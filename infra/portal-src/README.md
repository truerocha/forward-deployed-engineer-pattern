# FDE Code Factory — Observability Portal

The Code Factory portal is a React SPA (Vite + Tailwind) that provides real-time observability into the distributed squad execution pipeline.

## Components

- **DoraCard** — DORA metrics per autonomy level
- **CostCard** — Token usage and cost tracking
- **SquadExecutionCard** — Per-agent status and progress
- **ConductorPlanCard** — Workflow topology visualization (ADR-020)
- **BrainSimCard** — Fidelity scoring and emulation metrics
- **LiveTimeline** — Real-time event stream
- **MaturityRadar** — 7-capability system maturity
- **PersonaRouter** — Role-based view filtering (Staff SWE / SRE / TPM)

## Run Locally

**Prerequisites:** Node.js 18+

1. Install dependencies:
   ```bash
   npm install
   ```

2. Configure environment (copy from example):
   ```bash
   cp .env.example .env.local
   ```
   Edit `.env.local` with your API Gateway URL (from Terraform outputs).

3. Run the dev server:
   ```bash
   npm run dev
   ```

## Build for Production

```bash
npm run build
```

Output goes to `dist/` and is synced to `infra/dashboard/` by the deploy script.

## Deploy

```bash
# From repo root:
export AWS_PROFILE=your-sso-profile
bash scripts/deploy-dashboard.sh --build
```

## Architecture

- **Framework**: React 18 + TypeScript + Vite
- **Styling**: Tailwind CSS
- **Animations**: Motion (framer-motion)
- **Icons**: Lucide React
- **Data**: Fetches from API Gateway (`/status/tasks`) via `factoryService.ts`
- **Hosting**: S3 + CloudFront (OAC, SSE-S3 encryption)
