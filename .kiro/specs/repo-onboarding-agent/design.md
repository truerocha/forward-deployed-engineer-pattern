# Design: Repo Onboarding Agent (Phase 0 — Codebase Reasoning Brain)

> Status: draft
> Date: 2026-05-06
> Source requirements: `.kiro/specs/repo-onboarding-agent/requirements.md`
> Architecture selection: `.kiro/specs/repo-onboarding-agent/architecture_analysis.md`
> Related ADRs: ADR-009 (AWS Cloud Infrastructure), ADR-014 (Secret Isolation)

---

## 1. Overview

The Repo Onboarding Agent is a Phase 0 pipeline that runs before the FDE intake for any project. It clones (or scans locally) a target repository, extracts structure using Magika + tree-sitter, infers patterns via Claude Haiku, persists a SQLite catalog to S3, and generates a project-specific FDE steering file for human approval.

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| File type detection | Magika (Google) | Content-based, not extension-based. Handles polyglot/generated files. No LLM needed. |
| AST extraction | tree-sitter | Language-agnostic, fast, battle-tested. Supports 6 target languages. |
| Pattern inference | Claude Haiku (Bedrock) | Cost cap $0.01/run. Structured input only (no raw code). 8K token limit. |
| Catalog format | SQLite | Lightweight, portable, queryable. Single-file artifact. No server needed. |
| Steering approval | Human gate | Generated steering written to staging path. Staff Engineer copies to workspace. |
| Credential handling | ADR-014 fetch-use-discard | Tokens fetched from Secrets Manager at clone time, never stored in context. |
| Architecture | Sequential pipeline | Lowest coupling (9% cross-cutting), matches existing FDE pattern. |
| Local mode | Workspace scan (no clone) | Enables experimentation without repo URL. Catalog stored locally. |

---

## 2. Architecture

### 2.1 Selected Architecture: Sequential Pipeline

Based on architecture analysis (scoring: 9% cross-cutting, 0.11 flow density, 11% god object, 1.0 evolvability), the sequential pipeline was selected over event-driven and layered alternatives.

**Trade-off**: No parallelism for large repos. Mitigated by the 5-minute budget + sampling strategy for repos >100K files.

### 2.2 Component Inventory

| Component | Owned State | Responsibility |
|-----------|-------------|----------------|
| Trigger Handler | trigger_event, correlation_id, repo_url, mode | Receives event, validates input, determines mode (cloud vs local), creates workspace |
| Repo Cloner | git_credentials, cloned_workspace_path, commit_sha | Clones repo with ADR-014 credential isolation. Skipped in local mode. |
| File Scanner | file_list, magika_classifications | Walks filesystem, classifies every file with Magika |
| AST Extractor | ast_signatures, import_graph, dependency_graph | Parses source with tree-sitter, builds directed dependency graph |
| Convention Detector | detected_conventions | Detects languages, package managers, test frameworks, linters, CI/CD, IaC |
| Pattern Inferrer | pipeline_chain, module_boundaries, tech_stack, level_patterns | Sends structured summary to Haiku, receives inferred patterns |
| Catalog Writer | catalog_db, scan_metadata | Persists all extracted data to SQLite. Records scan metadata (duration, counts, errors). |
| Steering Generator | steering_draft_md, steering_diff | Generates `.kiro/steering/fde.md` from catalog data |
| S3 Persister | s3_catalog_path | Uploads catalog + steering draft to S3. Skipped in local mode. |
| Observability Emitter | structured_logs, metrics, failure_report | Emits per-stage metrics, writes failure reports on error |

### 2.3 Information Flow

```
EventBridge / Direct / Kiro Hook
        │
        ▼
┌─────────────────┐
│ Trigger Handler  │──── mode=local? ────┐
└────────┬────────┘                      │
         │ mode=cloud                    │
         ▼                               │
┌─────────────────┐                      │
│  Repo Cloner    │                      │
│ (ADR-014 creds) │                      │
└────────┬────────┘                      │
         │                               │
         ▼                               ▼
┌─────────────────┐              ┌──────────────┐
│  File Scanner   │◄─────────────│ cwd = workspace│
│  (Magika)       │              └──────────────┘
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ AST Extractor   │
│ (tree-sitter)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│Convention Detect │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│Pattern Inferrer  │
│ (Haiku, ≤8K tok)│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Catalog Writer   │
│ (SQLite)         │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│Steering Generator│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  S3 Persister   │ (skipped in local mode)
└─────────────────┘
```

### 2.4 Requirement Allocation

