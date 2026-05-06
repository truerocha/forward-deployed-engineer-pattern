# ADR-016: Ephemeral Catalog and Data Residency for Regulated Environments

## Status
Accepted

## Date
2026-05-06

## Context

The Repo Onboarding Agent (ADR-015) persists a SQLite catalog containing:
- File paths and directory structure (organizational IP)
- Module names and function signatures (code structure metadata)
- Import graphs and dependency relationships (architecture intelligence)
- Tech stack tags and convention data (technology posture)
- Pipeline chain and module boundaries (system design knowledge)

In regulated environments (financial services, healthcare, government, defense), this metadata constitutes **sensitive intellectual property** or **regulated data** that:

1. **Cannot be exfiltrated** — even to the customer's own S3 bucket in some air-gapped environments
2. **Must have provable lifecycle** — creation, use, and destruction must be auditable
3. **Must remain within compute boundary** — no network transfer of code metadata
4. **Must be customer-controlled** — the customer decides retention, not the factory operator

### Regulatory Drivers

| Regulation | Requirement | Impact on Catalog |
|------------|-------------|-------------------|
| SOC 2 Type II | Data classification and handling controls | Catalog must be classified and handled per policy |
| PCI DSS 4.0 | Cardholder data environment isolation | If scanning payment code, catalog is in-scope |
| HIPAA | PHI cannot leave covered entity boundary | If scanning healthcare code, metadata may be PHI-adjacent |
| FedRAMP High | Data must remain in authorized boundary | No S3 unless in authorized ATO boundary |
| ITAR/EAR | Technical data export controls | Code structure of defense systems is controlled |
| GDPR Art. 28 | Data processor obligations | Catalog is processing output; customer is controller |
| Internal IP Policy | Source code metadata is trade secret | Many enterprises classify code structure as confidential |

### Current Architecture Gap

The current design has a single persistence path:
```
Catalog Writer → S3 Persister → s3://bucket/catalogs/{owner}/{repo}/catalog.db
```

This assumes:
- Network access to S3 is available
- Data transfer to S3 is permitted
- S3 bucket is within the customer's trust boundary
- Indefinite retention is acceptable

None of these hold in air-gapped, regulated, or high-security environments.

## Decision

### Introduce Three Catalog Persistence Modes

The Onboarding Agent supports three mutually exclusive persistence modes, selected at deployment time:

| Mode | Storage | Network | Retention | Use Case |
|------|---------|---------|-----------|----------|
| `cloud` | S3 bucket (existing) | Required | Indefinite (S3 versioning) | Standard cloud deployment |
| `local` | Workspace filesystem | None | Session-scoped | Developer experimentation |
| `ephemeral` | Encrypted Docker volume | None | Customer-controlled TTL | Regulated environments |

### Ephemeral Mode Architecture

```
┌─────────────────────────────────────────────────────┐
│  Customer-Controlled Docker Host                     │
│                                                      │
│  ┌──────────────────┐    ┌────────────────────────┐ │
│  │ Onboarding Agent │    │ Encrypted Volume       │ │
│  │ (ECS/Docker)     │───▶│ /data/catalog.db       │ │
│  │                  │    │ /data/steering-draft.md │ │
│  │ No network out   │    │ AES-256 at rest        │ │
│  └──────────────────┘    │ Customer KMS key       │ │
│                           │ Auto-destroy on TTL    │ │
│                           └────────────────────────┘ │
│                                                      │
│  ┌──────────────────┐                               │
│  │ Audit Sidecar    │                               │
│  │ (logs only)      │──▶ Customer CloudWatch/SIEM   │
│  └──────────────────┘                               │
└─────────────────────────────────────────────────────┘
```

### Key Design Properties

**1. No network egress for catalog data**
- The onboarding container runs with no outbound network or VPC-endpoint-only access
- Bedrock access (for Haiku) uses a VPC endpoint (no public internet)
- The only network traffic is: Bedrock invoke (via VPC endpoint) + audit logs (to customer SIEM)

