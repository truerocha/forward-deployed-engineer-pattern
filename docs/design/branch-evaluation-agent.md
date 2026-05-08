# Branch Evaluation Agent — Design Document

> **Status**: Draft  
> **Author**: FDE Protocol  
> **Date**: 2026-05-07  
> **Epic**: Online Enrichment Mode (#86)  
> **Scope**: Automated quality gate for feature branch evaluation before merge  
> **ADR**: Pending (recommend ADR-0040)

---

## 1. Problem Statement

Feature branches in the Cognitive WAFR project require manual review to validate:
- Structural correctness of artifacts (schemas, code, knowledge)
- Convention compliance with project patterns
- Backward compatibility with existing consumers
- Domain alignment with WAF framework
- Adversarial resilience (edge cases, malformed inputs)
- Pipeline impact (downstream consumer safety)

This is time-consuming, error-prone, and inconsistent across reviewers. An automated evaluation agent can provide deterministic, reproducible quality scoring with adversarial probing — augmenting (not replacing) human review.

---

## 2. Design Goals

| Goal | Rationale |
|------|-----------|
| **Deterministic scoring** | Same branch state always produces same score |
| **Artifact-type-aware** | Different evaluation strategies for code vs knowledge vs schema vs prompt |
| **Pipeline-aware** | Understands producer→consumer edges, not just individual files |
| **Adversarial by default** | Generates attack inputs, not just happy-path validation |
| **Score-gated merge** | Configurable threshold below which merge is blocked |
| **Incremental** | Evaluates only the delta (changed files), not the entire repo |
| **Auditable** | Produces a structured evaluation report stored as PR artifact |

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        TRIGGER LAYER                                     │
│  GitHub Action (PR opened/updated) OR Kiro Hook (userTriggered)         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     PHASE 0: INTAKE & CLASSIFICATION                     │
│                                                                          │
│  1. Compute diff (main...feature-branch)                                 │
│  2. Classify each changed file by artifact type                          │
│  3. Identify affected pipeline edges (E1-E6)                             │
│  4. Load applicable régua (quality reference artifacts)                  │
│  5. Resolve the parent issue's acceptance criteria                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     PHASE 1: STRUCTURAL VALIDATION                       │
│                                                                          │
│  Per artifact type:                                                      │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  ┌───────────────┐  │
│  │   Schema    │  │    Code      │  │  Knowledge │  │    Prompt     │  │
│  │  Evaluator  │  │  Evaluator   │  │  Evaluator │  │  Evaluator    │  │
│  └─────────────┘  └──────────────┘  └────────────┘  └───────────────┘  │
│                                                                          │
│  Outputs: per-file structural score + issue list                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     PHASE 2: CONVENTION & COMPATIBILITY                   │
│                                                                          │
│  1. Convention compliance check (naming, patterns, imports)              │
│  2. Backward compatibility analysis (schema evolution rules)             │
│  3. Cross-reference with existing consumers                              │
│  4. Test execution (scoped to affected modules)                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     PHASE 3: ADVERSARIAL / RED TEAM                       │
│                                                                          │
│  1. Generate adversarial inputs per artifact type                        │
│  2. Boundary value probing                                               │
│  3. Conditional logic bypass attempts                                    │
│  4. Pipeline poisoning scenarios                                         │
│  5. Regression surface analysis                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     PHASE 4: DOMAIN VALIDATION                            │
│                                                                          │
│  1. WAF corpus alignment (pillar enums, question IDs, BP refs)           │
│  2. Knowledge artifact domain truth verification                         │
│  3. Prompt governance compliance (hash, version, template)               │
│  4. 5W2H reasoning validation                                            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     PHASE 5: SCORING & DECISION                           │
│                                                                          │
│  1. Compute per-dimension scores (0-10)                                  │
│  2. Apply dimension weights                                              │
│  3. Compute aggregate score                                              │
│  4. Apply decision thresholds                                            │
│  5. Generate evaluation report                                           │
│  6. Post PR comment with verdict + score breakdown                       │
│  7. Set GitHub check status (pass/fail)                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Artifact Type Classification

The agent classifies each changed file into one of four artifact types. Each type has a different evaluation strategy.

| Artifact Type | File Patterns | Evaluation Strategy |
|---------------|---------------|---------------------|
| **Schema** | `src/contracts/schemas/**/*.json`, `*.schema.json` | Meta-validation + instance generation + adversarial probing |
| **Code** | `src/**/*.py`, `wafr/**/*.py`, `lambdas/**/*.py` | Lint + type check + test execution + contract verification |
| **Knowledge** | `config/mappings/*.yaml`, `config/mappings/*.json`, `data/*.json` | Domain truth verification + coverage completeness + semantic correctness |
| **Prompt** | `prompts/**/*.md`, `prompts/**/*.txt` | Hash governance + template completeness + injection resistance |
| **Infrastructure** | `infra/**/*.tf`, `Dockerfile`, `.github/workflows/*.yml` | Plan validation + security scan + drift detection |
| **Documentation** | `docs/**/*.md`, `README.md` | Link validation + drift gate + completeness |
| **Test** | `tests/**/*.py` | Coverage analysis + assertion quality + fixture governance |

---

## 5. Evaluation Dimensions & Scoring Rubric

### 5.1 Dimension Definitions

Each dimension is scored 0-10 independently.

#### D1: Structural Validity (Weight: 20%)

| Score | Criteria |
|-------|----------|
| 10 | All artifacts pass meta-validation. No syntax errors. All required fields present. Types correct. |
| 7 | Minor issues (e.g., missing optional descriptions) but structurally sound. |
| 5 | Some structural issues that don't break consumers but indicate incomplete work. |
| 3 | Structural errors that would cause runtime failures in some consumers. |
| 0 | Invalid artifacts. Parse failures. Missing required fields. |

**Evaluation method by artifact type**:
- Schema: `Draft202012Validator.check_schema()` + `jsonschema` meta-validation
- Code: `ruff check` + `mypy` + `python -m compileall`
- Knowledge: YAML/JSON parse + schema validation against governing schema
- Prompt: Template placeholder completeness + markdown structure

---

#### D2: Convention Compliance (Weight: 15%)

| Score | Criteria |
|-------|----------|
| 10 | Follows all project conventions. Naming, structure, imports, patterns match existing code. |
| 7 | Minor deviations (e.g., slightly different docstring style) but recognizably consistent. |
| 5 | Noticeable deviations that create inconsistency but don't break functionality. |
| 3 | Significant departures from project patterns. Introduces new conventions without justification. |
| 0 | Completely ignores project conventions. Foreign patterns. |

**Convention checklist** (project-specific):
- `$schema` and `$id` fields in JSON schemas follow `https://wafr.dev/schemas/` pattern
- Python modules follow hexagonal architecture (ports/adapters separation)
- Test files mirror source structure (`src/foo/bar.py` → `tests/foo/test_bar.py`)
- YAML mappings use snake_case keys
- Enum values use snake_case
- ID patterns follow `^{prefix}-[0-9a-f]{16}$`
- Imports follow plane layering (Data → Knowledge → Cognitive, never reverse)

---

#### D3: Backward Compatibility (Weight: 20%)

| Score | Criteria |
|-------|----------|
| 10 | Proven backward-compatible via tests. Old instances validate against new schema. No breaking changes. |
| 7 | Likely compatible (new fields optional, no removals) but not explicitly tested. |
| 5 | Ambiguous — changes could break some consumers depending on their validation strictness. |
| 3 | Breaking change identified but with migration path documented. |
| 0 | Breaking change with no migration path. Existing consumers will fail. |

**Evaluation method**:
- Schema: Generate instances conforming to OLD schema → validate against NEW schema
- Code: Run existing test suite against modified module → all pass = compatible
- Knowledge: Verify all existing consumers still find expected keys/values
- API: Check function signatures — no removed params, no type changes on existing params

**Breaking change detection rules**:
```
BREAKING (score ≤ 3):
  - Removing a field from schema
  - Adding a field to `required` array
  - Narrowing an enum (removing values)
  - Changing a field type
  - Removing a function/method from public API
  - Changing function signature (removing params, changing types)

NON-BREAKING (score ≥ 7):
  - Adding optional fields
  - Widening an enum (adding values)
  - Adding new functions/methods
  - Adding new files/modules
  - Relaxing validation (e.g., removing maxLength)
```

---

#### D4: Domain Alignment (Weight: 15%)

| Score | Criteria |
|-------|----------|
| 10 | Verified against authoritative domain source. Enums match corpus. Semantics correct. |
| 7 | Plausible domain alignment but not explicitly verified against source of truth. |
| 5 | Partially aligned — some values correct, others unverifiable. |
| 3 | Contradicts domain source in minor ways (e.g., wrong pillar assignment). |
| 0 | Fundamentally misaligned with WAF framework or domain model. |

**Domain sources of truth** (project-specific):
- Pillar names/enums → `src/knowledge/waf_*_corpus.py`
- Question IDs → `config/waf_knowledge_base.yaml`
- Best practice IDs → `config/mappings/bp_descriptions.json`
- Evidence types → `config/mappings/evidence_patterns.yaml`
- Fact types → `config/mappings/fact_type_question_map.yaml`
- Risk levels → `src/assessment/risk_engine.py`

---

#### D5: Test Coverage (Weight: 15%)

| Score | Criteria |
|-------|----------|
| 10 | Happy path + sad path + edge cases + adversarial + backward compat tests. All pass. |
| 7 | Happy path + basic rejection tests. All pass. Some edge cases missing. |
| 5 | Happy path tests only. Pass. No negative testing. |
| 3 | Tests exist but some fail or are incomplete. |
| 0 | No tests for new/modified code. |

**Test quality indicators**:
- Assertion density: ≥2 assertions per test function
- Negative testing: at least 1 rejection test per validation rule
- Parametrization: boundary values tested via `@pytest.mark.parametrize`
- Fixture governance: follows `docs/testing/fixture-governance.md`
- Marker usage: appropriate pytest markers applied (`contract`, `red_team`, etc.)

---

#### D6: Adversarial Resilience (Weight: 10%)

| Score | Criteria |
|-------|----------|
| 10 | Survives all generated adversarial probes. No unexpected accepts/rejects. |
| 7 | Survives most probes. 1-2 minor gaps identified but non-exploitable. |
| 5 | Some adversarial inputs bypass validation. Gaps are documented. |
| 3 | Multiple adversarial bypasses. Validation is porous. |
| 0 | Trivial adversarial inputs bypass validation. No defensive coding. |

**Adversarial probe categories** (detailed in Section 7):
- Type coercion attacks
- Boundary value exploitation
- Pattern bypass attempts
- Conditional logic circumvention
- Injection attacks (prompt, SQL, path traversal)
- State manipulation (race conditions, partial writes)

---

#### D7: Documentation (Weight: 5%)

| Score | Criteria |
|-------|----------|
| 10 | Complete README, inline docs, lifecycle diagram, consumer map, validation instructions. |
| 7 | Good documentation covering purpose and usage. Some gaps in edge cases. |
| 5 | Basic documentation. Purpose clear but usage details missing. |
| 3 | Minimal or outdated documentation. |
| 0 | No documentation for new artifacts. |

---

### 5.2 Aggregate Score Computation

```python
def compute_aggregate_score(dimensions: dict[str, float]) -> float:
    """
    Compute weighted aggregate score.
    
    Args:
        dimensions: Dict of dimension_id -> score (0-10)
    
    Returns:
        Weighted aggregate (0-10)
    """
    weights = {
        "structural_validity": 0.20,
        "convention_compliance": 0.15,
        "backward_compatibility": 0.20,
        "domain_alignment": 0.15,
        "test_coverage": 0.15,
        "adversarial_resilience": 0.10,
        "documentation": 0.05,
    }
    
    return sum(
        dimensions[dim] * weight
        for dim, weight in weights.items()
    )
```

### 5.3 Decision Thresholds

| Aggregate Score | Verdict | Action |
|-----------------|---------|--------|
| **≥ 8.0** | 🟢 PASS | Auto-approve. Merge eligible (if CI green). |
| **7.0 – 7.9** | 🟡 CONDITIONAL PASS | Approve with noted observations. Human review recommended but not blocking. |
| **5.0 – 6.9** | 🟠 CONDITIONAL FAIL | Block merge. Issues identified. Author must address before re-evaluation. |
| **< 5.0** | 🔴 FAIL | Block merge. Significant issues. Requires rework. |

### 5.4 Dimension Veto Rules

Regardless of aggregate score, certain dimension scores trigger automatic FAIL:

| Veto Rule | Condition | Rationale |
|-----------|-----------|-----------|
| **Structural veto** | D1 < 3 | Broken artifacts cannot be merged regardless of other qualities |
| **Compatibility veto** | D3 < 3 | Breaking changes require explicit human approval |
| **Domain veto** | D4 < 3 | Domain misalignment propagates silently through the pipeline |

---

## 6. Per-Artifact-Type Evaluation Protocols

### 6.1 Schema Evaluation Protocol

```
INPUT: Changed/new .schema.json files

STEP 1 — Meta-validation
  - Load schema
  - Run Draft202012Validator.check_schema(schema)
  - Verify $schema, $id, title, description present
  - Verify $id follows project pattern

STEP 2 — Convention check
  - additionalProperties: false on closed objects
  - required array present for mandatory fields
  - Enum values use snake_case
  - ID fields have pattern constraints
  - $defs used for reusable sub-schemas

STEP 3 — Instance generation (happy path)
  - Generate minimal valid instance
  - Validate against schema → must pass
  - Generate fully-populated instance (all optional fields)
  - Validate → must pass

STEP 4 — Adversarial probing (see Section 7)
  - Generate invalid instances per probe category
  - Validate → must REJECT each one

STEP 5 — Backward compatibility (if modified schema)
  - Load OLD schema from main branch
  - Generate valid instance against OLD schema
  - Validate against NEW schema → must pass (non-breaking)
  - Check: no fields removed from schema
  - Check: no fields added to required array
  - Check: no enum values removed

STEP 6 — Consumer impact
  - Identify downstream consumers (from README or imports)
  - Verify consumer code can handle new optional fields gracefully
```

### 6.2 Code Evaluation Protocol

```
INPUT: Changed/new .py files

STEP 1 — Static analysis
  - ruff check (lint)
  - mypy (type check)
  - python -m compileall (syntax)

STEP 2 — Convention check
  - Import layering (no cross-plane imports)
  - Hexagonal architecture compliance
  - Naming conventions (snake_case functions, PascalCase classes)
  - Docstrings on public API

STEP 3 — Test execution
  - Run tests scoped to changed module
  - Verify coverage ≥ 80% on new code
  - Check for new test files matching source structure

STEP 4 — Contract verification
  - If module produces artifacts: validate output against schema
  - If module consumes artifacts: verify it handles all schema-valid inputs
  - Run cross-layer contract tests (pytest -m contract)

STEP 5 — Adversarial scenarios
  - Identify error paths: what happens on invalid input?
  - Verify graceful degradation (no crashes, proper error types)
  - Check for unhandled exceptions in new code paths

STEP 6 — Pipeline impact
  - Identify producer→consumer edges affected
  - Run downstream consumer tests
  - Verify no regression in existing test suite (make test)
```

### 6.3 Knowledge Artifact Evaluation Protocol

```
INPUT: Changed/new YAML/JSON in config/mappings/ or data/

STEP 1 — Structural validation
  - Parse YAML/JSON (no syntax errors)
  - Validate against governing schema (if exists)
  - Verify all required keys present

STEP 2 — Domain truth verification
  - Cross-reference values against authoritative source
  - Pillar names → waf_*_corpus.py
  - Question IDs → waf_knowledge_base.yaml
  - Evidence types → evidence_patterns.yaml
  - Flag any value not found in source of truth

STEP 3 — Coverage completeness
  - Compare entry count with expected coverage
  - Identify gaps (expected entries missing)
  - Identify orphans (entries with no consumer)

STEP 4 — Semantic correctness
  - Verify mappings make domain sense
  - Evidence type → question mapping: is the affinity logical?
  - BP → pillar assignment: correct pillar?

STEP 5 — Consumer impact
  - Identify all consumers of this artifact
  - Verify consumers handle new/changed entries
  - Run consumer tests
```

### 6.4 Prompt Artifact Evaluation Protocol

```
INPUT: Changed/new files in prompts/

STEP 1 — Template completeness
  - All declared placeholders have corresponding data sources
  - No orphan placeholders (referenced but never filled)
  - Output format section matches target schema

STEP 2 — Governance compliance
  - SHA-256 hash computed and recorded
  - Version field present and incremented
  - Change documented in prompt changelog

STEP 3 — Injection resistance
  - Scan for patterns that could enable prompt injection
  - Verify constraints section present ("do not fabricate", etc.)
  - Check for proper escaping of user-provided content in template

STEP 4 — Output contract
  - Verify prompt's expected output format matches consuming schema
  - If prompt produces JSON: validate example output against schema
```


---

## 7. Adversarial Mode — Red Team Protocol

### 7.1 Philosophy

The adversarial phase does NOT test "does it work?" — that's Phase 1 (structural). The adversarial phase tests "can it be broken?" and "what happens when it's fed unexpected input?"

The Red Team operates under the assumption that:
- Upstream producers may emit malformed data (bugs, version skew)
- LLM outputs are inherently unpredictable (hallucination, format drift)
- Schema consumers may have stricter or looser validation than expected
- Attackers may craft inputs to exploit validation gaps

### 7.2 Adversarial Probe Categories

#### Category A: Type Coercion

Test that type boundaries are enforced. Attempt to pass values of wrong types that might be silently coerced.

```python
probes_type_coercion = [
    # String where integer expected
    {"total_gaps": "5"},
    {"priority": "high"},
    
    # Integer where string expected
    {"run_id": 12345},
    {"gap_type": 1},
    
    # Null where required
    {"run_id": None},
    {"base_run_id": None},
    
    # Array where object expected
    {"config": ["token_budget", 5000]},
    
    # Boolean where string expected
    {"model_id": True},
]
```

#### Category B: Boundary Values

Test minimum/maximum constraints and edge cases at boundaries.

```python
probes_boundary = [
    # Below minimum
    {"priority": 0},          # minimum: 1
    {"new_confidence": -0.1}, # minimum: 0
    {"total_gaps": -1},       # minimum: 0
    
    # Above maximum
    {"priority": 11},         # maximum: 10
    {"new_confidence": 1.01}, # maximum: 1
    
    # At boundary (should PASS)
    {"priority": 1},          # exactly minimum
    {"priority": 10},         # exactly maximum
    {"new_confidence": 0.0},  # exactly minimum
    {"new_confidence": 1.0},  # exactly maximum
    
    # Empty strings where minLength: 1
    {"run_id": ""},
    {"model_id": ""},
    
    # Extremely long strings (no maxLength defined)
    {"reason": "x" * 100000},
    
    # Zero-length arrays where minItems expected
    {"artifacts": []},        # minItems: 6
    
    # Unicode edge cases
    {"run_id": "\u0000"},     # null byte
    {"run_id": "​"},          # zero-width space
]
```

#### Category C: Pattern Bypass

Test regex pattern constraints with inputs designed to bypass them.

```python
probes_pattern_bypass = [
    # gap_id: ^gap-[0-9a-f]{16}$
    {"gap_id": "gap-ABCDEF1234567890"},  # uppercase hex (should fail)
    {"gap_id": "gap-1234567890abcde"},   # 15 chars (too short)
    {"gap_id": "gap-1234567890abcdef0"}, # 17 chars (too long)
    {"gap_id": "gap-1234567890abcdeg"},  # 'g' not in hex
    {"gap_id": "Gap-1234567890abcdef"},  # capital G
    {"gap_id": "gap_1234567890abcdef"},  # underscore instead of dash
    {"gap_id": " gap-1234567890abcdef"}, # leading space
    {"gap_id": "gap-1234567890abcdef "}, # trailing space
    {"gap_id": ""},                       # empty
    
    # evidence_id: ^ev-[0-9a-f]{16}$
    {"evidence_id": "ev-ZZZZZZZZZZZZZZZZ"},
    {"evidence_id": "evidence-1234567890abcdef"},
    {"evidence_id": "ev-1234"},
]
```

#### Category D: Conditional Logic Circumvention

Test `allOf/if/then` conditional requirements by providing states that should trigger requirements but omitting the required fields.

```python
probes_conditional = [
    # enrichment_results: status=succeeded requires enrichment + provenance
    {
        "status": "succeeded",
        # Missing: enrichment, provenance
    },
    
    # enrichment_results: status=failed requires error
    {
        "status": "failed",
        # Missing: error
    },
    
    # disambiguation: disposition=reclassified requires reclassified_type
    {
        "disposition": "reclassified",
        # Missing: reclassified_type
    },
    
    # run_manifest: repo_scope=sub_path requires scope_paths.project_root
    {
        "repo_scope": "sub_path",
        # Missing: scope_paths
    },
]
```

#### Category E: Additional Properties Injection

Test that `additionalProperties: false` actually rejects unknown fields.

```python
probes_injection = [
    # Inject fields that could confuse consumers
    {"__proto__": {"admin": True}},           # prototype pollution
    {"constructor": {"name": "exploit"}},     # constructor override
    {"internal_score": 99},                   # field that looks legitimate
    {"_debug": True},                         # debug flag injection
    {"enrichment_override": {"skip": True}},  # logic bypass attempt
]
```

#### Category F: Enum Exhaustion

Test that only declared enum values are accepted.

```python
probes_enum = [
    # gap_type: only 6 valid values
    {"gap_type": "unknown_type"},
    {"gap_type": ""},
    {"gap_type": "MISSING_NOTES"},  # wrong case
    {"gap_type": "missing-notes"},  # wrong separator
    
    # pillar: only 6 valid values
    {"pillar": "security_excellence"},  # invented
    {"pillar": "Security"},             # wrong case
    {"pillar": "all"},                  # wildcard attempt
    
    # disposition: only 3 valid values
    {"disposition": "unknown"},
    {"disposition": "CONFIRMED"},       # wrong case
    {"disposition": "partially_confirmed"},  # invented
    
    # status: only 4 valid values
    {"status": "pending"},
    {"status": "in_progress"},
    {"status": "SUCCESS"},             # wrong case
]
```

### 7.3 Red Team Scenarios (Code Artifacts)

For code changes (not just schemas), the Red Team generates behavioral scenarios:

| Scenario ID | Category | Description | Expected Behavior |
|-------------|----------|-------------|-------------------|
| RT-001 | LLM Output | Bedrock returns valid JSON but with fabricated evidence_refs | Enricher rejects (refs not in catalog) |
| RT-002 | LLM Output | Bedrock returns risk_level: UNANSWERED | Enricher rejects (violates contract) |
| RT-003 | Timeout | Bedrock timeout mid-stream (partial JSON) | Enricher returns None gracefully |
| RT-004 | Budget | Token budget exceeded mid-enrichment | Orchestrator stops, marks remaining as skipped_budget |
| RT-005 | Concurrency | Concurrent enrichment requests with shared state | No race conditions, no data corruption |
| RT-006 | Injection | Prompt injection via evidence content | Prompt template escapes user content |
| RT-007 | Schema Drift | enrichment_results.json with extra fields from newer version | Consumer handles gracefully (ignores or logs) |
| RT-008 | Rollback | Enrichment fails mid-run, rollback triggered | Base artifacts restored, no partial state |
| RT-009 | Poison | Malformed gap_manifest.json fed to orchestrator | Orchestrator rejects with clear error, no crash |
| RT-010 | Replay | Same gap_manifest processed twice | Idempotent — no duplicate enrichments |

### 7.4 Adversarial Test Generation Strategy

The agent generates adversarial tests using this algorithm:

```python
def generate_adversarial_suite(schema: dict, artifact_type: str) -> list[dict]:
    """
    Generate adversarial test cases from a JSON schema.
    
    Strategy:
    1. For each required field: generate instance with field missing
    2. For each typed field: generate instance with wrong type
    3. For each constrained field: generate boundary violations
    4. For each pattern field: generate pattern bypass attempts
    5. For each enum field: generate invalid enum values
    6. For each conditional (allOf/if/then): generate state without required consequence
    7. For additionalProperties:false objects: inject extra fields
    8. Combine multiple violations in single instance (compound attacks)
    """
    probes = []
    
    # Category A: Missing required fields (one per required field)
    for field in schema.get("required", []):
        probe = generate_valid_instance(schema)
        del probe[field]
        probes.append({"category": "missing_required", "field": field, "instance": probe})
    
    # Category B: Type violations
    for field, field_schema in schema.get("properties", {}).items():
        wrong_type_value = generate_wrong_type(field_schema["type"])
        probe = generate_valid_instance(schema)
        probe[field] = wrong_type_value
        probes.append({"category": "type_coercion", "field": field, "instance": probe})
    
    # Category C: Boundary violations
    for field, field_schema in schema.get("properties", {}).items():
        for boundary_probe in generate_boundary_violations(field_schema):
            probe = generate_valid_instance(schema)
            probe[field] = boundary_probe
            probes.append({"category": "boundary", "field": field, "instance": probe})
    
    # ... (pattern, enum, conditional, injection categories)
    
    return probes
```

### 7.5 Adversarial Scoring

The adversarial score is computed as:

```
adversarial_score = (probes_correctly_rejected / total_probes_expected_to_fail) * 10
```

Where:
- `probes_correctly_rejected`: adversarial inputs that were properly rejected by validation
- `total_probes_expected_to_fail`: total adversarial inputs generated (all should fail)

A score of 10 means 100% of adversarial inputs were correctly rejected.

---

## 8. Pipeline Impact Analysis

### 8.1 Edge-Aware Evaluation

The agent doesn't just evaluate files in isolation — it understands the pipeline edges:

```
Changed File → Identify Producer/Consumer Role → Find Affected Edges → Test Edge Contracts
```

| If Changed File Is... | Then Also Validate... |
|----------------------|----------------------|
| A schema (contract definition) | All producers conform to new schema. All consumers handle new fields. |
| A producer module | Output still conforms to schema. Downstream consumers unaffected. |
| A consumer module | Still handles all valid inputs from producer. |
| A knowledge artifact | All consumers of this artifact still function correctly. |
| A shared utility | All importers still work. No signature changes break callers. |

### 8.2 Regression Surface Mapping

For each changed file, the agent computes the "regression surface" — the set of tests that MUST pass:

```python
def compute_regression_surface(changed_files: list[str]) -> list[str]:
    """
    Given changed files, return the minimum test set that must pass.
    
    Rules:
    1. Direct tests: tests that import or reference the changed module
    2. Consumer tests: tests for modules that consume the changed module's output
    3. Contract tests: cross-layer invariant tests for affected edges
    4. Smoke tests: always included (golden path validation)
    """
    tests = set()
    
    for file in changed_files:
        # Direct tests
        tests.update(find_tests_for_module(file))
        
        # Consumer tests
        for consumer in find_consumers(file):
            tests.update(find_tests_for_module(consumer))
        
        # Contract tests for affected edges
        for edge in find_affected_edges(file):
            tests.update(find_contract_tests(edge))
    
    # Always include smoke
    tests.add("tests/e2e/test_golden_path_smoke.py")
    
    return sorted(tests)
```

---

## 9. Evaluation Report Format

The agent produces a structured evaluation report posted as a PR comment and stored as a workflow artifact.

### 9.1 PR Comment Format

```markdown
## 🔍 Branch Evaluation Report

**Branch**: `feature/GH-87-online-enrichment-task-1-define-json-sch`
**Evaluated**: 2026-05-07T14:30:00Z
**Verdict**: 🟢 PASS (8.4/10)

### Score Breakdown

| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Structural Validity | 10/10 | 20% | 2.00 |
| Convention Compliance | 9/10 | 15% | 1.35 |
| Backward Compatibility | 10/10 | 20% | 2.00 |
| Domain Alignment | 9/10 | 15% | 1.35 |
| Test Coverage | 7/10 | 15% | 1.05 |
| Adversarial Resilience | 6/10 | 10% | 0.60 |
| Documentation | 10/10 | 5% | 0.50 |
| **Aggregate** | | | **8.85** |

### Observations

- ⚠️ D6 (Adversarial): 3 probes identified gaps in boundary validation
  - `enrichment_metadata` accepts empty object `{}` (no required fields)
  - `gaps_by_type` keys not validated against gap_type enum
  - `reasoning` field has maxLength but `reason` field does not
  
- ℹ️ D5 (Tests): No adversarial/red_team marked tests. Consider adding.

### Files Evaluated

| File | Type | Status |
|------|------|--------|
| `src/contracts/schemas/enrichment/gap_manifest.schema.json` | Schema | ✅ Added |
| `src/contracts/schemas/enrichment/enrichment_results.schema.json` | Schema | ✅ Added |
| `src/contracts/schemas/enrichment/enrichment_manifest.schema.json` | Schema | ✅ Added |
| `src/contracts/schemas/enrichment/disambiguation_result.schema.json` | Schema | ✅ Added |
| `src/contracts/schemas/run_manifest.schema.json` | Schema | ✅ Modified |
| `src/contracts/schemas/publish/published_index.schema.json` | Schema | ✅ Modified |
| `tests/contracts/test_enrichment_schemas.py` | Test | ✅ Added |
| `src/contracts/schemas/enrichment/README.md` | Documentation | ✅ Added |

### Adversarial Probes Summary

| Category | Probes Generated | Correctly Rejected | Pass Rate |
|----------|-----------------|-------------------|-----------|
| Type Coercion | 12 | 12 | 100% |
| Boundary Values | 18 | 16 | 89% |
| Pattern Bypass | 10 | 10 | 100% |
| Conditional Logic | 6 | 6 | 100% |
| Additional Properties | 8 | 8 | 100% |
| Enum Exhaustion | 14 | 14 | 100% |
| **Total** | **68** | **66** | **97%** |
```

### 9.2 Machine-Readable Report (JSON Artifact)

```json
{
  "evaluation_id": "eval-2026-05-07T143000Z-abc123",
  "branch": "feature/GH-87-online-enrichment-task-1-define-json-sch",
  "base": "main",
  "evaluated_at": "2026-05-07T14:30:00Z",
  "verdict": "PASS",
  "aggregate_score": 8.85,
  "dimensions": {
    "structural_validity": {"score": 10, "weight": 0.20, "issues": []},
    "convention_compliance": {"score": 9, "weight": 0.15, "issues": ["minor: description style"]},
    "backward_compatibility": {"score": 10, "weight": 0.20, "issues": []},
    "domain_alignment": {"score": 9, "weight": 0.15, "issues": []},
    "test_coverage": {"score": 7, "weight": 0.15, "issues": ["no adversarial tests"]},
    "adversarial_resilience": {"score": 6, "weight": 0.10, "issues": ["3 boundary gaps"]},
    "documentation": {"score": 10, "weight": 0.05, "issues": []}
  },
  "veto_triggered": false,
  "adversarial_summary": {
    "total_probes": 68,
    "correctly_rejected": 66,
    "pass_rate": 0.97,
    "gaps": [
      {"category": "boundary", "field": "enrichment_metadata", "detail": "accepts empty object"}
    ]
  },
  "regression_surface": {
    "tests_required": 12,
    "tests_executed": 12,
    "tests_passed": 12
  },
  "files_evaluated": 8,
  "pipeline_edges_affected": ["E5", "E6"]
}
```

---

## 10. Implementation Components

### 10.1 Component Map

| Component | Type | Purpose |
|-----------|------|---------|
| `branch_evaluator.py` | Python module | Core evaluation engine |
| `artifact_classifier.py` | Python module | Classifies files by artifact type |
| `schema_evaluator.py` | Python module | Schema-specific evaluation logic |
| `code_evaluator.py` | Python module | Code-specific evaluation logic |
| `knowledge_evaluator.py` | Python module | Knowledge artifact evaluation |
| `adversarial_generator.py` | Python module | Generates adversarial probes from schemas |
| `scoring_engine.py` | Python module | Computes dimension scores and aggregate |
| `report_renderer.py` | Python module | Generates PR comment and JSON report |
| `pipeline_graph.py` | Python module | Maps files to pipeline edges and consumers |
| `evaluate-branch.yml` | GitHub Action | CI trigger and orchestration |
| `branch-eval-gate.kiro.hook` | Kiro Hook | Local evaluation trigger |
| `branch-evaluation-protocol.md` | Steering file | Agent instructions |

### 10.2 GitHub Action Workflow

```yaml
# .github/workflows/evaluate-branch.yml
name: Branch Evaluation Gate

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write
  checks: write

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Full history for diff

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install evaluation dependencies
        run: |
          pip install jsonschema pyyaml ruff mypy

      - name: Compute diff
        id: diff
        run: |
          git diff --name-only origin/main...HEAD > changed_files.txt
          echo "files=$(cat changed_files.txt | wc -l)" >> $GITHUB_OUTPUT

      - name: Run Branch Evaluation
        id: evaluate
        run: |
          python scripts/evaluate_branch.py \
            --base main \
            --head ${{ github.head_ref }} \
            --output evaluation_report.json \
            --pr-comment evaluation_comment.md

      - name: Post PR Comment
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const comment = fs.readFileSync('evaluation_comment.md', 'utf8');
            
            // Find existing evaluation comment
            const comments = await github.rest.issues.listComments({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
            });
            
            const existing = comments.data.find(c => 
              c.body.includes('## 🔍 Branch Evaluation Report')
            );
            
            if (existing) {
              await github.rest.issues.updateComment({
                owner: context.repo.owner,
                repo: context.repo.repo,
                comment_id: existing.id,
                body: comment,
              });
            } else {
              await github.rest.issues.createComment({
                owner: context.repo.owner,
                repo: context.repo.repo,
                issue_number: context.issue.number,
                body: comment,
              });
            }

      - name: Set Check Status
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const report = JSON.parse(fs.readFileSync('evaluation_report.json', 'utf8'));
            
            const conclusion = report.aggregate_score >= 7.0 ? 'success' : 'failure';
            
            await github.rest.checks.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              name: 'Branch Evaluation Gate',
              head_sha: context.sha,
              status: 'completed',
              conclusion: conclusion,
              output: {
                title: `Score: ${report.aggregate_score.toFixed(1)}/10 — ${report.verdict}`,
                summary: `Evaluated ${report.files_evaluated} files across ${Object.keys(report.dimensions).length} dimensions.`,
              },
            });

      - name: Upload Report Artifact
        uses: actions/upload-artifact@v4
        with:
          name: evaluation-report
          path: evaluation_report.json
```

### 10.3 Kiro Hook (Local Trigger)

```json
{
  "name": "Branch Evaluation Gate",
  "version": "1.0.0",
  "description": "Runs the Branch Evaluation Agent against the current branch. Produces a score and verdict.",
  "when": {
    "type": "userTriggered"
  },
  "then": {
    "type": "askAgent",
    "prompt": "Execute the Branch Evaluation Protocol against the current branch. Follow the instructions in .kiro/steering/branch-evaluation-protocol.md. Compute diff against main, classify artifacts, run all evaluation phases (structural, convention, compatibility, adversarial, domain, test coverage, documentation), compute scores, and present the evaluation report."
  }
}
```

### 10.4 Auto-Merge Configuration

For branches that score ≥ 8.0 AND have all CI checks green:

```yaml
# In evaluate-branch.yml, add after scoring:
      - name: Auto-Approve (Score ≥ 8.0)
        if: steps.evaluate.outputs.score >= 8.0
        uses: actions/github-script@v7
        with:
          script: |
            await github.rest.pulls.createReview({
              owner: context.repo.owner,
              repo: context.repo.repo,
              pull_number: context.issue.number,
              event: 'APPROVE',
              body: '🤖 Branch Evaluation Agent: PASS (score ≥ 8.0). Auto-approved.',
            });

      - name: Enable Auto-Merge (Score ≥ 8.0 + L1/L2 only)
        if: steps.evaluate.outputs.score >= 8.0 && steps.evaluate.outputs.level <= 2
        uses: actions/github-script@v7
        with:
          script: |
            await github.rest.pulls.merge({
              owner: context.repo.owner,
              repo: context.repo.repo,
              pull_number: context.issue.number,
              merge_method: 'squash',
            });
```

**Auto-merge eligibility**:
- Score ≥ 8.0
- Engineering Level L1 or L2 (trivial/simple changes)
- All CI checks green
- No veto rules triggered
- No `factory/level:L4` or `factory/level:L5` labels

For L3+ changes, the agent approves but does NOT auto-merge — human review is still required.

---

## 11. Agent Instruction (Steering File)

The following is the steering file that instructs the evaluation agent:


```markdown
---
inclusion: manual
---

# Branch Evaluation Protocol — Agent Instructions

> Activation: provide `#branch-eval` in chat or trigger via hook.
> Scope: Evaluate a feature branch for merge readiness.
> Output: Structured evaluation report with score and verdict.

## Your Role

You are the **Branch Evaluation Agent**. Your job is to evaluate a feature branch
against the project's quality standards and produce a deterministic score.

You are NOT a code reviewer giving opinions. You are a quality gate producing
measurable, reproducible assessments.

## Execution Protocol

### Step 0: Intake

1. Identify the feature branch (current branch or specified)
2. Compute diff against main: `git diff --name-only main...HEAD`
3. Load the parent issue (from branch name pattern or PR description)
4. Extract acceptance criteria from the issue

### Step 1: Classify

For each changed file, assign an artifact type:
- Schema: `*.schema.json`
- Code: `*.py` in `src/`, `wafr/`, `lambdas/`
- Knowledge: `*.yaml`, `*.json` in `config/mappings/`, `data/`
- Prompt: `*.md`, `*.txt` in `prompts/`
- Infrastructure: `*.tf`, `Dockerfile`, `*.yml` in `.github/workflows/`
- Documentation: `*.md` in `docs/`
- Test: `*.py` in `tests/`

### Step 2: Evaluate Each Dimension

For each dimension (D1-D7), apply the evaluation protocol specific to the
artifact types present in the diff. Use the scoring rubric to assign 0-10.

**Critical rules**:
- EXECUTE tests, don't just read them. Run `pytest` on affected test files.
- GENERATE adversarial inputs, don't just theorize about them.
- VALIDATE schemas with actual instances, don't just inspect the JSON.
- COMPARE with main branch for backward compatibility, don't assume.

### Step 3: Adversarial Phase

For each schema in the diff:
1. Generate ≥10 adversarial probes per category (A-F)
2. Validate each probe against the schema
3. Record which probes were correctly rejected vs incorrectly accepted
4. Compute adversarial pass rate

For each code module in the diff:
1. Identify error paths and edge cases
2. Generate test scenarios for each (RT-001 through RT-010 as applicable)
3. Verify graceful degradation behavior

### Step 4: Score & Report

1. Compute per-dimension scores (0-10)
2. Check veto rules (D1 < 3, D3 < 3, D4 < 3 → automatic FAIL)
3. Compute weighted aggregate
4. Apply decision threshold
5. Generate report in both markdown (PR comment) and JSON (artifact) formats

### Step 5: Verdict

Post the evaluation report. Set the verdict:
- ≥ 8.0 → 🟢 PASS
- 7.0-7.9 → 🟡 CONDITIONAL PASS
- 5.0-6.9 → 🟠 CONDITIONAL FAIL
- < 5.0 → 🔴 FAIL

## What You Must NOT Do

- Do not modify any files in the branch
- Do not create commits
- Do not merge or approve without meeting thresholds
- Do not skip the adversarial phase
- Do not give subjective opinions — only measurable assessments
- Do not evaluate style preferences — only convention violations
```

---

## 12. Integration with Existing FDE Protocol

### 12.1 Relationship to FDE Phases

| FDE Phase | Branch Evaluation Equivalent |
|-----------|------------------------------|
| Phase 1 (Reconnaissance) | Phase 0: Intake & Classification |
| Phase 3.a (Adversarial) | Phase 3: Adversarial / Red Team |
| Phase 3.b (Pipeline testing) | Phase 2: Regression Surface + Pipeline Impact |
| Phase 3.c (5W2H) | Phase 4: Domain Validation |
| DoD Gate | Phase 5: Scoring & Decision |

### 12.2 Relationship to Factory Confidence Scoring

The Branch Evaluation Agent's score complements the Factory's intake confidence score:

```
Factory Confidence (0-1.0) → How well-specified is the task?
Branch Evaluation (0-10)   → How well-implemented is the solution?
```

Together they form a quality funnel:
1. **Intake gate**: Is the task well-defined? (Factory confidence ≥ 0.65)
2. **Implementation gate**: Is the solution correct? (Branch evaluation ≥ 7.0)
3. **CI gate**: Does it pass automated checks? (All green)
4. **Human gate**: Does a human approve? (Required for L3+)

### 12.3 Relationship to Existing Test Markers

The adversarial phase generates tests that should be tagged with existing markers:

| Generated Test Type | pytest Marker |
|--------------------|---------------|
| Adversarial schema probes | `@pytest.mark.red_team` |
| Boundary value tests | `@pytest.mark.contract` |
| Pipeline regression tests | `@pytest.mark.smoke` |
| Cross-layer invariants | `@pytest.mark.contract` |

---

## 13. Configuration

### 13.1 Evaluation Config File

```yaml
# .github/factory/evaluation-config.yaml
evaluation:
  # Score thresholds
  thresholds:
    pass: 8.0
    conditional_pass: 7.0
    conditional_fail: 5.0
  
  # Dimension weights (must sum to 1.0)
  weights:
    structural_validity: 0.20
    convention_compliance: 0.15
    backward_compatibility: 0.20
    domain_alignment: 0.15
    test_coverage: 0.15
    adversarial_resilience: 0.10
    documentation: 0.05
  
  # Veto rules
  veto:
    structural_validity: 3    # Score below this → automatic FAIL
    backward_compatibility: 3
    domain_alignment: 3
  
  # Auto-merge eligibility
  auto_merge:
    enabled: true
    min_score: 8.0
    max_engineering_level: 2  # L1 and L2 only
    require_ci_green: true
  
  # Adversarial configuration
  adversarial:
    min_probes_per_category: 10
    categories:
      - type_coercion
      - boundary_values
      - pattern_bypass
      - conditional_logic
      - additional_properties
      - enum_exhaustion
    
    # For code artifacts
    red_team_scenarios:
      - llm_output_fabrication
      - timeout_partial_response
      - budget_exhaustion
      - concurrent_access
      - prompt_injection
      - schema_drift
      - rollback_integrity
      - poison_input
      - replay_attack
  
  # Pipeline edge map (project-specific)
  pipeline_edges:
    E1:
      producer: "src/evidence/facts_extractor.py"
      consumer: "src/evidence/evidence_catalog.py"
      contract: "src/contracts/schemas/evidence_catalog.schema.json"
    E2:
      producer: "src/evidence/evidence_catalog.py"
      consumer: "src/assessment/deterministic_reviewer.py"
      contract: "src/contracts/schemas/question_evaluation.schema.json"
    E3:
      producer: "src/assessment/deterministic_reviewer.py"
      consumer: "wafr/publish_tree.py"
      contract: "src/contracts/schemas/publish/findings.schema.json"
    E4:
      producer: "wafr/publish_tree.py"
      consumer: "wafr/publish_sanitizer.py"
    E5:
      producer: "wafr/publish_sanitizer.py"
      consumer: "published artifacts (JSON)"
      contract: "src/contracts/schemas/publish/published_index.schema.json"
    E6:
      producer: "published artifacts (JSON)"
      consumer: "portal JS renderers"
  
  # Artifact type classification rules
  artifact_types:
    schema:
      patterns: ["src/contracts/schemas/**/*.json", "**/*.schema.json"]
    code:
      patterns: ["src/**/*.py", "wafr/**/*.py", "lambdas/**/*.py"]
    knowledge:
      patterns: ["config/mappings/**", "data/**/*.json", "pillars/**"]
    prompt:
      patterns: ["prompts/**"]
    infrastructure:
      patterns: ["infra/**/*.tf", "**/Dockerfile", ".github/workflows/**"]
    documentation:
      patterns: ["docs/**/*.md", "**/README.md"]
    test:
      patterns: ["tests/**/*.py"]
```

### 13.2 Per-Branch Override

Teams can override thresholds for specific branch patterns:

```yaml
# In evaluation-config.yaml
overrides:
  - branch_pattern: "hotfix/*"
    thresholds:
      pass: 6.0          # Lower bar for hotfixes
    weights:
      test_coverage: 0.25  # Higher weight on tests for hotfixes
  
  - branch_pattern: "docs/*"
    thresholds:
      pass: 7.0
    weights:
      documentation: 0.30  # Higher weight on docs for doc branches
      adversarial_resilience: 0.00  # Not applicable
```

---

## 14. Rollout Strategy

### Phase A: Shadow Mode (Week 1-2)

- Agent runs on every PR but only posts comment
- Does NOT block merge
- Team reviews accuracy of scores
- Calibrate weights and thresholds based on feedback

### Phase B: Advisory Mode (Week 3-4)

- Agent posts comment AND sets GitHub check
- Check is "neutral" (informational, not blocking)
- Team uses scores to prioritize review effort
- Refine adversarial probe generation

### Phase C: Gating Mode (Week 5+)

- Check becomes "required" in branch protection rules
- Score < 7.0 blocks merge
- Auto-approve enabled for L1/L2 with score ≥ 8.0
- Human review still required for L3+

---

## 15. Metrics & Observability

### 15.1 Tracked Metrics

| Metric | Purpose |
|--------|---------|
| `evaluation.score.aggregate` | Distribution of scores across PRs |
| `evaluation.score.{dimension}` | Per-dimension score distribution |
| `evaluation.verdict.{pass/conditional/fail}` | Verdict distribution |
| `evaluation.adversarial.pass_rate` | How well code resists adversarial probes |
| `evaluation.time_to_evaluate` | Latency of evaluation pipeline |
| `evaluation.false_positive_rate` | PRs that scored FAIL but were manually approved |
| `evaluation.false_negative_rate` | PRs that scored PASS but had post-merge issues |
| `evaluation.auto_merge_rate` | % of PRs auto-merged vs human-reviewed |

### 15.2 Calibration Loop

Monthly review of:
1. False positive rate → if too high, lower thresholds or adjust weights
2. False negative rate → if too high, raise thresholds or add adversarial categories
3. Dimension correlation → which dimensions best predict post-merge issues?
4. Auto-merge safety → any auto-merged PRs that caused incidents?

---

## 16. Security Considerations

| Risk | Mitigation |
|------|-----------|
| Agent has write access to PR | Agent only posts comments and sets check status. No code modification. |
| Adversarial probes could be expensive | Budget limit on probe generation (max 100 per category) |
| Score manipulation via branch naming | Score is computed from content, not metadata |
| Auto-merge bypasses human review | Only for L1/L2. L3+ always requires human. |
| Evaluation report leaks internal details | Report contains file paths and scores, not source code content |

---

## 17. Open Questions for Engineering Review

1. **Threshold calibration**: Should initial thresholds be more lenient (6.0 pass) during shadow mode?
2. **LLM-assisted evaluation**: Should D4 (Domain Alignment) use an LLM to assess semantic correctness, or remain purely rule-based?
3. **Incremental scoring**: Should re-pushes to the same PR only re-evaluate changed files, or always evaluate the full diff?
4. **Cross-PR awareness**: Should the agent consider other open PRs that might conflict?
5. **Cost**: Adversarial probe generation for large PRs (50+ files) — should there be a file count cap?
6. **Hypothesis integration**: Should adversarial probes use the existing Hypothesis (property-based testing) infrastructure?

---

## 18. References

- FDE Protocol: `.kiro/steering/fde.md`
- Factory Issue Contract: `.kiro/steering/fde-code-factory-issues-pattern.md`
- Fixture Governance: `docs/testing/fixture-governance.md`
- Prompt Governance: `docs/prompt-governance.md`
- Architecture: `docs/architecture/tech-design-document.md`
- Existing Red Team marker: `@pytest.mark.red_team` (defined in `pyproject.toml`)