| Requirement | Component(s) |
|-------------|--------------|
| REQ-1.1 Clone any Git repo | Repo Cloner |
| REQ-1.2 Shallow clone | Repo Cloner |
| REQ-1.3 Credential isolation | Repo Cloner, Trigger Handler |
| REQ-2.1 Magika file detection | File Scanner |
| REQ-2.2 tree-sitter AST | AST Extractor |
| REQ-2.3 Dependency graph | AST Extractor |
| REQ-2.4 Convention detection | Convention Detector |
| REQ-2.5 Scan performance | File Scanner, AST Extractor (time budget) |
| REQ-3.1 Pipeline chain inference | Pattern Inferrer |
| REQ-3.2 Module boundary detection | Pattern Inferrer |
| REQ-3.3 Tech stack classification | Pattern Inferrer |
| REQ-3.4 Level pattern detection | Pattern Inferrer |
| REQ-3.5 LLM cost control | Pattern Inferrer |
| REQ-4.1 SQLite catalog | Catalog Writer |
| REQ-4.2 S3 storage | S3 Persister |
| REQ-4.3 Incremental updates | Trigger Handler, Catalog Writer |
| REQ-5.1 Generate steering | Steering Generator |
| REQ-5.2 Human approval gate | S3 Persister (staging path) |
| REQ-5.3 Diff on re-scan | Steering Generator |
| REQ-6.1 Catalog lookup | (Consumer: FDE Intake) |
| REQ-6.2 Dynamic level | (Consumer: FDE Intake) |
| REQ-6.3 Global env vars | (Consumer: ECS Task Def) |
| REQ-7.1 ECS task definition | Infrastructure (Terraform) |
| REQ-7.2 Trigger mechanism | Trigger Handler |
| REQ-7.3 Isolation | Trigger Handler, Observability Emitter |


---

## 3. Detailed Component Design

### 3.1 Trigger Handler

**Responsibility**: Receives the onboarding event, validates input, determines execution mode, creates an isolated workspace, and initiates the pipeline.

**Inputs**:
- EventBridge event (`fde.onboarding.requested` with `repo_url` in detail)
- Direct ECS RunTask invocation (`REPO_URL` env var)
- Kiro hook trigger (`fde-repo-onboard` userTriggered)

**Mode Detection**:
```python
if not repo_url:
    mode = "local"
    workspace_path = os.getcwd()  # Kiro workspace
    catalog_path = "catalog.db"   # Local file
else:
    mode = "cloud"
    workspace_path = f"/tmp/onboard-{correlation_id}"
    catalog_path = f"catalogs/{owner}/{repo}/catalog.db"  # S3
```

**Outputs**:
- `correlation_id` (UUID v4)
- `mode` (cloud | local)
- `workspace_path`
- `catalog_path`
- `repo_url` (None in local mode)

**Incremental check** (REQ-4.3): If catalog exists at `catalog_path`, read `repos.commit_sha`. If current HEAD matches, emit `SKIP` event and exit early.

**Observability**: Emits `fde/onboarding/trigger` metric with dimensions: `mode`, `repo_owner`, `repo_name`.

### 3.2 Repo Cloner

**Responsibility**: Clones the target repository using ADR-014 credential isolation. Skipped entirely in local mode.

**Credential Flow** (ADR-014 fetch-use-discard):
```
1. Fetch PAT from Secrets Manager (fde-{env}/alm-tokens)
2. Set GIT_ASKPASS to a one-shot script that echoes the token
3. Execute: gh repo clone {repo_url} {workspace_path} -- --depth 1
4. Unset GIT_ASKPASS, discard token reference
```

**Security properties**:
- Token never enters environment variables visible to the agent
- Token never appears in shell history or process listing
- `GIT_ASKPASS` script is deleted after clone completes
- Falls back to env var `GITHUB_TOKEN` in local dev mode only

**Multi-platform support** (REQ-1.1):
- GitHub: `gh repo clone` with PAT via ASKPASS
- GitLab: `git clone https://oauth2:{token}@gitlab.com/{path}` via ASKPASS
- Bitbucket: `git clone https://x-token-auth:{token}@bitbucket.org/{path}` via ASKPASS

**Outputs**: `cloned_workspace_path`, `commit_sha` (from `git rev-parse HEAD`)

**Observability**: Emits `fde/onboarding/clone` metric with `duration_ms`, `repo_size_bytes`.

### 3.3 File Scanner (Magika)

**Responsibility**: Walks the filesystem and classifies every file by content type using Google's Magika library.

**Algorithm**:
```python
from magika import Magika

magika = Magika()

for path in walk_files(workspace_path):
    if should_skip(path):  # .git, node_modules, __pycache__, .venv
        continue
    result = magika.identify_path(path)
    yield FileRecord(
        path=relative_path,
        magika_type=result.output.ct_label,
        language=result.output.group,
        size_bytes=path.stat().st_size,
        is_generated=detect_generated(path, result)
    )
```

**Skip list** (performance, REQ-2.5):
- `.git/`, `node_modules/`, `__pycache__/`, `.venv/`, `vendor/`, `dist/`, `build/`
- Binary files > 1MB (detected by Magika as binary)
- Files matching `.gitignore` patterns

**Generated file detection**:
- Header comments containing "auto-generated", "DO NOT EDIT", "@generated"
- Magika type = "generated" or file in known generated paths (proto output, swagger codegen)

**Sampling** (repos > 100K files): Scan top-level directories + the 50 most-connected modules (by import count from a quick grep pass).

**Outputs**: List of `FileRecord` objects, `total_files_scanned`, `scan_duration_ms`

**Observability**: Emits `fde/onboarding/stage_duration` with `stage=file_scanner`, `files_processed`, `errors_count`.

### 3.4 AST Extractor (tree-sitter)

**Responsibility**: Parses source files using tree-sitter and extracts module signatures, import graphs, and public API surfaces.

**Supported languages** (REQ-7.1 grammar list):
- Python, JavaScript, TypeScript, Go, Java, Rust, HCL

