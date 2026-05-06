# Architecture Selection: repo-onboarding-agent

## Recommended Architecture: Pipeline (Sequential Stages)

### Rationale
The Pipeline architecture achieves the lowest cross-cutting concerns (9%), lowest information flow density (0.11), and best evolvability cost (1.0 — adding a new scanner touches exactly one component). It matches the existing FDE pipeline pattern (sequential phases), reducing cognitive load for maintainers. The trade-off is no parallelism for large repos, but the 5-minute time budget with Magika throughput (~20K files/min) and the sampling strategy for oversized repos makes this acceptable.

### Components
| Component | Owned State | Responsibility |
|-----------|-------------|----------------|
| Trigger Handler | trigger_event, correlation_id, repo_url | Receives EventBridge/direct event, validates input, creates isolated workspace |
| Repo Cloner | git_credentials, workspace_path, commit_sha | Shallow clones repo with ADR-014 credential isolation |
| File Scanner | file_list, magika_classifications | Walks filesystem, classifies every file via Magika |
| AST Extractor | ast_signatures, import_graph, dependency_graph | Parses source with tree-sitter, builds directed dependency graph |
| Convention Detector | detected_conventions | Detects languages, package managers, test frameworks, linters, CI/CD, IaC |
| Pattern Inferrer | pipeline_chain, module_boundaries, tech_stack, level_patterns | Sends structured summary to Haiku, receives pipeline chain + boundaries + tech stack + level patterns |
| Catalog Writer | catalog_db | Persists all extracted data to SQLite (9 tables), handles incremental updates |
| Steering Generator | steering_draft, steering_diff | Renders project-specific FDE steering from catalog data |
| S3 Persister | s3_catalog_path | Uploads catalog.db + steering-draft.md to factory artifacts bucket |

### Information Flow
| From \ To | Trigger | Cloner | Scanner | AST | Convention | Inferrer | CatalogW | SteeringG | S3 |
|-----------|---------|--------|---------|-----|------------|----------|----------|-----------|-----|
| Trigger | | → | | | | | | | |
| Cloner | | | → | | | | | | |
| Scanner | | | | → | → | | | | |
| AST | | | | | | → | | | |
| Convention | | | | | | → | | | |
| Inferrer | | | | | | | → | | |
| CatalogW | | | | | | | | → | → |
| SteeringG | | | | | | | | | → |

### Requirement Allocation
| Requirement | Component(s) |
|-------------|--------------|
| REQ-1.1 | Trigger Handler, Repo Cloner |
| REQ-1.2 | Repo Cloner |
| REQ-1.3 | Repo Cloner |
| REQ-2.1 | File Scanner |
| REQ-2.2 | AST Extractor |
| REQ-2.3 | AST Extractor |
| REQ-2.4 | Convention Detector |
| REQ-2.5 | File Scanner (time budget enforcement) |
| REQ-3.1 | Pattern Inferrer |
| REQ-3.2 | Pattern Inferrer |
| REQ-3.3 | Pattern Inferrer |
| REQ-3.4 | Pattern Inferrer |
| REQ-3.5 | Pattern Inferrer |
| REQ-4.1 | Catalog Writer |
| REQ-4.2 | S3 Persister |
| REQ-4.3 | Catalog Writer |
| REQ-5.1 | Steering Generator |
| REQ-5.2 | S3 Persister |
| REQ-5.3 | Steering Generator |
| REQ-6.1 | (Consumed by FDE intake — reads from S3 catalog) |
| REQ-6.2 | (Consumed by FDE intake — reads level_patterns from catalog) |
| REQ-6.3 | (Consumed by ECS task definition — reads tech_stack from catalog) |
| REQ-7.1 | (Terraform — new ECS task definition) |
| REQ-7.2 | Trigger Handler |
| REQ-7.3 | Trigger Handler |

### Key Design-Induced Invariants
1. **Unidirectional data flow** — data flows strictly left-to-right through the pipeline. No component reads from a downstream component. This eliminates sync cycles by construction.
2. **Single writer per state** — each piece of state is owned by exactly one component. No concurrent write conflicts.
3. **Catalog as integration contract** — the SQLite schema is the contract between the onboarding agent and the FDE intake. Changes to the schema require versioning.
4. **Fail-fast propagation** — if any stage fails, the pipeline halts immediately. Partial catalogs are never persisted to S3 (atomic upload after all stages complete).

### Alternatives Considered
| Candidate | Strength | Weakness | Why Not Selected |
|-----------|----------|----------|-----------------|
| Event-Driven (Pub/Sub) | Parallel scanning for large repos | 2x flow density (0.19), 2x cross-cutting (18%), shared store coordination complexity | Parallelism not needed within 5-min budget for repos up to 50K files. Sampling handles larger repos. |
| Layered (Domain-Driven) | Pure domain layer, maximum testability, hexagonal alignment | Higher flow density (0.14), more components with layer boundaries adding indirection | Added indirection doesn't pay off — domain logic is straightforward transforms, not complex business rules. Pipeline stages are already independently testable. |

### Metrics Summary
| Metric | Pipeline (Selected) | Event-Driven | Layered |
|--------|----------|-------|-------|
| Cross-cutting reqs % | 9% | 18% | 14% |
| Cross-cutting invariants % | 12% | 25% | 12% |
| Flow density | 0.11 | 0.19 | 0.14 |
| God object score | 11% | 28% | 22% |
| Sync cycles | 0 | 0 | 0 |
| Max fan-in | 1 | 3 | 2 |
| Max fan-out | 2 | 3 | 3 |
| Evolvability cost | 1.0 | 1.5 | 1.3 |

### Well-Architected Alignment
| Pillar | How This Architecture Addresses It |
|--------|-----------------------------------|
| Operational Excellence (OPS) | Sequential pipeline is easy to observe — each stage logs start/end/duration. Failures are localized to one stage. |
| Security (SEC) | Credential isolation in Repo Cloner only. No other component touches secrets. Minimal blast radius. |
| Reliability (REL) | Fail-fast with atomic S3 upload. No partial state. Retry = re-run entire pipeline (idempotent). |
| Performance Efficiency (PERF) | Magika + tree-sitter are native-speed tools. LLM call is single-shot Haiku (< 2s). Total pipeline < 5 min. |
| Cost Optimization (COST) | Single ECS task (1 vCPU / 2GB). One Haiku call ($0.01 max). No always-on resources. |
| Sustainability (SUS) | Shallow clone minimizes network/disk. Incremental updates avoid redundant work. |
