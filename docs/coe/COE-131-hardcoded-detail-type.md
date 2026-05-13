# COE-131: Hardcoded EventBridge detail-type Blocks Review Feedback Loop

## Date
2026-05-13

## Severity
P1 — Review Feedback Loop (ADR-027) completely non-functional

## Impact
- PR review events from GitHub arrive on EventBridge with wrong detail-type
- Review Feedback Lambda never invoked
- Rework loop cannot trigger
- Factory appears to ignore human feedback entirely

## Root Cause (5 Whys)

1. Why didn't the Review Feedback Lambda fire? → EventBridge rule didn't match.
2. Why didn't the rule match? → Event arrived with detail-type "issue.labeled" instead of "pull_request_review.submitted".
3. Why wrong detail-type? → API Gateway EventBridge-PutEvents integration hardcodes DetailType="issue.labeled" for ALL GitHub events.
4. Why hardcoded? → Original integration built for single use case (issue labeled). ADR-027 added new event types but didn't update the API Gateway layer.
5. Why not caught? → No end-to-end test validated full path from GitHub webhook to Lambda invocation.

## The Architectural Flaw

EventBridge-PutEvents integration subtype does NOT support dynamic DetailType from request headers. It only accepts static values. This means X-GitHub-Event header is ignored.

Same flaw affects GitLab and Asana integrations.

## Fix

Replaced direct EventBridge-PutEvents integration with Webhook Router Lambda that reads platform-specific event type signals and sets correct detail-type dynamically.

## Prevention

1. End-to-end integration test for any new EventBridge rule
2. All ALM webhooks go through router Lambda (no more direct EventBridge-PutEvents)
3. Router logs every event type received (visibility even without matching rules)