**Extraction targets** (REQ-2.2):
```python
@dataclass
class ModuleSignature:
    name: str
    path: str
    type: str  # package | class | namespace | module
    functions: list[str]       # public function names
    classes: list[str]         # class names
    exports: list[str]         # exported symbols
    imports: list[ImportEdge]  # who this module imports

@dataclass
class ImportEdge:
    source_module: str
    target_module: str
    dependency_type: str  # import | call | inherit
```

**Dependency graph construction** (REQ-2.3):
1. Parse each source file with the appropriate tree-sitter grammar
2. Extract import/require/use statements → `ImportEdge` list
3. Resolve relative imports to absolute module paths
4. Supplement with package manifests (package.json `dependencies`, requirements.txt, go.mod, Cargo.toml, pom.xml)
5. Build directed graph: nodes = modules, edges = import relationships

**Outputs**: `dependency_graph` (networkx DiGraph), list of `ModuleSignature`

**Observability**: Emits `fde/onboarding/stage_duration` with `stage=ast_extractor`, `modules_found`, `edges_found`, `parse_errors`.

### 3.5 Convention Detector

**Responsibility**: Detects project conventions by examining configuration files and directory structure.

**Detection matrix** (REQ-2.4):

| Category | Detection Method | Examples |
|----------|-----------------|----------|
| Languages | Magika output + file extensions | Python, TypeScript, Go, Java, Rust |
| Package managers | Config file presence | package.json → npm/yarn, requirements.txt → pip, go.mod → go modules |
| Test frameworks | Config + directory patterns | pytest.ini/conftest.py → pytest, jest.config → jest, *_test.go → go test |
| Linters | Config file presence | ruff.toml → ruff, .eslintrc → eslint, .golangci.yml → golangci-lint |
| CI/CD | Workflow directory | .github/workflows → GitHub Actions, .gitlab-ci.yml → GitLab CI |
| Containerization | Dockerfile presence | Dockerfile, docker-compose.yml |
| IaC | Directory + file patterns | *.tf → Terraform, cdk.json → CDK, template.yaml → SAM |

**Outputs**: List of `Convention(category, name, version, config_path)`

**Observability**: Emits `fde/onboarding/stage_duration` with `stage=convention_detector`, `conventions_found`.

### 3.6 Pattern Inferrer (Claude Haiku)

**Responsibility**: Uses a lightweight LLM to infer high-level patterns that cannot be extracted deterministically: pipeline chain, module boundaries, and engineering level patterns.

**Cost control** (REQ-3.5):
- Model: Claude Haiku via Bedrock (`anthropic.claude-3-haiku-20240307-v1:0`)
- Input: structured summary only (never raw source code)
- Max input tokens: 8,192
- Max output tokens: 2,048
- Cost ceiling: $0.01 per onboarding run (Haiku input: $0.25/MTok, output: $1.25/MTok)

**Input construction**:
```json
{
  "dependency_graph_summary": {
    "total_modules": 42,
    "top_modules_by_fan_out": [...],
    "top_modules_by_fan_in": [...],
    "longest_dependency_chain": [...]
  },
  "file_type_distribution": {
    "python": 65,
    "typescript": 20,
    "terraform": 8,
    "yaml": 7
  },
  "conventions": ["pytest", "ruff", "github-actions", "terraform", "docker"],
  "entry_points": ["main.py", "agent_entrypoint.py", "lambda_handler.py"],
  "directory_structure_depth_2": [...]
}
```

**Prompt template** (REQ-3.1, 3.2, 3.3, 3.4):
```
You are analyzing a codebase structure. Given the dependency graph summary,
file type distribution, and conventions, produce:

1. pipeline_chain: The main data/execution flow as ordered steps.
   Format: [{"step_order": 1, "module_name": "...", "produces": "...", "consumes": "..."}]

2. module_boundaries: Producer/consumer edges where data transforms.
   Format: [{"edge_id": "E1", "producer": "...", "consumer": "...", "transform_description": "..."}]

3. tech_stack: Technology tags with categories.
   Format: [{"tag": "Python", "category": "language", "confidence": 0.95}]

4. level_patterns: Task patterns indicating engineering complexity.
   Format: [{"pattern": "bugfix", "level": "L2", "description": "..."}]

Respond in JSON only. No explanation.
```

**Outputs**: `pipeline_chain`, `module_boundaries`, `tech_stack_tags`, `level_patterns`

**Observability**: Emits `fde/onboarding/stage_duration` with `stage=pattern_inferrer`, `input_tokens`, `output_tokens`, `cost_usd`.

### 3.7 Catalog Writer (SQLite)

**Responsibility**: Persists all extracted data into a SQLite database following the schema defined in REQ-4.1.

