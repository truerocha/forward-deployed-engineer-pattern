"""
Pipeline Graph — Regression surface mapping for branch evaluation.

Maps changed files to pipeline edges, finds consumers, and computes
the minimum test set that must pass for a given set of changes.

Design ref: docs/design/branch-evaluation-agent.md Section 8
"""

import ast
import logging
import re
from pathlib import Path

logger = logging.getLogger("fde.branch_evaluation.pipeline_graph")


# ─── Pipeline Edge Definitions ──────────────────────────────────────────────

PIPELINE_EDGES: dict[str, dict] = {
    "E1": {
        "producer": "src/evidence/facts_extractor.py",
        "consumer": "src/evidence/evidence_catalog.py",
        "contract": "src/contracts/schemas/evidence_catalog.schema.json",
        "description": "Facts extraction → Evidence catalog",
    },
    "E2": {
        "producer": "src/evidence/evidence_catalog.py",
        "consumer": "src/assessment/deterministic_reviewer.py",
        "contract": "src/contracts/schemas/question_evaluation.schema.json",
        "description": "Evidence catalog → Deterministic reviewer",
    },
    "E3": {
        "producer": "src/assessment/deterministic_reviewer.py",
        "consumer": "wafr/publish_tree.py",
        "contract": "src/contracts/schemas/publish/findings.schema.json",
        "description": "Deterministic reviewer → Publish tree",
    },
    "E4": {
        "producer": "wafr/publish_tree.py",
        "consumer": "wafr/publish_sanitizer.py",
        "contract": None,
        "description": "Publish tree → Publish sanitizer",
    },
    "E5": {
        "producer": "wafr/publish_sanitizer.py",
        "consumer": None,
        "contract": "src/contracts/schemas/publish/published_index.schema.json",
        "description": "Publish sanitizer → Published artifacts",
    },
    "E6": {
        "producer": None,
        "consumer": None,
        "contract": None,
        "description": "Published artifacts → Portal renderers",
    },
}

# Module name → edges it participates in
MODULE_EDGE_MAP: dict[str, list[str]] = {
    "facts_extractor": ["E1"],
    "evidence_catalog": ["E1", "E2"],
    "deterministic_reviewer": ["E2", "E3"],
    "publish_tree": ["E3", "E4"],
    "publish_sanitizer": ["E4", "E5"],
    "router": ["E1"],
    "orchestrator": ["E1", "E2", "E3", "E4"],
    "task_queue": ["E4"],
    "workspace_setup": ["E5"],
    "stream_callback": ["E6"],
}

# Artifact type → edges affected
TYPE_EDGE_MAP: dict[str, list[str]] = {
    "schema": ["E5"],
    "portal": ["E6"],
    "infrastructure": ["E4", "E5"],
    "knowledge": ["E2", "E3"],
    "prompt": ["E3", "E4"],
}


# ─── Import Graph Analysis ──────────────────────────────────────────────────

def _extract_imports(filepath: str) -> list[str]:
    """Extract imported module names from a Python file.

    Args:
        filepath: Path to the Python file.

    Returns:
        List of imported module/package names.
    """
    path = Path(filepath)
    if not path.exists() or not path.suffix == ".py":
        return []

    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    return imports


def _module_name_from_path(filepath: str) -> str:
    """Convert a file path to a Python module name.

    Args:
        filepath: Relative file path (e.g., 'src/evidence/facts_extractor.py').

    Returns:
        Module name (e.g., 'src.evidence.facts_extractor').
    """
    path = filepath.replace("\\", "/")
    if path.endswith(".py"):
        path = path[:-3]
    return path.replace("/", ".")


def _stem_from_path(filepath: str) -> str:
    """Get the stem (filename without extension) from a path."""
    return Path(filepath).stem


# ─── Public API ─────────────────────────────────────────────────────────────

def find_tests_for_module(filepath: str) -> list[str]:
    """Find test files that directly test a given module.

    Searches for:
    1. tests/test_<module_stem>.py
    2. tests/<package>/test_<module_stem>.py
    3. Any test file that imports the module

    Args:
        filepath: Path to the source module.

    Returns:
        List of test file paths.
    """
    stem = _stem_from_path(filepath)
    module_name = _module_name_from_path(filepath)
    tests: list[str] = []

    # Direct naming convention
    direct_test = Path(f"tests/test_{stem}.py")
    if direct_test.exists():
        tests.append(str(direct_test))

    # Nested test directories
    tests_dir = Path("tests")
    if tests_dir.exists():
        for test_file in tests_dir.rglob(f"test_{stem}.py"):
            test_path = str(test_file)
            if test_path not in tests:
                tests.append(test_path)

        # Import-based discovery: scan test files for imports of this module
        for test_file in tests_dir.rglob("test_*.py"):
            test_path = str(test_file)
            if test_path in tests:
                continue
            imports = _extract_imports(test_path)
            for imp in imports:
                if stem in imp or module_name in imp:
                    tests.append(test_path)
                    break

    return sorted(set(tests))


