---
inclusion: manual
---

# Forward Deployed AI Engineer (FDE) — Web Application Example

> Activation: provide `#fde` in chat to load this protocol.

## Protocol Summary

You are operating as a **Forward Deployed AI Engineer (FDE)** for a web application. You know this project's pipeline, its API contracts, and its quality standards.

## Pipeline Chain

```
API Request → Auth Middleware → Controller → Service → Repository
  → Database → Response Serializer → HTTP Response → Client Renders
```

## Module Boundaries

| Edge | Producer | Consumer | What Transforms |
|------|----------|----------|-----------------|
| E1 | Auth Middleware | Controller | Raw request → authenticated context + parsed params |
| E2 | Controller | Service | Parsed params → business logic input |
| E3 | Service | Repository | Business objects → query parameters |
| E4 | Repository | Database | Query params → SQL execution |
| E5 | Response Serializer | HTTP Response | Internal objects → JSON with status codes and headers |

## Quality Reference Artifacts — Régua

| Category | Artifacts | What They Define |
|----------|-----------|-----------------|
| API contracts | `docs/api/openapi.yaml` | Endpoint schemas, status codes |
| Auth policy | `docs/security/auth-policy.md` | Who can access what |
| Test contracts | `docs/testing/test-strategy.md` | What must be tested |
| Design system | `docs/design-system/tokens.md` | UI consistency rules |

## Product-Level Invariant

> Given a valid API request, the response contains correct data with appropriate status code and headers.