**Schema** (REQ-4.1):
```sql
CREATE TABLE repos (
    repo_url TEXT PRIMARY KEY,
    clone_date TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    scan_duration_ms INTEGER,
    total_files INTEGER,
    total_modules INTEGER,
    error_count INTEGER DEFAULT 0
);

CREATE TABLE files (
    path TEXT PRIMARY KEY,
    magika_type TEXT NOT NULL,
    language TEXT,
    size_bytes INTEGER,
    is_generated BOOLEAN DEFAULT FALSE
);

CREATE TABLE modules (
    name TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    type TEXT NOT NULL,  -- package | class | namespace
    file_count INTEGER,
    line_count INTEGER
);

CREATE TABLE dependencies (
    source_module TEXT NOT NULL,
    target_module TEXT NOT NULL,
    dependency_type TEXT NOT NULL,  -- import | call | inherit
    PRIMARY KEY (source_module, target_module, dependency_type),
    FOREIGN KEY (source_module) REFERENCES modules(name),
    FOREIGN KEY (target_module) REFERENCES modules(name)
);

CREATE TABLE conventions (
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT,
    config_path TEXT,
    PRIMARY KEY (category, name)
);

CREATE TABLE pipeline_chain (
    step_order INTEGER PRIMARY KEY,
    module_name TEXT NOT NULL,
    produces TEXT,
    consumes TEXT
);

CREATE TABLE module_boundaries (
    edge_id TEXT PRIMARY KEY,
    producer TEXT NOT NULL,
    consumer TEXT NOT NULL,
    transform_description TEXT
);

CREATE TABLE tech_stack (
    tag TEXT PRIMARY KEY,
    category TEXT NOT NULL,  -- language | framework | cloud | infra
    confidence REAL DEFAULT 1.0
);

CREATE TABLE level_patterns (
    pattern TEXT PRIMARY KEY,
    level TEXT NOT NULL,  -- L2 | L3 | L4
    description TEXT
);
```

**Incremental update logic** (REQ-4.3):
```python
def should_full_scan(catalog_path, current_sha):
    if not exists(catalog_path):
        return True
    stored_sha = query("SELECT commit_sha FROM repos LIMIT 1")
    return stored_sha != current_sha

def delta_scan(workspace, catalog_path, previous_sha):
    changed_files = git_diff_names(previous_sha, "HEAD")
    # Only re-scan changed files
    # Only re-extract AST for changed modules
    # Re-run Pattern Inferrer if dependency graph changed
```

**Scan metadata** (observability): The `repos` table stores `scan_duration_ms`, `total_files`, `total_modules`, and `error_count` for historical tracking across runs.

**Outputs**: `catalog.db` file at `catalog_path`

**Observability**: Emits `fde/onboarding/stage_duration` with `stage=catalog_writer`, `tables_written`, `rows_inserted`.

### 3.8 Steering Generator

**Responsibility**: Generates a project-specific `.kiro/steering/fde.md` file from the catalog data.

**Template structure** (REQ-5.1):
```markdown
---
inclusion: manual
---

# Forward Deployed AI Engineer (FDE) — {repo_name}

> Auto-generated by Repo Onboarding Agent on {date}
> Catalog: {catalog_path}
> Commit: {commit_sha}

## Pipeline Chain

{rendered from pipeline_chain table}

## Module Boundaries (Where Bugs Live)

| Edge | Producer | Consumer | What Transforms |
|------|----------|----------|-----------------|
{rendered from module_boundaries table}

## Tech Stack

{rendered from tech_stack table as tags}

## Engineering Level Patterns

| Pattern | Level | Description |
|---------|-------|-------------|
{rendered from level_patterns table}

## Quality Reference Artifacts

{detected from conventions — test configs, lint configs, CI/CD}
```

**Diff on re-scan** (REQ-5.3):
```python
def generate_steering_diff(current_steering, new_steering):
    """Produces a unified diff highlighting what changed."""
    import difflib
    return '\n'.join(difflib.unified_diff(
        current_steering.splitlines(),
        new_steering.splitlines(),
        fromfile='current-steering.md',
        tofile='proposed-steering.md',
        lineterm=''
    ))
```

**Outputs**: `steering_draft_md` (full markdown), `steering_diff` (unified diff, empty on first run)

### 3.9 S3 Persister

**Responsibility**: Uploads the catalog and steering draft to S3. Skipped in local mode.

**S3 paths** (REQ-4.2):
- Catalog: `s3://{bucket}/catalogs/{owner}/{repo}/catalog.db`
- Steering draft: `s3://{bucket}/catalogs/{owner}/{repo}/steering-draft.md`
- Steering diff: `s3://{bucket}/catalogs/{owner}/{repo}/steering-diff.md` (re-scan only)
- Failure report: `s3://{bucket}/catalogs/{owner}/{repo}/failure-report.json` (on error)

**Local mode**: Catalog written to `./catalog.db` in workspace root. Steering draft written to `./.kiro/steering/fde-draft.md`.

**Outputs**: S3 URIs for uploaded artifacts

### 3.10 Observability Emitter

**Responsibility**: Cross-cutting component that provides structured logging, CloudWatch metrics, and failure reporting for all pipeline stages.

**Structured logging** (per stage):
```json
{
  "timestamp": "2026-05-06T14:30:00Z",
  "correlation_id": "uuid-v4",
  "stage_name": "file_scanner",
  "duration_ms": 12340,
  "files_processed": 4521,
  "errors_count": 3,
  "level": "INFO"
}
```

**CloudWatch metrics**:
- Namespace: `fde/onboarding`
- Metrics:
  - `stage_duration` (dimensions: stage_name, mode, repo_owner)
  - `total_onboarding_duration` (dimensions: mode, repo_owner)
  - `llm_cost_usd` (dimensions: model, repo_owner)
  - `scan_file_count` (dimensions: mode)
  - `error_count` (dimensions: stage_name, error_type)

**Failure reporting**:
```json
{
  "correlation_id": "uuid-v4",
  "repo_url": "https://github.com/org/repo",
  "failed_stage": "ast_extractor",
  "error_type": "ParseError",
  "error_message": "Unsupported language grammar: Kotlin",
  "partial_results": {
    "files_scanned": 4521,
    "modules_extracted": 38,
    "conventions_detected": 12
  },
  "timestamp": "2026-05-06T14:32:15Z",
  "scan_duration_ms": 135000
}
```

