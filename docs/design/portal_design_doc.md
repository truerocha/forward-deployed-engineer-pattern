# Code Factory Portal — Design Document

> Status: Implemented (Phase A + Phase B)
> Author: FDE Agent
> Date: 2026-05-07
> Dashboard URL: https://d3btj6a4igoa8k.cloudfront.net

---

## 1. Problem Statement

The Code Factory pipeline executes autonomously — agents ingest tasks, run reconnaissance, engineer solutions, and deliver PRs. But the **human stakeholders** (PM, Staff Engineer, Tech Lead) had no way to understand *what the factory decided and why* without running:

```bash
AWS_PROFILE=your-sso-profile aws logs tail /ecs/fde-dev --follow --since 1m --region us-east-1
```

This is unacceptable for a PM. The original dashboard was a flat 3-panel real-time monitor (agents | flow | logs) with:
- No navigation between sections
- No structured reasoning visibility
- No gate decision transparency
- No intentional UX journey per persona

The PM explicitly requested a **rail navigation** pattern similar to the cognitive-wafr portal (`wafr/assets/*.html`) that separates sections and enables intentional navigation.

---

## 2. Design Decisions

### 2.1 Why Modular (Not Monolithic)

The original dashboard was a single 500-line `index.html`. The adversarial analysis rejected:

| Approach | Rejected Because |
|----------|-----------------|
| Multi-page app (separate HTML files) | Breaks real-time state; full page reloads lose polling state |
| ES Modules + bundler (Vite/Webpack) | Introduces build step; violates zero-dependency principle |
| Web Components | Solves developer ergonomics, not user navigation |
| Single monolith with inlined views | PM can't reason about sections; developer can't extend one view without reading 700 lines |

**Accepted**: Modular SPA with native ES modules, hash routing, and file-per-view separation.

### 2.2 Why Zero Dependencies

Per ADR-011 (YAGNI) and Well-Architected Security pillar (SEC 6 — minimize attack surface):
- No `npm install`, no `node_modules`, no build pipeline
- Native `<script type="module">` — supported by all modern browsers
- S3 serves `.js` files with correct MIME types natively
- Deploy script remains a simple `aws s3 sync` — atomic, no partial upload risk
- Zero supply chain risk in enterprise environments

### 2.3 Why Rail Navigation (Not Tabs, Not Sidebar)

The rail pattern was chosen because:
- **Compact**: 64px width — doesn't steal content space
- **Always visible**: Unlike tabs, the rail is persistent across all views
- **Icon + label**: Scannable at a glance without reading
- **Deep-linkable**: Hash URLs (`#pipeline`, `#reasoning`) enable sharing specific views
- **Familiar**: Matches VS Code, AWS Console, and the cognitive-wafr portal pattern the PM referenced

---

## 3. Architecture

### 3.1 File Structure

```
infra/dashboard/
├── index.html              # Shell: <head>, rail nav, view containers, module imports
├── css/
│   └── factory.css         # Design tokens, layout, all component styles (BEM)
├── js/
│   ├── api.js              # State management, fetch, event bus, helpers
│   └── router.js           # Hash-based view switching, active state management
├── views/
│   ├── pipeline.js         # Pipeline Activity — task flow with status dots
│   ├── agents.js           # Autonomous Units — agent cards with progress
│   ├── reasoning.js        # Chain of Thought — structured reasoning timeline
│   ├── gates.js            # Gate Decisions — pass/fail with criteria
│   └── health.js           # DORA Metrics + System Health Checks
└── img/
    └── proserve-logo.png   # Brand asset
```

### 3.2 Module Responsibilities

| Module | Responsibility | Exports |
|--------|---------------|---------|
| `api.js` | Fetches `/status/tasks` every 15s, manages app state, notifies subscribers | `subscribe()`, `getState()`, `refreshData()`, `checkHealth()`, `fmt()`, `esc()` |
| `router.js` | Listens to `hashchange`, toggles `.cf-view--active` class, updates rail active state | `initRouter()`, `navigateTo()`, `getCurrentView()` |
| `pipeline.js` | Renders task flow nodes with status dots, project filter, priority badges | `init()` |
| `agents.js` | Renders agent cards with stage timeline, progress bar, PR links | `init()` |
| `reasoning.js` | Groups events by task, renders structured timeline with phase/gate/criteria metadata | `init()` |
| `gates.js` | Filters gate events, shows pass/fail summary + individual decision cards | `init()` |
| `health.js` | Renders DORA metric cards + health check results | `init()` |

