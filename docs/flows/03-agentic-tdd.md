# Agentic TDD Flow

```mermaid
flowchart TD
    SPEC[Read Spec Scenarios] --> TESTS[Generate Tests From Scenarios]
    TESTS --> REDBAR[Run Tests - Expect Red Bar]
    REDBAR --> APPROVE{Human Approves Tests?}
    APPROVE -->|No| TESTS
    APPROVE -->|Yes| MARK[Add human-approved Marker]
    MARK --> IMPL[Implement Production Code]
    IMPL --> RUN[Run Tests]
    RUN -->|Green| DOD[DoD Gate]
    RUN -->|Red| CB{Circuit Breaker}
    CB -->|Code Error| IMPL
    CB -->|Environment Error| STOP[Report to Human]
    CB -->|3 Approaches Exhausted| ROLLBACK[Rollback and Report]
```