**Integration with existing infrastructure** (OPS 6+8):
- ECS task failures caught by existing dead-letter queue + CloudWatch alarm
- New alarm: `fde-onboarding-stage-p99-latency` triggers when any stage exceeds 2 minutes
- Dashboard: `fde-onboarding-health` shows per-stage latency percentiles


---

## 4. Execution Modes

### 4.1 Cloud Mode (REPO_URL provided)

Standard production flow. Triggered by EventBridge or direct ECS RunTask.

```
EventBridge event (fde.onboarding.requested)
  → Trigger Handler (validates repo_url, generates correlation_id)
    → Repo Cloner (ADR-014 credential isolation, shallow clone)
      → File Scanner → AST Extractor → Convention Detector
        → Pattern Inferrer (Haiku, ≤$0.01)
          → Catalog Writer (SQLite)
            → Steering Generator
              → S3 Persister (catalog + steering-draft + diff)
```

**Artifacts produced**:
- `s3://fde-{env}-artifacts-{account}/catalogs/{owner}/{repo}/catalog.db`
- `s3://fde-{env}-artifacts-{account}/catalogs/{owner}/{repo}/steering-draft.md`
- `s3://fde-{env}-artifacts-{account}/catalogs/{owner}/{repo}/steering-diff.md` (re-scan)

**Human approval gate** (REQ-5.2): The Staff Engineer reviews `steering-draft.md` in S3 and copies it to the target workspace's `.kiro/steering/fde.md` to activate. No auto-apply.

### 4.2 Local Mode (No REPO_URL — Experimentation)

Enables onboarding for the currently opened Kiro workspace without cloning. This is the "experiment" project mode from `code-factory-setup.sh`.

**Trigger**: Kiro hook `fde-repo-onboard` (userTriggered) with no `REPO_URL` env var, or direct invocation with `MODE=local`.

**Differences from cloud mode**:

| Aspect | Cloud Mode | Local Mode |
|--------|-----------|------------|
| Source | Cloned repo in /tmp | Current working directory |
| Catalog storage | S3 bucket | `./catalog.db` in workspace root |
| Steering output | S3 staging path | `./.kiro/steering/fde-draft.md` |
| Credentials | Secrets Manager PAT | Not needed (no clone) |
| ECS task | Separate Fargate task | Runs in Kiro agent process |
| Observability | CloudWatch metrics | Structured stdout logs |

**Flow**:
```
Kiro hook trigger (fde-repo-onboard, no REPO_URL)
  → Trigger Handler (mode=local, workspace_path=cwd)
    → [Repo Cloner SKIPPED]
      → File Scanner (scans cwd)
        → AST Extractor → Convention Detector
          → Pattern Inferrer (Haiku via Bedrock)
            → Catalog Writer (./catalog.db)
              → Steering Generator (./.kiro/steering/fde-draft.md)
                → [S3 Persister SKIPPED]
```

**Local approval gate**: Staff Engineer reviews `.kiro/steering/fde-draft.md` and renames to `.kiro/steering/fde.md` to activate.

### 4.3 Incremental Re-scan

When triggered for an already-onboarded repo (catalog exists):

1. Trigger Handler reads `repos.commit_sha` from existing catalog
2. Compares with current HEAD (`git rev-parse HEAD`)
3. If unchanged → emit SKIP event, exit (no cost incurred)
4. If changed → compute delta:
   - `git diff --name-only {stored_sha} HEAD` → changed file list
   - File Scanner runs only on changed files
   - AST Extractor re-parses only changed modules
   - If dependency graph edges changed → re-run Pattern Inferrer
   - If no structural changes → skip Pattern Inferrer (save $0.01)
5. Catalog Writer updates only modified rows (UPSERT)
6. Steering Generator produces diff against current steering

---

## 5. Data Contracts

### 5.1 Trigger Event Schema

```json
{
  "source": "fde.onboarding",
  "detail-type": "fde.onboarding.requested",
  "detail": {
    "repo_url": "https://github.com/org/repo",
    "clone_depth": 1,
    "force_full_scan": false,
    "correlation_id": "optional-override-uuid"
  }
}
```

### 5.2 Catalog Query Interface (for FDE Intake — REQ-6)

The FDE intake pipeline (Phase 2) queries the catalog via SQLite:

```python
def get_tech_stack(catalog_path: str) -> list[str]:
    """REQ-6.1: Returns tech_stack tags for data contract population."""
    conn = sqlite3.connect(catalog_path)
    return [row[0] for row in conn.execute("SELECT tag FROM tech_stack")]

def get_suggested_level(catalog_path: str, task_labels: list[str], task_description: str) -> str:
    """REQ-6.2: Returns suggested engineering level based on pattern matching."""
    conn = sqlite3.connect(catalog_path)
    patterns = conn.execute("SELECT pattern, level FROM level_patterns").fetchall()
    for pattern, level in patterns:
        if pattern.lower() in task_description.lower() or pattern in task_labels:
            return level
    return "L3"  # default

def get_module_context(catalog_path: str, file_path: str) -> dict:
    """REQ-6.1: Returns module context for constraint extractor."""
    conn = sqlite3.connect(catalog_path)
    module = conn.execute(
        "SELECT name, type, file_count FROM modules WHERE path LIKE ?",
        (f"%{file_path}%",)
    ).fetchone()
    deps = conn.execute(
        "SELECT target_module, dependency_type FROM dependencies WHERE source_module = ?",
        (module[0],) if module else ("",)
    ).fetchall()
    return {"module": module, "dependencies": deps}
```