### 3.3 Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    api.js (State Layer)                       │
│                                                              │
│  fetch(/status/tasks) ──→ state.tasks, state.metrics, ...   │
│  fetch(/status/health) ──→ state.health                     │
│                                                              │
│  notify() ──→ all subscribers re-render                     │
└──────────────────────────┬──────────────────────────────────┘
                           │ subscribe(fn)
          ┌────────────────┼────────────────────┐
          ▼                ▼                    ▼
    pipeline.js      reasoning.js         health.js
    agents.js        gates.js
    (header stats)
```

### 3.4 View Switching (Router)

```
URL: https://d3btj6a4igoa8k.cloudfront.net#reasoning
                                            ▲
                                            │
router.js listens to hashchange ────────────┘
  │
  ├── document.querySelectorAll('.cf-view')
  │     → toggle cf-view--active based on data-view === hash
  │
  └── document.querySelectorAll('.cf-rail__item')
        → toggle cf-rail__item--active based on data-nav === hash
```

---

## 4. UX Design

### 4.1 Layout

```
┌─────────────────────────────────────────────────────────────┐
│ HEADER (56px) — brand, live stats, theme toggle             │
├────┬────────────────────────────────────────────────────────┤
│    │                                                        │
│ R  │  CONTENT AREA                                          │
│ A  │                                                        │
│ I  │  Switches based on active hash route.                  │
│ L  │  Only one view visible at a time.                      │
│    │  Each view has: header (title + actions) + body        │
│ 64 │                                                        │
│ px │                                                        │
│    │                                                        │
└────┴────────────────────────────────────────────────────────┘
```

### 4.2 Navigation Rail

| Icon | Label | Hash | View |
|------|-------|------|------|
| ▶ | Pipeline | `#pipeline` | Task flow with status dots |
| ⚡ | Agents | `#agents` | Agent cards with progress |
| 👁 | Reasoning | `#reasoning` | Structured CoT timeline |
| 🛡 | Gates | `#gates` | Gate pass/fail decisions |
| 💚 | Health | `#health` | DORA + system diagnostics |

### 4.3 Persona Journeys

#### PM: "What did the factory decide and why?"

```
#pipeline → See what's running, what completed
    ↓ clicks task (future: deep-link)
#reasoning → See structured CoT: intake contract, adversarial challenges, gate decisions
    ↓ wants to verify quality
#gates → See all gate pass/fail with criteria evaluated
    ↓ wants the outcome
#pipeline → PR link, completion status
```

#### Staff Engineer: "Is the system healthy?"

```
#health → DORA metrics, health checks, degradation alerts
    ↓ sees a failure
#agents → Which agent failed? What stage? Error detail?
    ↓ wants the log
#reasoning → Full event timeline for that agent's task
    ↓ wants to retry
#pipeline → Issue link → re-label → factory picks it up
```

#### Developer: "I need to add a new view"

```
1. Create views/my-new-view.js (export init() function)
2. Add <section class="cf-view" data-view="myview"> to index.html
3. Add <a class="cf-rail__item" data-nav="myview"> to the rail
4. Import and call init() in the <script type="module"> block
5. Done. No other files touched.
```

---

## 5. Design System

### 5.1 Design Tokens

| Token | Dark | Light | Usage |
|-------|------|-------|-------|
| `--bg` | `#050507` | `#f8fafc` | Page background |
| `--surface` | `rgba(15,15,20,0.85)` | `rgba(255,255,255,0.95)` | Panel backgrounds |
| `--accent` | `#6366f1` | `#6366f1` | Active states, links |
| `--success` | `#10b981` | `#10b981` | Completed, passed |
| `--warning` | `#f59e0b` | `#f59e0b` | Degraded, blocked |
| `--error` | `#ef4444` | `#ef4444` | Failed, errors |
| `--running` | `#8b5cf6` | `#8b5cf6` | In-progress states |
| `--font` | Inter | Inter | Body text |
| `--mono` | Fira Code | Fira Code | Code, metrics, timestamps |

### 5.2 Component Library

| Component | Class | Usage |
|-----------|-------|-------|
| Card | `.cf-card` | Agent cards, metric cards |
| Badge | `.cf-badge--{status}` | Status indicators (running, completed, failed, etc.) |
| Button | `.cf-btn` | Actions (refresh, check health) |
| Flow Node | `.cf-flow-node` + `.cf-flow-dot` | Pipeline task entries |
| Reasoning Entry | `.cf-reasoning-entry--{type}` | Timeline entries with colored left border |
| Gate Card | `.cf-gate-card` | Gate decision with icon + info + timestamp |
| Metric Card | `.cf-metric-card` | Large number + label (DORA metrics) |
| Health Grid | `.cf-health-grid` | Auto-fit grid for metric cards |

### 5.3 Theming