def find_consumers(filepath: str) -> list[str]:
    """Find source modules that import/consume the given module.

    Scans src/, wafr/, lambdas/, and infra/docker/agents/ for files
    that import the given module.

    Args:
        filepath: Path to the source module.

    Returns:
        List of consumer file paths.
    """
    stem = _stem_from_path(filepath)
    module_name = _module_name_from_path(filepath)
    consumers: list[str] = []

    search_dirs = [
        Path("src"),
        Path("wafr"),
        Path("lambdas"),
        Path("infra/docker/agents"),
    ]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for py_file in search_dir.rglob("*.py"):
            py_path = str(py_file)
            if py_path == filepath:
                continue
            imports = _extract_imports(py_path)
            for imp in imports:
                if stem in imp or module_name in imp:
                    consumers.append(py_path)
                    break

    return sorted(set(consumers))


def find_affected_edges(filepath: str) -> list[str]:
    """Determine which pipeline edges are affected by a file change.

    Uses both module-name matching and artifact-type heuristics.

    Args:
        filepath: Path to the changed file.

    Returns:
        List of affected edge identifiers (e.g., ['E1', 'E2']).
    """
    affected: set[str] = set()
    stem = _stem_from_path(filepath)
    fp = filepath.replace("\\", "/")

    # Module-level matching
    for module_name, edges in MODULE_EDGE_MAP.items():
        if module_name in stem or module_name in fp:
            affected.update(edges)

    # Type-level matching
    if "schemas/" in fp or fp.endswith(".schema.json"):
        affected.update(TYPE_EDGE_MAP.get("schema", []))
    elif "portal" in fp or "dashboard" in fp:
        affected.update(TYPE_EDGE_MAP.get("portal", []))
    elif fp.endswith(".tf") or "Dockerfile" in fp or "workflows/" in fp:
        affected.update(TYPE_EDGE_MAP.get("infrastructure", []))
    elif "knowledge" in fp or "mappings/" in fp:
        affected.update(TYPE_EDGE_MAP.get("knowledge", []))
    elif "prompts/" in fp:
        affected.update(TYPE_EDGE_MAP.get("prompt", []))

    # Contract file → both sides of the edge
    for edge_id, edge_def in PIPELINE_EDGES.items():
        contract = edge_def.get("contract")
        if contract and contract in fp:
            affected.add(edge_id)

    return sorted(affected)


def find_contract_tests(edge_id: str) -> list[str]:
    """Find contract tests for a specific pipeline edge.

    Contract tests validate the interface between producer and consumer.

    Args:
        edge_id: Pipeline edge identifier (e.g., 'E3').

    Returns:
        List of contract test file paths.
    """
    tests: list[str] = []
    tests_dir = Path("tests")

    if not tests_dir.exists():
        return tests

    # Look for contract-marked test files
    for test_file in tests_dir.rglob("test_*contract*.py"):
        tests.append(str(test_file))

    # Look for edge-specific test files
    edge_lower = edge_id.lower()
    for test_file in tests_dir.rglob(f"test_*{edge_lower}*.py"):
        tests.append(str(test_file))

    # Look for tests in a contracts/ subdirectory
    contracts_dir = tests_dir / "contracts"
    if contracts_dir.exists():
        for test_file in contracts_dir.rglob("test_*.py"):
            test_path = str(test_file)
            if test_path not in tests:
                tests.append(test_path)

    return sorted(set(tests))


def compute_regression_surface(changed_files: list[str]) -> list[str]:
    """Compute the minimum test set that must pass for a set of changes.

    Rules:
    1. Direct tests: tests that import or reference the changed module
    2. Consumer tests: tests for modules that consume the changed module's output
    3. Contract tests: cross-layer invariant tests for affected edges
    4. Smoke tests: always included (golden path validation)

    Args:
        changed_files: List of changed file paths.

    Returns:
        Sorted list of test file paths that must pass.
    """
    tests: set[str] = set()

    for filepath in changed_files:
        if not filepath.endswith(".py"):
            continue

        # Direct tests
        tests.update(find_tests_for_module(filepath))

        # Consumer tests
        for consumer in find_consumers(filepath):
            tests.update(find_tests_for_module(consumer))

        # Contract tests for affected edges
        for edge in find_affected_edges(filepath):
            tests.update(find_contract_tests(edge))

    # Always include smoke tests
    smoke_test = "tests/e2e/test_golden_path_smoke.py"
    if Path(smoke_test).exists():
        tests.add(smoke_test)

    logger.info(
        "Regression surface: %d tests for %d changed files",
        len(tests), len(changed_files),
    )
    return sorted(tests)