### 5.3 Environment Variables (REQ-6.3)

In cloud mode (ECS), tech stack tags are set as environment variables:

```
ONBOARD_TECH_STACK=Python,AWS,Bedrock,Terraform,Docker
ONBOARD_CATALOG_PATH=s3://bucket/catalogs/owner/repo/catalog.db
ONBOARD_REPO_LEVEL=L3
```

In local mode, the intake reads directly from `./catalog.db`.

---

## 6. Infrastructure Design

### 6.1 ECS Task Definition (REQ-7.1)

Separate from the FDE pipeline agent task definition:

```hcl
resource "aws_ecs_task_definition" "onboarding_agent" {
  family                   = "fde-${var.environment}-onboarding-agent"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024"   # 1 vCPU
  memory                   = "2048"   # 2 GB
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.onboarding_task.arn

  container_definitions = jsonencode([{
    name  = "onboarding-agent"
    image = "${aws_ecr_repository.onboarding_agent.repository_url}:latest"
    environment = [
      { name = "ENVIRONMENT", value = var.environment },
      { name = "ARTIFACTS_BUCKET", value = aws_s3_bucket.artifacts.id },
      { name = "AWS_REGION", value = var.aws_region }
    ]
    # NOTE: No ALM tokens in environment (ADR-014)
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/fde-${var.environment}-onboarding"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "onboarding"
      }
    }
  }])
}
```

**Container image contents** (REQ-7.1):
- Python 3.12 slim base
- `gh` CLI (GitHub CLI for cloning)
- `magika` Python package
- `tree-sitter` + `tree-sitter-languages` (Python, JS, TS, Go, Java, Rust, HCL grammars)
- `sqlite3` (built into Python stdlib)
- `boto3` (Bedrock + S3 + Secrets Manager)
- `networkx` (dependency graph construction)

### 6.2 IAM Role (Least Privilege)

```hcl
resource "aws_iam_role" "onboarding_task" {
  name = "fde-${var.environment}-onboarding-task-role"

  inline_policy {
    name = "onboarding-permissions"
    policy = jsonencode({
      Version = "2012-10-17"
      Statement = [
        {
          Sid    = "S3CatalogAccess"
          Effect = "Allow"
          Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
          Resource = [
            "${aws_s3_bucket.artifacts.arn}/catalogs/*",
            aws_s3_bucket.artifacts.arn
          ]
        },
        {
          Sid    = "SecretsManagerRead"
          Effect = "Allow"
          Action = ["secretsmanager:GetSecretValue"]
          Resource = [
            "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:fde-${var.environment}/alm-tokens*"
          ]
        },
        {
          Sid    = "BedrockInvoke"
          Effect = "Allow"
          Action = ["bedrock:InvokeModel"]
          Resource = [
            "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0"
          ]
        },
        {
          Sid    = "CloudWatchMetrics"
          Effect = "Allow"
          Action = ["cloudwatch:PutMetricData"]
          Resource = ["*"]
          Condition = {
            StringEquals = { "cloudwatch:namespace" = "fde/onboarding" }
          }
        }
      ]
    })
  }
}
```

### 6.3 EventBridge Rule (REQ-7.2)

```hcl
resource "aws_cloudwatch_event_rule" "onboarding_trigger" {
  name        = "fde-${var.environment}-onboarding-trigger"
  description = "Triggers onboarding agent on fde.onboarding.requested events"
  event_bus_name = aws_cloudwatch_event_bus.factory_bus.name

  event_pattern = jsonencode({
    source      = ["fde.onboarding"]
    detail-type = ["fde.onboarding.requested"]
  })
}

resource "aws_cloudwatch_event_target" "onboarding_ecs" {
  rule           = aws_cloudwatch_event_rule.onboarding_trigger.name
  event_bus_name = aws_cloudwatch_event_bus.factory_bus.name
  arn            = aws_ecs_cluster.factory.arn
  role_arn       = aws_iam_role.eventbridge_ecs.arn

  ecs_target {
    task_definition_arn = aws_ecs_task_definition.onboarding_agent.arn
    task_count          = 1
    launch_type         = "FARGATE"

    network_configuration {
      subnets          = aws_subnet.private[*].id
      security_groups  = [aws_security_group.ecs_tasks.id]
      assign_public_ip = false
    }
  }

  input_transformer {
    input_paths = {
      repo_url       = "$.detail.repo_url"
      correlation_id = "$.detail.correlation_id"
      clone_depth    = "$.detail.clone_depth"
    }
    input_template = <<EOF
{
  "containerOverrides": [{
    "name": "onboarding-agent",
    "environment": [
      {"name": "REPO_URL", "value": <repo_url>},
      {"name": "CORRELATION_ID", "value": <correlation_id>},
      {"name": "CLONE_DEPTH", "value": <clone_depth>}
    ]
  }]
}
EOF
  }
}
```

### 6.4 Isolation (REQ-7.3)