**2. Customer-controlled encryption**
- Docker volume encrypted with customer's KMS key (not factory operator's key)
- Key rotation follows customer's policy
- Factory operator cannot decrypt catalog without customer's key

**3. Provable destruction**
- TTL-based auto-destruction: volume is deleted after configurable retention period
- Destruction event logged to audit trail (tamper-evident)
- Customer can trigger immediate destruction via API call
- Docker volume deletion is cryptographic erasure (key destruction = data destruction)

**4. Audit trail without data exposure**
- Audit sidecar logs: scan started, scan completed, files_count, modules_count, duration
- Audit sidecar NEVER logs: file paths, module names, dependency edges, tech stack
- Audit events go to customer's SIEM (not factory operator's logging)

**5. Steering output is the only "export"**
- The generated `fde-draft.md` is the only artifact that leaves the ephemeral boundary
- Staff Engineer reviews it inside the compute boundary (via Kiro IDE or terminal)
- If approved, Staff Engineer manually copies it to the workspace (human decision, not automated)

### Configuration

```yaml
# Environment variable or ECS task definition
CATALOG_MODE: "ephemeral"  # cloud | local | ephemeral

# Ephemeral mode configuration
EPHEMERAL_VOLUME_PATH: "/data"
EPHEMERAL_ENCRYPTION_KEY_ARN: "arn:aws:kms:us-east-1:CUSTOMER_ACCOUNT:key/customer-key-id"
EPHEMERAL_TTL_HOURS: 24
EPHEMERAL_AUDIT_ENDPOINT: "https://customer-siem.internal/events"
EPHEMERAL_NETWORK_MODE: "none"   # No outbound network (except VPC endpoints)
```

### Integration with Existing Pipeline

The `pipeline.py` orchestrator selects persistence strategy based on `CATALOG_MODE`:

```python
if mode == "cloud":
    # Existing: S3 Persister uploads to bucket
    persist_to_s3(...)
elif mode == "local":
    # Existing: catalog.db in workspace root
    pass  # Already written by Catalog Writer
elif mode == "ephemeral":
    # New: catalog stays in encrypted volume, audit event emitted
    emit_audit_event("catalog_written", {"path": volume_path, "ttl_hours": ttl})
    # No S3 upload, no network transfer
    # Steering draft written to volume for human review
```

## Consequences

### Positive
- Enables deployment in air-gapped and regulated environments
- Customer retains full control over their code metadata
- Provable data lifecycle satisfies SOC 2, PCI DSS, HIPAA audit requirements
- No architectural change to the scanning pipeline itself (only persistence layer)
- Factory operator never has access to customer's code structure

### Negative
- Ephemeral mode cannot do incremental re-scan across sessions (catalog destroyed after TTL)
- No cross-session catalog comparison (each scan is independent)
- Bedrock VPC endpoint required (additional infrastructure cost)
- Customer must manage KMS key and volume lifecycle
- More complex deployment (Docker volume management vs simple S3 upload)

### Trade-offs

| Capability | Cloud Mode | Ephemeral Mode |
|------------|-----------|----------------|
| Incremental re-scan | Yes (catalog persists in S3) | No (catalog destroyed after TTL) |
| Cross-session comparison | Yes | No |
| Steering diff on re-scan | Yes | No (no previous scan to diff against) |
| Data residency compliance | Depends on S3 location | Never leaves compute boundary |
| Audit trail | CloudWatch logs | Customer SIEM (tamper-evident) |
| Operator access to metadata | S3 bucket access possible | Operator cannot access |
| Deployment complexity | Low (S3 bucket exists) | Medium (KMS + volume + VPC endpoint) |

## Security Controls Matrix

