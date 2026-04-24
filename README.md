# Forward Deployed AI Engineers (FDE) — A Design Pattern for Kiro

> Transform your AI coding assistant from a reactive code writer into a context-aware engineering partner.

[![Tests](https://img.shields.io/badge/tests-54%20passed-brightgreen)]()
[![Quality](https://img.shields.io/badge/FDE%20quality-100%25-blue)]()
[![Bare](https://img.shields.io/badge/bare%20quality-33%25-red)]()

## What is an FDE?

A Forward Deployed AI Engineer is an AI agent that has been **deployed into** a specific project's context — its pipeline architecture, its knowledge artifacts, its quality standards (régua), and its governance boundaries. It is not a general-purpose coding assistant.

An FDE has:
- **System awareness** — it knows the pipeline chain, module boundaries, and data flow
- **Quality standards** — it measures against the project's régua, not its own judgment
- **Structured interaction** — it follows the Context + Instruction pattern, not ad-hoc questions
- **Recipe discipline** — it executes a predefined engineering sequence, carrying context across steps

## The Problem

Standard AI-assisted development follows a reactive cycle that produces locally correct fixes which cascade into system-level failures. Our post-mortem documented 20 cascading fixes in a single session. The root cause: the agent optimizes for function correctness, not pipeline correctness.

## Empirical Results

Same task, same AI agent. Without FDE: **33%** quality score. With FDE: **100%** quality score.

```
FDE wins: 12 criteria  |  Bare wins: 0  |  Ties: 6
Improvement: +67 percentage points
```

See [docs/forward-deployed-ai-engineers.md](docs/forward-deployed-ai-engineers.md) for the full design document with research foundations.

## Quick Start

### 1. Copy the artifacts to your project

```bash
# Copy steering template
cp .kiro/steering/fde.md <your-project>/.kiro/steering/fde.md

# Copy hook templates
cp .kiro/hooks/*.kiro.hook <your-project>/.kiro/hooks/
```

### 2. Customize the steering file

Edit `.kiro/steering/fde.md` to describe YOUR project:
- Replace the pipeline chain with your data flow
- Replace the module boundaries with your edge contracts
- Replace the régua table with your quality reference artifacts

### 3. Activate in Kiro

```
# In Kiro chat, type:
#fde <your task description>

# Enable hooks in the Agent Hooks panel:
# - fde-dor-gate (preTaskExecution)
# - fde-adversarial-gate (preToolUse on write)
# - fde-dod-gate (postTaskExecution)
# - fde-pipeline-validation (postTaskExecution)
```

### 4. Choose your engineering level

| Level | What to Activate | When |
|---|---|---|
| L1 — Routine | Steering only (`#fde`). No hooks. | Typo fix, doc change |
| L2 — Targeted | Steering + adversarial gate | Single-module bug fix |
| L3 — Cross-module | Steering + all 4 hooks | Multi-module change |
| L4 — Architectural | All hooks + human gate | Architecture change |

## Repo Structure

```
forward-deployed-ai-pattern/
├── .kiro/
│   ├── steering/
│   │   └── fde.md                    # Steering template (customize for your project)
│   └── hooks/
│       ├── fde-dor-gate.kiro.hook    # Definition of Ready (preTaskExecution)
│       ├── fde-adversarial-gate.kiro.hook  # Adversarial Gate (preToolUse/write)
│       ├── fde-dod-gate.kiro.hook    # Definition of Done (postTaskExecution)
│       └── fde-pipeline-validation.kiro.hook  # Pipeline Validation (postTaskExecution)
├── docs/
│   └── forward-deployed-ai-engineers.md  # Full design document
├── tests/
│   ├── test_fde_e2e_protocol.py      # Structural E2E test (48 tests)
│   ├── test_fde_quality_threshold.py # Quality comparison test (6 tests)
│   └── fixtures/fde_quality/         # Bare vs FDE response fixtures
├── scripts/
│   └── lint_language.py              # Weasel words / violent / trauma linter
├── examples/
│   ├── web-app/                      # Example: FDE for a web application
│   └── data-pipeline/               # Example: FDE for a data pipeline
└── README.md
```

## The Four-Phase Protocol

```
Phase 1: RECONNAISSANCE ──────── Before any code
  Understand the system, map modules, identify artifact types

Phase 2: TASK INTAKE (Structured) ── The specification
  Reformulate raw task → Context + Instruction + Constraints

Phase 3: MULTI-TURN ENGINEERING ── The work (Recipe)
  3.   Implement (recipe-aware, context-carrying)
  3.a  Adversarial challenge (8 questions before every write)
  3.b  Pipeline testing (edges, not nodes)
  3.c  5W2H reasoning
  3.d  5 Whys for issues found

Phase 4: COMPLETION ──────────── Inform the user
  What was delivered, validated, NOT validated, residual risks
```

## Research Foundations

The pattern is grounded in four peer-reviewed studies:

1. **Esposito et al. (2025)** — 93% of GenAI architecture studies lack formal validation
2. **Vandeputte et al. (2025)** — Verification at all levels, not only unit tests
3. **Shonan Meeting 222 (2025)** — Greenfield doesn't generalize to brownfield
4. **DiCuffa et al. (2025)** — "Context and Instruction" is the most efficient prompt pattern (ANOVA p<10⁻³²)

## Running the Tests

```bash
# Structural E2E test — validates all artifacts are coherent
python3 -m pytest tests/test_fde_e2e_protocol.py -v

# Quality threshold test — compares bare vs FDE responses
python3 -m pytest tests/test_fde_quality_threshold.py -v -s

# Language lint — checks for weasel words, violent/trauma language
python3 scripts/lint_language.py docs/forward-deployed-ai-engineers.md
```

## License

MIT

## Contributing

PRs welcome. If you apply the FDE pattern to your project and have results to share, open an issue — we'd love to add your case study.
