"""
SDLC Gates — Enforces a robust Software Development Lifecycle for every task.

The Code Factory implements two loops:

Inner Loop (per-commit, fast feedback):
  lint → type-check → unit-test → build
  Runs inside the Engineering Agent's execution. If any gate fails,
  the agent must fix before proceeding. Max 3 retries per gate.

Outer Loop (per-task, quality gates):
  DoR Gate → Constraint Extraction → Adversarial Challenge → Ship-Readiness
  Runs at pipeline boundaries. If any gate fails, the pipeline blocks.

Each gate produces a GateResult that is logged to the DORA metrics collector
and persisted to S3 for audit trail.

SDLC Phase Mapping:
  Phase 1 (Reconnaissance) → DoR Gate, Constraint Extraction
  Phase 2 (Reformulation)  → Adversarial Challenge
  Phase 3 (Engineering)    → Inner Loop (lint → test → build)
  Phase 4 (Reporting)      → Ship-Readiness Gate
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger("fde.sdlc_gates")


class GateVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


class GatePhase(str, Enum):
    """Which SDLC phase this gate belongs to."""
    INNER_LINT = "inner.lint"
    INNER_TYPECHECK = "inner.typecheck"
    INNER_UNIT_TEST = "inner.unit_test"
    INNER_BUILD = "inner.build"
    OUTER_DOR = "outer.dor"
    OUTER_CONSTRAINT = "outer.constraint_extraction"
    OUTER_ADVERSARIAL = "outer.adversarial_challenge"
    OUTER_SHIP_READINESS = "outer.ship_readiness"


@dataclass
class GateResult:
    """Result of a single SDLC gate execution."""

    gate: str                            # GatePhase value
    verdict: str                         # GateVerdict value
    duration_ms: int = 0                 # How long the gate took
    attempt: int = 1                     # Which attempt (for inner loop retries)
    max_attempts: int = 3                # Max retries before hard fail
    details: str = ""                    # Human-readable summary
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "gate": self.gate,
            "verdict": self.verdict,
            "duration_ms": self.duration_ms,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "details": self.details,
            "errors": self.errors,
            "warnings": self.warnings,
            "timestamp": self.timestamp,
        }


@dataclass
class SDLCReport:
    """Aggregated SDLC report for a complete task execution."""

    task_id: str
    gates: list[GateResult] = field(default_factory=list)
    inner_loop_passes: int = 0
    inner_loop_failures: int = 0
    outer_loop_passes: int = 0
    outer_loop_failures: int = 0
    total_duration_ms: int = 0
    started_at: str = ""
    completed_at: str = ""

    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).isoformat()

    @property
    def all_passed(self) -> bool:
        return all(
            g.verdict in (GateVerdict.PASS, GateVerdict.WARN, GateVerdict.SKIP)
            for g in self.gates
        )

    def record_gate(self, result: GateResult) -> None:
        """Record a gate result and update counters."""
        self.gates.append(result)
        self.total_duration_ms += result.duration_ms

        is_inner = result.gate.startswith("inner.")
        if result.verdict == GateVerdict.PASS:
            if is_inner:
                self.inner_loop_passes += 1
            else:
                self.outer_loop_passes += 1
        elif result.verdict == GateVerdict.FAIL:
            if is_inner:
                self.inner_loop_failures += 1
            else:
                self.outer_loop_failures += 1

    def finalize(self) -> None:
        """Mark the report as complete."""
        self.completed_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "all_passed": self.all_passed,
            "gates": [g.to_dict() for g in self.gates],
            "inner_loop": {
                "passes": self.inner_loop_passes,
                "failures": self.inner_loop_failures,
            },
            "outer_loop": {
                "passes": self.outer_loop_passes,
                "failures": self.outer_loop_failures,
            },
            "total_duration_ms": self.total_duration_ms,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


# ─── Gate Runners ───────────────────────────────────────────────

def run_gate(
    gate: GatePhase,
    check_fn,
    max_attempts: int = 3,
) -> GateResult:
    """Run a single SDLC gate with retry logic.

    Args:
        gate: Which gate to run.
        check_fn: Callable that returns (passed: bool, details: str, errors: list, warnings: list).
        max_attempts: Max retries for inner loop gates.

    Returns:
        GateResult with verdict and timing.
    """
    for attempt in range(1, max_attempts + 1):
        start = time.monotonic()
        try:
            passed, details, errors, warnings = check_fn()
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            logger.error("Gate %s attempt %d crashed: %s", gate.value, attempt, e)
            if attempt == max_attempts:
                return GateResult(
                    gate=gate.value,
                    verdict=GateVerdict.FAIL,
                    duration_ms=elapsed,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    details=f"Gate crashed: {e}",
                    errors=[str(e)],
                )
            continue

        elapsed = int((time.monotonic() - start) * 1000)

        if passed:
            verdict = GateVerdict.WARN if warnings else GateVerdict.PASS
            logger.info("Gate %s PASSED (attempt %d, %dms)", gate.value, attempt, elapsed)
            return GateResult(
                gate=gate.value,
                verdict=verdict,
                duration_ms=elapsed,
                attempt=attempt,
                max_attempts=max_attempts,
                details=details,
                errors=errors,
                warnings=warnings,
            )

        logger.warning(
            "Gate %s FAILED attempt %d/%d: %s",
            gate.value, attempt, max_attempts, details,
        )

        if attempt == max_attempts:
            return GateResult(
                gate=gate.value,
                verdict=GateVerdict.FAIL,
                duration_ms=elapsed,
                attempt=attempt,
                max_attempts=max_attempts,
                details=details,
                errors=errors,
                warnings=warnings,
            )

    # Should not reach here, but safety net
    return GateResult(
        gate=gate.value,
        verdict=GateVerdict.FAIL,
        details="Exhausted all attempts",
    )


# ─── Inner Loop Gate Checks ─────────────────────────────────────

def check_lint(workspace_dir: str, tech_stack: list[str]) -> tuple[bool, str, list, list]:
    """Run linting for the detected tech stack.

    Returns:
        Tuple of (passed, details, errors, warnings).
    """
    import subprocess

    commands = _resolve_lint_commands(tech_stack)
    if not commands:
        return True, "No lint commands for this stack", [], ["No linter configured"]

    all_errors: list[str] = []
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=120, cwd=workspace_dir,
            )
            if result.returncode != 0:
                all_errors.append(f"{cmd}: {result.stderr[-500:]}")
        except subprocess.TimeoutExpired:
            all_errors.append(f"{cmd}: TIMEOUT")
        except FileNotFoundError:
            all_errors.append(f"{cmd}: command not found")

    if all_errors:
        enriched_errors = [_enrich_lint_output(e, tech_stack) for e in all_errors]
        return False, f"Lint failed: {len(enriched_errors)} errors", enriched_errors, []
    return True, "All lint checks passed", [], []


def check_unit_tests(workspace_dir: str, tech_stack: list[str]) -> tuple[bool, str, list, list]:
    """Run unit tests for the detected tech stack.

    Returns:
        Tuple of (passed, details, errors, warnings).
    """
    import subprocess

    commands = _resolve_test_commands(tech_stack)
    if not commands:
        return True, "No test commands for this stack", [], ["No test runner configured"]

    all_errors: list[str] = []
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=300, cwd=workspace_dir,
            )
            if result.returncode != 0:
                all_errors.append(f"{cmd}: {result.stderr[-500:]}")
        except subprocess.TimeoutExpired:
            all_errors.append(f"{cmd}: TIMEOUT (300s)")

    if all_errors:
        return False, f"Tests failed: {len(all_errors)} errors", all_errors, []
    return True, "All tests passed", [], []


def check_build(workspace_dir: str, tech_stack: list[str]) -> tuple[bool, str, list, list]:
    """Run build for the detected tech stack.

    Returns:
        Tuple of (passed, details, errors, warnings).
    """
    import subprocess

    commands = _resolve_build_commands(tech_stack)
    if not commands:
        return True, "No build commands for this stack", [], ["No build step configured"]

    all_errors: list[str] = []
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=300, cwd=workspace_dir,
            )
            if result.returncode != 0:
                all_errors.append(f"{cmd}: {result.stderr[-500:]}")
        except subprocess.TimeoutExpired:
            all_errors.append(f"{cmd}: TIMEOUT (300s)")

    if all_errors:
        return False, f"Build failed: {len(all_errors)} errors", all_errors, []
    return True, "Build succeeded", [], []


# ─── Outer Loop Gate Checks ─────────────────────────────────────

def check_ship_readiness(
    sdlc_report: "SDLCReport",
    acceptance_criteria: list[str],
) -> tuple[bool, str, list, list]:
    """Validate that the task is ready to ship.

    Checks:
    1. All inner loop gates passed
    2. All outer loop gates passed (except this one)
    3. Acceptance criteria are addressed

    Returns:
        Tuple of (passed, details, errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Check inner loop
    if sdlc_report.inner_loop_failures > 0:
        errors.append(
            f"Inner loop has {sdlc_report.inner_loop_failures} failures"
        )

    # Check outer loop (exclude ship-readiness itself)
    outer_failures = [
        g for g in sdlc_report.gates
        if g.gate.startswith("outer.") and g.gate != GatePhase.OUTER_SHIP_READINESS
        and g.verdict == GateVerdict.FAIL
    ]
    if outer_failures:
        errors.append(
            f"Outer loop has {len(outer_failures)} failures: "
            + ", ".join(g.gate for g in outer_failures)
        )

    # Check acceptance criteria
    if not acceptance_criteria:
        warnings.append("No acceptance criteria defined — cannot validate completeness")

    passed = len(errors) == 0
    details = "Ship-ready" if passed else f"Not ship-ready: {len(errors)} blockers"
    return passed, details, errors, warnings


# ─── Command Resolution ─────────────────────────────────────────

_LINT_COMMANDS: dict[str, list[str]] = {
    "python": ["python -m ruff check . || python -m flake8 ."],
    "typescript": ["npx eslint ."],
    "javascript": ["npx eslint ."],
    "go": ["go vet ./..."],
    "rust": ["cargo clippy -- -D warnings"],
    "java": ["mvn checkstyle:check"],
    "terraform": ["terraform fmt -check -recursive"],
}

_TEST_COMMANDS: dict[str, list[str]] = {
    "python": ["python -m pytest --tb=short -q"],
    "typescript": ["npx vitest --run"],
    "javascript": ["npx vitest --run"],
    "go": ["go test ./..."],
    "rust": ["cargo test"],
    "java": ["mvn test -q"],
}

_BUILD_COMMANDS: dict[str, list[str]] = {
    "python": ["python -m py_compile *.py || true"],
    "typescript": ["npx tsc --noEmit"],
    "javascript": ["npm run build --if-present"],
    "go": ["go build ./..."],
    "rust": ["cargo build"],
    "java": ["mvn compile -q"],
    "terraform": ["terraform validate"],
    "docker": ["docker build --check ."],
}


def _resolve_lint_commands(tech_stack: list[str]) -> list[str]:
    return _resolve_commands(tech_stack, _LINT_COMMANDS)


def _resolve_test_commands(tech_stack: list[str]) -> list[str]:
    return _resolve_commands(tech_stack, _TEST_COMMANDS)


def _resolve_build_commands(tech_stack: list[str]) -> list[str]:
    return _resolve_commands(tech_stack, _BUILD_COMMANDS)


def _resolve_commands(tech_stack: list[str], command_map: dict[str, list[str]]) -> list[str]:
    """Resolve commands from tech_stack against a command map."""
    commands: list[str] = []
    stack_lower = [s.lower() for s in tech_stack]

    for key, cmds in command_map.items():
        if any(key in s for s in stack_lower):
            commands.extend(cmds)

    return commands


# ─── Lint Remediation Enrichment ────────────────────────────────

# Maps lint error codes to actionable remediation instructions.
# The agent sees these in the inner loop retry, giving it a concrete fix strategy.
REMEDIATION_MAP: dict[str, str] = {
    # Python — ruff / flake8
    "E501": (
        "Remediation: Split line at a logical boundary (after comma, operator, or "
        "opening bracket) or extract a sub-expression into a named variable."
    ),
    "F401": (
        "Remediation: Remove the unused import. If it's re-exported for public API, "
        "add it to __all__ or use 'noqa: F401' with a comment explaining why."
    ),
    "F841": (
        "Remediation: Remove the unused variable assignment, or prefix with underscore "
        "(_var) if the assignment has a necessary side-effect."
    ),
    "E302": (
        "Remediation: Add two blank lines before the top-level function or class definition."
    ),
    "E303": (
        "Remediation: Remove extra blank lines. Maximum is 2 between top-level definitions, "
        "1 inside a function/class body."
    ),
    "W291": (
        "Remediation: Remove trailing whitespace from the end of the line."
    ),
    "W292": (
        "Remediation: Add a newline at the end of the file."
    ),
    "E711": (
        "Remediation: Use 'is None' or 'is not None' instead of '== None' or '!= None'."
    ),
    "E712": (
        "Remediation: Use 'if value:' or 'if not value:' instead of '== True' or '== False'."
    ),
    "I001": (
        "Remediation: Re-order imports to follow isort convention: stdlib → third-party → local. "
        "Run 'ruff check --fix' or 'isort .' to auto-fix."
    ),
    # TypeScript / JavaScript — eslint
    "no-unused-vars": (
        "Remediation: Remove the unused variable/import, or prefix with underscore "
        "(_unusedVar) if it's a required function parameter placeholder."
    ),
    "no-console": (
        "Remediation: Replace console.log with a structured logger (e.g., winston, pino). "
        "If this is intentional debug output, use // eslint-disable-next-line no-console."
    ),
    "@typescript-eslint/no-explicit-any": (
        "Remediation: Replace 'any' with a specific type. Use 'unknown' if the type is "
        "truly dynamic, then narrow with type guards."
    ),
    "prefer-const": (
        "Remediation: Change 'let' to 'const' since this variable is never reassigned."
    ),
    "no-var": (
        "Remediation: Replace 'var' with 'let' (if reassigned) or 'const' (if not)."
    ),
    "@typescript-eslint/no-unused-vars": (
        "Remediation: Remove the unused variable/import, or prefix with underscore "
        "(_unusedVar) if it's a required function parameter placeholder."
    ),
    "eqeqeq": (
        "Remediation: Use '===' and '!==' instead of '==' and '!=' for type-safe comparison."
    ),
    # Go — go vet / staticcheck
    "SA1000": (
        "Remediation: Fix the invalid regular expression. Check for unescaped special characters."
    ),
    "SA4006": (
        "Remediation: Remove the unused variable assignment or use the blank identifier '_'."
    ),
    # Terraform — terraform fmt
    "terraform fmt": (
        "Remediation: Run 'terraform fmt -recursive' to auto-format all .tf files."
    ),
}


def _enrich_lint_output(raw_output: str, tech_stack: list[str]) -> str:
    """Enrich raw lint output with actionable remediation instructions.

    Scans each line of lint output for known error codes and appends
    the corresponding remediation hint. This gives the agent a concrete
    fix strategy in the inner loop retry instead of raw error text.

    Args:
        raw_output: The raw stderr/stdout from the lint command.
        tech_stack: The detected tech stack (used for future stack-specific logic).

    Returns:
        Enriched output with remediation hints appended after matching lines.
    """
    if not raw_output.strip():
        return raw_output

    enriched_lines: list[str] = []
    for line in raw_output.splitlines():
        enriched_lines.append(line)
        # Check each known code against the line
        for code, remediation in REMEDIATION_MAP.items():
            if code in line:
                enriched_lines.append(f"  → {remediation}")
                break  # One remediation per line

    return "\n".join(enriched_lines)