Each onboarding run is fully isolated:
- **Container isolation**: Own ECS Fargate task (no shared filesystem)
- **Workspace isolation**: Clone to `/tmp/onboard-{correlation_id}/` (unique per run)
- **Correlation**: UUID v4 `correlation_id` propagated through all logs and metrics
- **No cross-repo interference**: Each task reads/writes only its own S3 prefix (`catalogs/{owner}/{repo}/`)
- **Cleanup**: Workspace directory deleted at task exit (ECS container is ephemeral)

---

## 7. Security Design (Well-Architected SEC Pillar)

### 7.1 Credential Isolation (ADR-014)

| Principle | Implementation |
|-----------|---------------|
| SEC 3: No embedded credentials | Tokens fetched from Secrets Manager at clone time only |
| SEC 6: Least privilege | Onboarding role has only S3, Secrets, Bedrock, CloudWatch access |
| SEC 8: Defense in depth | Token never in env vars, never in agent context, never logged |

**Fetch-use-discard flow**:
```python
def clone_with_isolation(repo_url: str, workspace: str, env: str):
    # 1. FETCH
    client = boto3.client('secretsmanager')
    secret = client.get_secret_value(SecretId=f'fde-{env}/alm-tokens')
    token = json.loads(secret['SecretString'])['github_pat']

    # 2. USE (via GIT_ASKPASS one-shot script)
    askpass_script = f"/tmp/askpass-{uuid4()}.sh"
    with open(askpass_script, 'w') as f:
        f.write(f"#!/bin/sh\necho {token}\n")
    os.chmod(askpass_script, 0o700)

    env_vars = {**os.environ, 'GIT_ASKPASS': askpass_script}
    subprocess.run(['git', 'clone', '--depth', '1', repo_url, workspace], env=env_vars)

    # 3. DISCARD
    os.unlink(askpass_script)
    del token, secret
```

### 7.2 Input Validation

- `repo_url` validated against allowlist of supported hosts (github.com, gitlab.com, bitbucket.org, or configured enterprise hosts)
- `clone_depth` must be positive integer, max 100
- `correlation_id` must be valid UUID v4 format
- No user-supplied strings passed to shell without escaping

### 7.3 LLM Security

- Pattern Inferrer receives only structured summaries, never raw source code
- No user-controlled content in the LLM prompt (dependency graph is machine-generated)
- LLM output parsed as JSON with strict schema validation — malformed output triggers retry (max 2)

---

## 8. Observability Design (Well-Architected OPS Pillar)

### 8.1 Structured Logging

Every pipeline stage emits structured JSON logs:

```json
{
  "timestamp": "ISO-8601",
  "correlation_id": "uuid-v4",
  "stage_name": "file_scanner | ast_extractor | convention_detector | pattern_inferrer | catalog_writer | steering_generator",
  "event": "stage_start | stage_complete | stage_error",
  "duration_ms": 12340,
  "files_processed": 4521,
  "errors_count": 3,
  "mode": "cloud | local",
  "repo_owner": "org",
  "repo_name": "repo"
}
```

### 8.2 Failure Reporting

On any unrecoverable error, the Observability Emitter writes a `OnboardingFailureReport` to S3:

**Path**: `catalogs/{owner}/{repo}/failure-report.json`

```json
{
  "correlation_id": "uuid-v4",
  "repo_url": "https://github.com/org/repo",
  "mode": "cloud",
  "failed_stage": "ast_extractor",
  "error_type": "ParseError",
  "error_message": "tree-sitter grammar not available for Kotlin",
  "partial_results": {
    "files_scanned": 4521,
    "magika_classifications": 4521,
    "modules_extracted": 38,
    "conventions_detected": 12,
    "pipeline_chain_inferred": false
  },
  "stages_completed": ["trigger_handler", "repo_cloner", "file_scanner"],
  "stages_remaining": ["convention_detector", "pattern_inferrer", "catalog_writer", "steering_generator"],
  "timestamp": "2026-05-06T14:32:15Z",
  "total_duration_ms": 135000
}
```

**Partial results preservation**: If the pipeline fails mid-way, completed stages' outputs are still written to the catalog. The `repos.error_count` field is incremented. The next run can resume from partial state.

### 8.3 CloudWatch Integration

| Metric | Namespace | Dimensions | Alarm |
|--------|-----------|------------|-------|
| `stage_duration` | fde/onboarding | stage_name, mode | P99 > 120s |
| `total_duration` | fde/onboarding | mode, repo_owner | > 300s (5 min budget) |
| `llm_cost` | fde/onboarding | model | > $0.01 per run |
| `error_count` | fde/onboarding | stage_name, error_type | > 0 |
| `scan_file_count` | fde/onboarding | mode | > 100,000 (sampling triggered) |

**Existing infrastructure reuse**:
- Dead-letter queue catches ECS task failures (already configured in ADR-009)
- CloudWatch alarm `fde-{env}-task-failure` fires on ECS task exit code != 0
- New dashboard: `fde-onboarding-health` with per-stage latency percentiles

### 8.4 Scan Metadata in Catalog

The `repos` table serves as a historical record:

```sql
-- After each successful scan:
INSERT OR REPLACE INTO repos VALUES (
    'https://github.com/org/repo',  -- repo_url
    '2026-05-06T14:30:00Z',        -- clone_date
    'abc123def456',                  -- commit_sha
    245000,                          -- scan_duration_ms
    4521,                            -- total_files
    42,                              -- total_modules
    3                                -- error_count (non-fatal parse errors)
);
```