Two themes supported via `[data-theme="light"]` CSS attribute selector:
- **Dark** (default): Optimized for monitoring dashboards, low-light environments
- **Light**: AWS-branded header (`#232F3E` + `#FF9900` border), white content area

Toggle persisted to `localStorage('cf-theme')`.

---

## 6. API Contract

### 6.1 GET /status/tasks

Returns the full dashboard payload. Supports `?repo=owner/repo` filter.

```json
{
  "metrics": {
    "active": 2,
    "completed_24h": 5,
    "failed_24h": 1,
    "avg_duration_ms": 180000,
    "total_agents_provisioned": 3,
    "active_agents": 2
  },
  "dora": {
    "level": "High",
    "lead_time_avg_ms": 240000,
    "success_rate_pct": 85,
    "throughput_24h": 5,
    "change_failure_rate_pct": 15
  },
  "tasks": [
    {
      "task_id": "TASK-03b21106",
      "title": "Add pagination to /users endpoint",
      "status": "running",
      "current_stage": "engineering",
      "stage_progress": { "current": 5, "total": 8, "percent": 62 },
      "agent": { "instance_id": "AGENT-a1b2c3d4", "name": "fde-pipeline" },
      "repo": "truerocha/cognitive-wafr",
      "issue_url": "https://github.com/truerocha/cognitive-wafr/issues/42",
      "pr_url": "",
      "priority": "P1",
      "elapsed_ms": 120000,
      "events": [
        {
          "ts": "2026-05-07T14:30:00Z",
          "type": "system",
          "msg": "Pipeline started — autonomy=L3, confidence=high",
          "phase": "intake",
          "autonomy_level": "L3",
          "confidence": "high"
        },
        {
          "ts": "2026-05-07T14:30:05Z",
          "type": "gate",
          "msg": "Concurrency guard: 1/2 slots used — proceeding",
          "gate_name": "concurrency",
          "gate_result": "pass",
          "criteria": "max_concurrent=2 for repo=truerocha/cognitive-wafr"
        }
      ]
    }
  ],
  "projects": [
    { "repo": "truerocha/cognitive-wafr", "display_name": "cognitive-wafr", "task_count": 3, "active": 1 }
  ]
}
```

### 6.2 GET /status/tasks/{task_id}/reasoning

Returns the full reasoning timeline for a single task (not capped at 20 events).

```json
{
  "task_id": "TASK-03b21106",
  "title": "Add pagination to /users endpoint",
  "status": "running",
  "current_stage": "engineering",
  "events": [ ],
  "reasoning_events": [ ],
  "gate_events": [ ],
  "gate_summary": {
    "total": 4,
    "passed": 3,
    "failed": 1
  }
}
```

### 6.3 GET /status/health

Returns system health diagnostics.

```json
{
  "status": "healthy|degraded|unhealthy",
  "checks": [
    { "name": "task_queue_table", "status": "pass", "detail": "Accessible" },
    { "name": "stuck_tasks", "status": "warn", "detail": "1 task running >30min" },
    { "name": "agent_capacity", "status": "pass", "detail": "2/10 agents active (20%)" }
  ]
}
```

### 6.4 Structured Event Schema (Phase B)

Events emitted by the orchestrator now include optional structured fields:

| Field | Type | When Present | Example |
|-------|------|-------------|---------|
| `ts` | string (ISO 8601) | Always | `"2026-05-07T14:30:00Z"` |
| `type` | string | Always | `"system"`, `"agent"`, `"gate"`, `"error"`, `"tool"` |
| `msg` | string (max 200) | Always | `"Pipeline started — autonomy=L3"` |
| `phase` | string | When in a named phase | `"intake"`, `"reconnaissance"`, `"engineering"` |
| `gate_name` | string | Gate events | `"dor"`, `"adversarial"`, `"concurrency"`, `"dod"` |
| `gate_result` | string | Gate events | `"pass"` or `"fail"` |
| `criteria` | string (max 150) | Gate events | `"max_concurrent=2 for repo=org/repo"` |
| `context` | string (max 300) | Rich reasoning | `"Scope check passed. Gates resolved: outer=[...], inner=[...]"` |
| `autonomy_level` | string | Pipeline start | `"L3"`, `"L5"` |
| `confidence` | string | Pipeline start | `"high"`, `"medium"`, `"low"` |

**Backward compatibility**: Old events without these fields render normally. The dashboard checks for field existence before rendering enriched UI.

---

## 7. Deployment

### 7.1 Dashboard Deploy

```bash
bash scripts/deploy-dashboard.sh --profile your-sso-profile
```