| Control | Cloud Mode | Ephemeral Mode |
|---------|-----------|----------------|
| Encryption at rest | S3 SSE-S3/SSE-KMS | Docker volume + customer KMS |
| Encryption in transit | HTTPS to S3 | N/A (no transit) |
| Access control | IAM role (factory operator) | Customer KMS policy (customer only) |
| Data classification | Not enforced | Enforced (all catalog data = confidential) |
| Retention policy | S3 lifecycle rules | TTL-based auto-destruction |
| Destruction verification | S3 delete (soft delete with versioning) | Cryptographic erasure (key destruction) |
| Audit logging | CloudWatch (factory account) | Customer SIEM (customer account) |
| Network boundary | VPC + security groups | No network (or VPC endpoint only) |

## Data Handling Across the Full Pipeline

This ADR also establishes data handling principles for the entire Code Factory pipeline, not just the Onboarding Agent:

### What Data Flows Through the Factory

| Data Type | Classification | Handling Rule |
|-----------|---------------|---------------|
| Source code (cloned repo) | Customer Confidential | Never persisted beyond task lifetime. Workspace deleted at container exit. |
| Catalog metadata (file paths, modules, deps) | Customer Confidential | Persisted per CATALOG_MODE. Encrypted at rest. Customer-controlled retention. |
| LLM prompts (structured summaries) | Customer Confidential | Sent to Bedrock via VPC endpoint. Not logged. Not stored by Bedrock (data opt-out). |
| LLM responses (inferred patterns) | Derived IP | Written to catalog only. Same handling as catalog metadata. |
| Steering draft (generated markdown) | Customer Confidential | Written to staging location. Human reviews before activation. |
| Audit events (counts, durations) | Operational | Safe to export to customer SIEM. No code content. |
| ALM tokens (PATs) | Secret | ADR-014 fetch-use-discard. Never in context window. Never logged. |

### Bedrock Data Privacy

- AWS Bedrock does NOT use customer inputs/outputs to train models (opt-out by default for on-demand)
- VPC endpoint ensures traffic never traverses public internet
- No prompt logging enabled (customer controls CloudWatch log group)
- Model invocation logs can be disabled at the Bedrock level

### Container Security Posture

| Property | Standard Mode | Ephemeral Mode |
|----------|--------------|----------------|
| Root user | No (non-root user) | No (non-root user) |
| Read-only filesystem | Yes (except /tmp and workspace) | Yes (except /data volume) |
| Network egress | S3, Secrets Manager, Bedrock, CloudWatch | Bedrock VPC endpoint only |
| Capabilities | Dropped (no SYS_ADMIN, no NET_RAW) | Dropped (all capabilities) |
| Seccomp profile | Default Docker profile | Restricted profile |
| Resource limits | 1 vCPU / 2GB / 5min timeout | Same |

## Implementation Plan

1. Add `CATALOG_MODE` environment variable to Trigger Handler
2. Create `infra/docker/agents/onboarding/ephemeral_persister.py` (volume write + audit emit)
3. Modify `pipeline.py` to branch on `CATALOG_MODE` at persistence stage
4. Create `infra/docker/Dockerfile.onboarding-agent-ephemeral` (hardened, no-network variant)
5. Create `infra/terraform/onboarding-ephemeral.tf` (KMS key, VPC endpoint, ECS task with no-network)
6. Add audit event schema to observability module
7. Document deployment guide for regulated environments
8. Add Bedrock data opt-out verification to deployment checklist

## Related

- **ADR-014** — Secret Isolation (same principle: minimize data exposure surface)
- **ADR-015** — Repo Onboarding Agent (base architecture this extends)
- **ADR-009** — AWS Cloud Infrastructure (VPC endpoint pattern)
- **WA SEC 7** — Data classification
- **WA SEC 8** — Data protection at rest
- **WA SEC 9** — Data protection in transit
- **WA SEC 10** — Data lifecycle management
- **WA Data Residency Lens** — Processing within approved boundaries
- **WA Financial Services Lens** — Three Lines of Defense model