This enables:
- Tracking scan performance over time
- Detecting repos that consistently fail or timeout
- Comparing scan duration across repo sizes

---

## 9. Well-Architected Alignment

| Pillar | Requirement | Design Decision |
|--------|-------------|-----------------|
| **Security** | REQ-1.3 Credential isolation | ADR-014 fetch-use-discard, no env var tokens |
| **Security** | Input validation | Repo URL allowlist, UUID validation, no shell injection |
| **Reliability** | REQ-2.5 Performance budget | 5-min timeout, sampling for large repos, incremental scan |
| **Reliability** | Failure handling | Partial results preserved, failure report to S3, dead-letter queue |
| **Performance** | REQ-3.5 Cost control | Haiku only, 8K token limit, structured input, $0.01 cap |
| **Performance** | REQ-2.5 Scan speed | Magika (no LLM for structure), tree-sitter (native speed), skip lists |
| **Cost** | LLM usage | Haiku ($0.25/MTok in) vs Sonnet ($3/MTok in) = 12x cheaper |
| **Cost** | Incremental scan | Skip unchanged repos, delta scan for changed files |
| **Ops Excellence** | Observability | Per-stage metrics, structured logs, failure reports, CloudWatch dashboards |
| **Ops Excellence** | Automation | EventBridge trigger, no manual intervention for scan |
| **Sustainability** | Resource efficiency | 1 vCPU / 2GB task, ephemeral (no idle resources), skip unchanged repos |

---

## 10. Acceptance Criteria Traceability

| AC# | Acceptance Criterion | Design Component | Verification Method |
|-----|---------------------|------------------|---------------------|
| 1 | Clone + scan + catalog in S3 within 5 min | All stages, REQ-2.5 time budget | Integration test with known repo, assert duration < 300s |
| 2 | Accurate file types (Magika ground truth) | File Scanner | Unit test: known files → expected Magika types |
| 3 | Correct import relationships | AST Extractor | Contract test: known repo → expected dependency edges |
| 4 | Valid pipeline chain for cognitive-wafr | Pattern Inferrer | Golden test: this repo → matches known chain in global steering |
| 5 | Steering contains all required sections | Steering Generator | Schema test: parse output, assert sections present |
| 6 | Incremental re-scan detects changes | Trigger Handler + Catalog Writer | Integration test: modify file → re-scan → only modified rows updated |
| 7 | Intake reads tech_stack and level_patterns | Catalog Query Interface (§5.2) | Integration test: query catalog → returns expected values |
| 8 | Dynamic level assignment from patterns | `get_suggested_level()` | Unit test: task labels → expected level |
| 9 | LLM cost under $0.01 | Pattern Inferrer cost tracking | Assert `llm_cost` metric < 0.01 per run |
| 10 | No credentials in agent context (ADR-014) | Repo Cloner | Security test: inspect env vars during clone → no tokens visible |

---

## 11. File Inventory

### New Files

| File | Purpose |
|------|---------|
| `infra/docker/agents/onboarding/__init__.py` | Package init |
| `infra/docker/agents/onboarding/trigger_handler.py` | Event reception, mode detection, workspace setup |
| `infra/docker/agents/onboarding/repo_cloner.py` | Git clone with ADR-014 credential isolation |
| `infra/docker/agents/onboarding/file_scanner.py` | Magika-based file classification |
| `infra/docker/agents/onboarding/ast_extractor.py` | tree-sitter AST parsing, dependency graph |
| `infra/docker/agents/onboarding/convention_detector.py` | Project convention detection |
| `infra/docker/agents/onboarding/pattern_inferrer.py` | Haiku LLM inference for patterns |
| `infra/docker/agents/onboarding/catalog_writer.py` | SQLite persistence |
| `infra/docker/agents/onboarding/steering_generator.py` | FDE steering file generation |
| `infra/docker/agents/onboarding/s3_persister.py` | S3 upload (cloud mode) |
| `infra/docker/agents/onboarding/observability.py` | Structured logging, metrics, failure reports |
| `infra/docker/agents/onboarding/pipeline.py` | Orchestrates all stages sequentially |
| `infra/docker/Dockerfile.onboarding-agent` | Container image for onboarding agent |
| `infra/terraform/onboarding.tf` | ECS task def, IAM role, EventBridge rule |
| `.kiro/hooks/fde-repo-onboard.kiro.hook` | Kiro hook for local/manual trigger |
| `tests/test_onboarding_pipeline.py` | Integration tests |
| `tests/test_onboarding_components.py` | Unit tests per component |

### Modified Files

| File | Change |
|------|--------|
| `infra/docker/requirements.txt` | Add magika, tree-sitter, tree-sitter-languages, networkx |
| `infra/docker/agents/router.py` | Add routing for `fde.onboarding.requested` events |
| `infra/terraform/main.tf` | Reference onboarding.tf module |
| `CHANGELOG.md` | Document new feature |

---

## 12. Out of Scope (Confirmed)

- Real-time file watching (scan is triggered, not continuous)
- Code quality scoring (FDE pipeline's job, not onboarding)
- Automatic steering application (human approves)
- Monorepos > 500K files (sampling is acceptable)
- Exotic language ASTs beyond Python, JS/TS, Go, Java, Rust, HCL
- Multi-repo dependency graphs (each repo scanned independently)