What it does:
1. Reads API URL from `terraform output`
2. Injects URL into `index.html` via `<meta>` tag (`sed`)
3. Copies entire `infra/dashboard/` directory to a temp folder
4. Runs `aws s3 sync` to `s3://fde-dev-artifacts-YOUR_ACCOUNT_ID/dashboard/`
5. Invalidates CloudFront cache (`/*`)

### 7.2 Infrastructure Deploy

```bash
cd infra/terraform
AWS_PROFILE=your-sso-profile terraform apply -var-file=factory.tfvars
```

Phase B added:
- API Gateway route: `GET /status/tasks/{task_id}/reasoning`
- Lambda code update: `_handle_reasoning()` handler

### 7.3 Agent Docker Image

The enriched event emissions (Phase B) require rebuilding the Docker image:

```bash
docker build -t fde-strands-agent infra/docker/
# Tag and push to ECR
```

---

## 8. Extensibility

### Adding a New View

1. Create `infra/dashboard/views/my-view.js`:
```javascript
import { subscribe, esc } from '../js/api.js';

export function init() {
  const container = document.querySelector('[data-view="myview"]');
  const body = container.querySelector('.cf-view__body');
  subscribe((state) => render(body, state));
}

function render(body, state) {
  body.innerHTML = '...';
}
```

2. Add section to `index.html`:
```html
<section class="cf-view" data-view="myview">
  <div class="cf-view__header">
    <div class="cf-view__title">My View</div>
  </div>
  <div class="cf-view__body"></div>
</section>
```

3. Add rail item:
```html
<a class="cf-rail__item" href="#myview" data-nav="myview">
  <span class="cf-rail__icon">🆕</span>
  <span class="cf-rail__label">My View</span>
</a>
```

4. Import in the module script:
```javascript
import { init as initMyView } from './views/my-view.js';
initMyView();
```

### Adding Structured Event Fields

1. Add field name to `allowed_fields` tuple in `task_queue.py`:
```python
allowed_fields = ("phase", "gate_name", "gate_result", "criteria", "context",
                  "autonomy_level", "confidence", "my_new_field")
```

2. Emit from orchestrator:
```python
task_queue.append_task_event(task_id, "agent", "Message", my_new_field="value")
```

3. Consume in dashboard view:
```javascript
${ev.my_new_field ? `<div>...</div>` : ''}
```

---

## 9. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| API exposed publicly | CORS `Access-Control-Allow-Origin: *` — read-only data, no mutations |
| Event content | `msg` capped at 200 chars, `context` at 300 chars — prevents DynamoDB item bloat |
| Secrets in events | Orchestrator never emits tokens, credentials, or internal paths in events |
| XSS in dashboard | All dynamic content passed through `esc()` (textContent-based escaping) |
| Supply chain | Zero external JS dependencies — no npm, no CDN-hosted libraries |
| S3 access | Bucket has public access blocked; CloudFront OAC provides read access |
| Dashboard auth | Currently none (CloudFront public). Future: CloudFront signed cookies or Cognito |

---

## 10. Well-Architected Alignment

| Pillar | How This Design Aligns |
|--------|----------------------|
| **Operational Excellence** | Dashboard provides real-time observability without CLI access. DORA metrics enable continuous improvement. |
| **Security** | Zero dependencies = zero supply chain risk. No secrets in events. S3 encryption (SSE-S3). |
| **Reliability** | Single-file deploy is atomic. CloudFront provides edge caching. API has health endpoint for self-diagnosis. |
| **Performance Efficiency** | Native ES modules — no bundler overhead. 15s polling (not WebSocket) — simpler, sufficient for dashboard use case. |
| **Cost Optimization** | Static site on S3+CloudFront — pennies/month. Lambda on-demand — no idle compute. DynamoDB PAY_PER_REQUEST. |
| **Sustainability** | Minimal compute — static assets cached at edge. No always-on servers for the dashboard. |

---

## 11. Known Limitations & Future Work

| Limitation | Impact | Future Resolution |
|-----------|--------|-------------------|
| No authentication on dashboard | Anyone with URL can view pipeline state | Add CloudFront signed cookies or Cognito |
| Events capped at 50 per task | Long-running tasks may lose early events | Archive to S3, load on-demand in reasoning view |
| No task deep-link from pipeline view | PM can't click a task to see its reasoning | Add click handler → `navigateTo('reasoning')` with task filter |
| No WebSocket for real-time updates | 15s polling delay | Evaluate AppSync or API Gateway WebSocket if latency matters |
| Reasoning view shows all tasks | No per-task filtering in the UI | Add task selector dropdown in reasoning view header |
| Docker image must be rebuilt for Phase B events | Existing running agents emit old-format events | Next deploy cycle picks it up automatically |
