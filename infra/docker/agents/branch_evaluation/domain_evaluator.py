"""
Domain Evaluator — Validates domain alignment and adversarial resilience.

Implements D4 (Domain Alignment) and D6 (Adversarial Resilience) from the design doc.
For this factory-template repo, domain alignment means FDE protocol compliance,
WAF framework alignment, and knowledge artifact correctness.

Design ref: docs/design/branch-evaluation-agent.md Sections 6.3, 6.4, 7
"""

import ast
import logging
import re
from pathlib import Path

from .artifact_classifier import ClassifiedFile
from .scoring_engine import DimensionScore, DEFAULT_WEIGHTS

logger = logging.getLogger("fde.branch_evaluation.domain_evaluator")


def evaluate_domain_alignment(files: list[ClassifiedFile]) -> DimensionScore:
    """D4: Domain Alignment — Artifacts align with WAF framework and FDE protocol.

    Checks:
    - Steering files have proper frontmatter (inclusion: manual/auto/fileMatch)
    - Knowledge artifacts reference valid WAF pillars
    - Hook files reference valid FDE protocol phases
    - Code modules follow hexagonal architecture layering
    - ADRs follow the project ADR format

    Args:
        files: Classified files to evaluate.

    Returns:
        DimensionScore for domain alignment.
    """
    issues: list[str] = []
    deductions = 0.0

    VALID_PILLARS = {
        "security", "operational_excellence", "reliability",
        "performance_efficiency", "cost_optimization", "sustainability",
    }

    for f in files:
        if f.status == "deleted":
            continue

        path = Path(f.path)
        if not path.exists():
            continue

        # Steering files must have frontmatter
        if f.artifact_type == "knowledge" and ".kiro/steering/" in f.path:
            try:
                content = path.read_text(encoding="utf-8")
                if not content.startswith("---"):
                    issues.append(f"Steering file missing frontmatter: {f.path}")
                    deductions += 1.0
                else:
                    parts = content.split("---", 2)
                    if len(parts) >= 3 and "inclusion:" not in parts[1]:
                        issues.append(f"Steering file missing 'inclusion:' in frontmatter: {f.path}")
                        deductions += 0.5
            except Exception:
                pass

        # ADR files must follow format
        if f.artifact_type == "documentation" and "adr/" in f.path.lower():
            try:
                content = path.read_text(encoding="utf-8")
                required_sections = ["## Status", "## Date", "## Context", "## Decision", "## Consequences"]
                for section in required_sections:
                    if section not in content:
                        issues.append(f"ADR missing section '{section}': {f.path}")
                        deductions += 0.3
            except Exception:
                pass

        # Knowledge corpus files must reference valid pillars
        if f.artifact_type == "knowledge" and "waf_" in f.path and f.path.endswith(".py"):
            try:
                content = path.read_text(encoding="utf-8")
                pillar_refs = re.findall(r'pillar["\s:=]+["\'](\w+)["\']', content, re.IGNORECASE)
                for ref in pillar_refs:
                    if ref.lower() not in VALID_PILLARS:
                        issues.append(f"Invalid pillar reference '{ref}' in {f.path}")
                        deductions += 1.0
            except Exception:
                pass

        # Hook files should reference valid protocol concepts
        if f.artifact_type == "hook" and f.path.endswith(".hook"):
            try:
                import json
                content = path.read_text(encoding="utf-8")
                hook = json.loads(content)
                description = hook.get("description", "").lower()
                if not any(kw in description for kw in ["gate", "validation", "review", "check", "trigger", "scan", "detect"]):
                    issues.append(f"Hook description doesn't indicate protocol role: {f.path}")
                    deductions += 0.3
            except Exception:
                pass

        # Python agent modules should follow layering
        if f.artifact_type == "code" and "infra/docker/agents/" in f.path:
            try:
                content = path.read_text(encoding="utf-8")
                tree = ast.parse(content)

                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        if "portal" in (node.module or ""):
                            issues.append(f"Cross-layer import (agent->portal) in {f.path}")
                            deductions += 2.0
            except Exception:
                pass

    score = max(0.0, 10.0 - deductions)
    return DimensionScore(
        name="domain_alignment",
        score=min(10.0, score),
        weight=DEFAULT_WEIGHTS["domain_alignment"],
        issues=issues,
        details={"deductions": deductions},
    )


def evaluate_adversarial_resilience(files: list[ClassifiedFile]) -> DimensionScore:
    """D6: Adversarial Resilience — Code handles unexpected inputs gracefully.

    Checks:
    - No bare except clauses (swallows errors silently)
    - Input validation on public functions (type hints + guards)
    - Error handling patterns (try/except with specific exceptions)
    - No eval() or exec() usage (injection risk)
    - No hardcoded secrets patterns
    - Defensive coding indicators (assertions, guards, early returns)

    Args:
        files: Classified files to evaluate.

    Returns:
        DimensionScore for adversarial resilience.
    """
    issues: list[str] = []
    deductions = 0.0
    checks_performed = 0

    SECRET_PATTERNS = [
        r'(?i)(password|secret|token|api_key)\s*=\s*["\'][^"\']{8,}["\']',
        r'AKIA[0-9A-Z]{16}',
        r'(?i)bearer\s+[a-zA-Z0-9\-._~+/]+=*',
    ]

    for f in files:
        if f.status == "deleted":
            continue
        if f.artifact_type != "code" or not f.path.endswith(".py"):
            continue

        path = Path(f.path)
        if not path.exists():
            continue

        try:
            content = path.read_text(encoding="utf-8")
            checks_performed += 1

            # Check 1: Bare except clauses
            bare_excepts = len(re.findall(r'\bexcept\s*:', content))
            if bare_excepts > 0:
                issues.append(f"Bare except clause(s) in {f.path} ({bare_excepts} found)")
                deductions += bare_excepts * 0.5

            # Check 2: eval/exec usage (injection risk)
            if re.search(r'\b(eval|exec)\s*\(', content):
                issues.append(f"eval()/exec() usage in {f.path} — injection risk")
                deductions += 2.0

            # Check 3: Hardcoded secrets
            for pattern in SECRET_PATTERNS:
                matches = re.findall(pattern, content)
                if matches:
                    issues.append(f"Potential hardcoded secret in {f.path}")
                    deductions += 3.0
                    break

            # Check 4: Public functions without type hints (minor)
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not node.name.startswith("_"):
                        if node.returns is None and node.name != "__init__":
                            deductions += 0.1

            # Check 5: Defensive coding indicators (positive signal)
            has_guards = bool(re.search(r'if not \w+:', content))
            has_validation = bool(re.search(r'raise (ValueError|TypeError|KeyError)', content))
            has_logging = "logger." in content or "logging." in content

            if has_guards or has_validation:
                deductions -= 0.3
            if has_logging:
                deductions -= 0.2

        except Exception as e:
            logger.debug("Adversarial check skipped for %s: %s", f.path, e)

    if checks_performed == 0:
        score = 8.0
    else:
        score = max(0.0, min(10.0, 10.0 - deductions))

    return DimensionScore(
        name="adversarial_resilience",
        score=score,
        weight=DEFAULT_WEIGHTS["adversarial_resilience"],
        issues=issues,
        details={"checks_performed": checks_performed, "deductions": round(deductions, 2)},
    )
