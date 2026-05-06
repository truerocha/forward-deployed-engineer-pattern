---
status: ready
level: L4
source: github
feature: repo-onboarding-agent
---

# Requirements: Repo Onboarding Agent (Phase 0 — Codebase Reasoning Brain)

## Overview

The Repo Onboarding Agent is a new Phase 0 that runs before the FDE intake pipeline for any project. It clones a target repository, scans its structure using lightweight tools (Magika for file type detection, tree-sitter for AST extraction), classifies the codebase into a structured catalog, and generates the project-specific FDE steering (pipeline chain, module boundaries, tech stack tags, engineering level patterns).

This agent runs on the existing ECS/ECR infrastructure and persists its catalog to a lightweight store (SQLite packaged as an S3 artifact). The catalog becomes the "codebase reasoning brain" — the canonical source of truth about a project's structure that all downstream FDE agents consume.

## Problem Statement

Today, deploying the FDE into a new project requires manual customization of the steering file (pipeline chain, module boundaries, quality artifacts, tech stack). This is:
1. Time-consuming (30+ minutes per project)
2. Error-prone (humans miss module boundaries)
3. Static (doesn't update as the codebase evolves)
4. Not scalable (each new project needs a human to configure)

The factory needs to self-configure from the codebase itself.

## Stakeholders

- **Staff Engineer** — triggers onboarding for new projects, approves generated steering
- **FDE Pipeline** — consumes the catalog during intake (Phase 2) to populate data contracts
- **Code Factory Infrastructure** — runs the scanner on ECS, stores catalog in S3

## Requirements

### REQ-1: Repository Cloning and Access

#### REQ-1.1: Clone any Git repository
The agent MUST clone any Git repository accessible via `gh` CLI or HTTPS git credentials. It MUST support GitHub, GitLab, and Bitbucket origins.

#### REQ-1.2: Shallow clone for speed
The agent MUST use shallow clone (`--depth 1`) by default to minimize network transfer and disk usage. Full history clone MUST be opt-in via configuration.

#### REQ-1.3: Credential isolation
Repository credentials (PATs, SSH keys) MUST follow the ADR-014 fetch-use-discard pattern. Tokens are fetched from Secrets Manager at clone time and never stored in the agent's context window.

### REQ-2: Codebase Scanning

#### REQ-2.1: File type detection via Magika
The agent MUST use Google's Magika library to classify every file in the repository by content type (not just extension). This provides accurate detection of polyglot files, generated code, and misnamed files.

#### REQ-2.2: AST extraction via tree-sitter
The agent MUST use tree-sitter to parse source files and extract:
- Module/class/function signatures
- Import graphs (who imports whom)
- Public API surfaces
- File-level dependency relationships

#### REQ-2.3: Dependency graph construction
The agent MUST build a directed dependency graph from import statements and package manifests (package.json, requirements.txt, go.mod, Cargo.toml, pom.xml, etc.).

#### REQ-2.4: Convention detection
The agent MUST detect project conventions:
- Languages and their relative proportions
- Package managers (npm, pip, cargo, maven, etc.)
- Test frameworks (pytest, jest, go test, JUnit, etc.)
- Linters (ruff, eslint, golangci-lint, etc.)
- CI/CD systems (GitHub Actions, GitLab CI, Jenkins, etc.)
- Containerization (Dockerfile, docker-compose)
- IaC (Terraform, CDK, CloudFormation, SAM)

#### REQ-2.5: Scan performance
The agent MUST complete scanning for repositories up to 100,000 files within 5 minutes on a 1 vCPU / 2GB ECS Fargate task. Repositories exceeding this size MUST be sampled (top-level + most-connected modules).

### REQ-3: Pattern Extraction (Lightweight LLM)

#### REQ-3.1: Pipeline chain inference
The agent MUST use a lightweight LLM (Bedrock Claude Haiku) to infer the pipeline chain from the dependency graph and module structure. The LLM receives the dependency graph + file type summary (not raw code) and outputs a pipeline chain in the format: `Module A → Module B → Module C → Output`.

#### REQ-3.2: Module boundary detection
The agent MUST identify module boundaries (producer/consumer edges) from the dependency graph. Each edge MUST include: producer module, consumer module, and what transforms at the boundary.

#### REQ-3.3: Tech stack classification
The agent MUST produce a `tech_stack` array (e.g., `["Python", "AWS", "Bedrock", "DynamoDB", "React"]`) from detected languages, frameworks, cloud services, and infrastructure patterns.

#### REQ-3.4: Engineering level pattern detection
The agent MUST classify task patterns that indicate engineering level:
- **L2 patterns**: bugfix, typo, config change, dependency update
- **L3 patterns**: feature addition, refactoring, new module, API change
- **L4 patterns**: architecture change, multi-module redesign, new subsystem, cross-cutting concern

These patterns are stored as label rules in the catalog for dynamic level assignment during intake.

#### REQ-3.5: LLM cost control
The LLM pass MUST use Claude Haiku (not Sonnet) and MUST limit input to structured summaries (dependency graph, file type counts, convention list) — never raw source code. Maximum input: 8K tokens. Maximum cost per onboarding: $0.01.

### REQ-4: Catalog Persistence

#### REQ-4.1: SQLite catalog format
The agent MUST persist the extracted catalog as a SQLite database with the following tables:
- `repos` — repo_url, clone_date, commit_sha, scan_duration_ms
- `files` — path, magika_type, language, size_bytes, is_generated
- `modules` — name, path, type (package/class/namespace), file_count, line_count
- `dependencies` — source_module, target_module, dependency_type (import/call/inherit)
- `conventions` — category, name, version, config_path
- `pipeline_chain` — step_order, module_name, produces, consumes
- `module_boundaries` — edge_id, producer, consumer, transform_description
- `tech_stack` — tag, category (language/framework/cloud/infra), confidence
- `level_patterns` — pattern, level (L2/L3/L4), description

#### REQ-4.2: S3 storage
The SQLite file MUST be stored in the factory artifacts bucket at path: `catalogs/{repo_owner}/{repo_name}/catalog.db`. Versioning via S3 bucket versioning (already enabled).

#### REQ-4.3: Incremental updates
On subsequent onboarding runs, the agent MUST compare the current commit SHA with the stored one. If unchanged, skip scanning. If changed, perform a delta scan (only files modified since last scan) and update the catalog.

### REQ-5: Steering Generation

#### REQ-5.1: Generate project-specific FDE steering
The agent MUST generate a complete `.kiro/steering/fde.md` file for the target project containing:
- Pipeline chain (from `pipeline_chain` table)
- Module boundaries table (from `module_boundaries` table)
- Quality reference artifacts (detected from conventions)
- Tech stack tags

#### REQ-5.2: Human approval gate
The generated steering MUST be written to a staging location (`catalogs/{owner}/{repo}/steering-draft.md`) and NOT applied automatically. The Staff Engineer approves by copying it to the target workspace.

#### REQ-5.3: Diff on re-scan
When re-scanning an already-onboarded repo, the agent MUST produce a diff between the current steering and the proposed update, highlighting what changed (new modules, removed boundaries, tech stack additions).

### REQ-6: Integration with FDE Intake

#### REQ-6.1: Catalog lookup during intake
The FDE intake (Phase 2) MUST read the catalog for the current repo to auto-populate:
- `tech_stack` field in the data contract
- Engineering level suggestion based on task labels matching `level_patterns`
- Module context for the constraint extractor

#### REQ-6.2: Dynamic engineering level
During intake, the agent MUST compare task labels and description against `level_patterns` in the catalog. If a match is found, the suggested level overrides the default L3. The Staff Engineer can override via the `level:` field in the spec frontmatter.

#### REQ-6.3: Global environment variables
The `tech_stack` tags MUST be set as environment variables in the ECS task definition when running headless (cloud mode). In local mode, they MUST be read from the catalog at intake time.

### REQ-7: Infrastructure

#### REQ-7.1: ECS task definition
The onboarding agent MUST run as a separate ECS Fargate task definition (not the same as the FDE pipeline agent). It needs:
- `gh` CLI installed (for cloning)
- `magika` Python package
- `tree-sitter` with language grammars (Python, JavaScript, TypeScript, Go, Java, Rust, HCL)
- SQLite3
- Bedrock access (Haiku model)

#### REQ-7.2: Trigger mechanism
The onboarding agent MUST be triggerable via:
- EventBridge event (`fde.onboarding.requested` with repo URL in detail)
- Direct invocation (ECS RunTask with `REPO_URL` env var)
- Kiro hook (`fde-repo-onboard` userTriggered hook)

#### REQ-7.3: Isolation
Each onboarding run MUST be fully isolated (own ECS container, own workspace directory, own correlation ID). No cross-repo interference.

## Acceptance Criteria

1. Given a repo URL, the agent clones, scans, and produces a SQLite catalog in S3 within 5 minutes
2. The catalog contains accurate file types (validated against Magika ground truth)
3. The dependency graph correctly identifies import relationships (validated against known repos)
4. The pipeline chain inference produces a valid chain for cognitive-wafr (matches the known chain in the global steering)
5. The generated steering file contains all required sections (pipeline chain, module boundaries, tech stack)
6. Incremental re-scan correctly detects changes and updates only modified entries
7. The intake flow reads tech_stack and level_patterns from the catalog
8. Engineering level is dynamically assigned based on task labels matching catalog patterns
9. Total LLM cost per onboarding is under $0.01 (Haiku only, structured input)
10. No credentials are exposed to the agent's context window (ADR-014 compliance)

## Out of Scope

- Real-time file watching (scan is triggered, not continuous)
- Code quality scoring (that's the FDE pipeline's job, not onboarding)
- Automatic steering application (human approves the generated steering)
- Support for monorepos with >500K files (sampling is acceptable)
- Multi-language AST for exotic languages (start with Python, JS/TS, Go, Java, Rust, HCL)

## Dependencies

- Existing ECS cluster (`fde-dev-cluster`)
- Existing ECR repository (or new one: `fde-dev-onboarding-agent`)
- Existing S3 bucket (`fde-dev-artifacts-<ACCOUNT_ID>`)
- Existing Secrets Manager (`fde-dev/alm-tokens` for GitHub PAT)
- Bedrock access (Claude Haiku model)
- Magika: `pip install magika` (Google's file type detection, Apache 2.0 license)
- tree-sitter: `pip install tree-sitter tree-sitter-languages` (MIT license)
