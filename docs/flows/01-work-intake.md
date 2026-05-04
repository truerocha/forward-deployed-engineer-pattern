# Work Intake Flow

How work enters the factory from ALM systems.

```mermaid
flowchart LR
    GH[GitHub Issue] --> FORMAT{NLSpec Format?}
    AS[Asana Task] --> FORMAT
    FORMAT -->|No| HUMAN[Staff Engineer Writes Spec]
    FORMAT -->|Yes| SPEC[.kiro/specs/feature.md]
    HUMAN --> SPEC
    SPEC --> FM{Frontmatter status: ready?}
    FM -->|No| HUMAN
    FM -->|Yes| AGENT[Agent Pipeline Triggered]
```
