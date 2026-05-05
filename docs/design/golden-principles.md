# Golden Principles — Code Quality Invariants

> Status: Active
> Date: 2026-05-05
> Source: OpenAI Harness Engineering — "golden principles encoded in repo + recurring cleanup"
> Hook: `fde-golden-principles` (userTriggered)

## Purpose

Golden principles are **mechanical, deterministic rules** that define "taste" for this codebase.
They prevent architectural drift in agent-generated code by encoding invariants that external
linters don't check.

Unlike lint rules (which check syntax and style), golden principles check **structural health**:
file size, abstraction boundaries, logging discipline, and import hygiene.

## Principles

### GP-01: Maximum File Size — 500 Lines

**Rule**: No Python file in `infra/docker/agents/` should exceed 500 lines.

**Rationale**: Files over 500 lines indicate the module is doing too much. Split into
focused modules with clear boundaries. This prevents the "god module" anti-pattern
that makes agent-generated code hard to review.

**Detection**: Count non-empty lines per `.py` file.

**Remediation**: Extract cohesive functions into a new module. Update imports.

---

### GP-02: No `print()` in Production Code

**Rule**: Production code (anything outside `tests/`, `scripts/`, `examples/`) must not
use `print()`. Use `logging.getLogger()` instead.

**Rationale**: `print()` output is unstructured, cannot be filtered by level, and
disappears in containerized environments. Structured logging enables observability.

**Detection**: Regex scan for `print(` in production files.

**Remediation**: Replace with `logger.info()`, `logger.debug()`, or `logger.warning()`.

---

### GP-03: All Modules Have Docstrings

**Rule**: Every `.py` file in `infra/docker/agents/` must have a module-level docstring
(triple-quoted string as the first statement).

**Rationale**: Module docstrings are the first thing a developer (or agent) reads when
navigating the codebase. They provide context without reading the implementation.

**Detection**: Parse first non-comment, non-blank line — must be `"""` or `'''`.

**Remediation**: Add a 1-3 line docstring explaining the module's responsibility.

---

### GP-04: No `import *`

**Rule**: No file may use `from module import *`.

**Rationale**: Star imports pollute the namespace, make it impossible to trace where
a name comes from, and break static analysis tools. They also make agent-generated
code harder to review because the reviewer can't see what's being used.

**Detection**: Regex scan for `from .* import \*`.

**Remediation**: Import specific names: `from module import ClassA, function_b`.

---

### GP-05: Maximum Function Length — 50 Lines

**Rule**: No function or method should exceed 50 lines (excluding docstring and decorators).

**Rationale**: Long functions indicate multiple responsibilities. They're harder to test,
harder to name, and harder for agents to modify without unintended side effects.

**Detection**: AST-based function body line count.

**Remediation**: Extract helper functions with descriptive names.

---

## Extension

To add a new principle:
1. Add it to this document with rule, rationale, detection, and remediation
2. Add a corresponding check function in `infra/docker/agents/golden_principles.py`
3. Register it with the `@register_principle` decorator
4. Add a BDD test in `tests/test_golden_principles.py`

## References

- OpenAI Harness Engineering: "taste invariants" encoded in repo
- ADR-012: Over-Engineering Mitigations (keep principles mechanical, not subjective)
- COE pattern: architectural drift from unchecked agent output
