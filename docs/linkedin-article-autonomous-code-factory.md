# LinkedIn Article — v3 (Post-Framing Correction)

> Framing: Amplification + cognitive load reduction + DORA as proof mechanism
> Tone: Propositive, outcome-oriented, respects the reader's intelligence
> Target: Engineering Managers, Staff Engineers, CTOs (5,000+)
> Length: ~1,500 words

---

## IMAGE GUIDE

| Position | Image | File | Why |
|----------|-------|------|-----|
| **Header** | 5 Planes architecture (VSM → Data → Context → FDE → Control) | `docs/architecture/planes/00-hero-overview.png` | Represents the real data journey. Communicates depth to a technical audience. Consistent with the repo. |

One image. The text carries the narrative.

---

## ARTICLE TEXT (copy from here)

---

# One Engineer, Three Projects, Measured Outcomes

33% quality score without structured scaffolding. 100% with it. Same AI model. Same task.

The specification is the product. The code is the output.

That realization changed how I spend my engineering time. I moved from writing implementation code to writing specifications — defining what systems do, approving test contracts, and reviewing outcomes. AI agents handle the implementation, testing, and delivery across three projects in parallel.

This article describes the open-source pattern I built, what it amplifies, and how DORA metrics prove it works.

---

## What This Amplifies

Engineers spend a significant portion of their time on work that requires precision but not judgment: wiring API endpoints, writing boilerplate tests, configuring CI pipelines, formatting PRs. This work is essential but does not benefit from human creativity or architectural thinking.

The Forward Deployed Engineer pattern redirects that time. When AI agents handle implementation within governed constraints, engineers focus on:

→ Architectural decisions that shape system evolution
→ Trade-off analysis that requires business context
→ Acceptance criteria that define what "done" means
→ Outcome review that ensures customer value

The cognitive load shifts from "how do I implement this?" to "what should this system do?" — a higher-leverage use of engineering time.

---

## How It Works: The Specification as Control Plane

A Forward Deployed Engineer is an AI agent deployed into a project's specific context. It knows your pipeline architecture, your quality standards, your module boundaries, and your governance rules.

The operating model:

1. **You write a specification** with acceptance criteria (from GitHub, GitLab, or Asana)
2. **The factory extracts constraints** from your design documents automatically
3. **Specialized agents are provisioned** based on your tech stack and task type
4. **Quality gates validate every commit** (lint, test, build — with retry logic)
5. **A PR opens with validated code** — you review the outcome, not the diff

The specification is the control plane. The agent's halting condition is: make the approved tests pass while respecting all constraints. If it cannot, it classifies why and reports back.

---

## Autonomy Calibration: Adapting to Task Complexity

Not every task requires the same level of human involvement. The factory computes an autonomy level (L2 through L5) from the task's type and complexity:

→ **L5 (Observer)**: Bugfixes and documentation. Agents run autonomously. You monitor metrics.
→ **L4 (Approver)**: Standard features. You approve the final PR.
→ **L3 (Consultant)**: Architectural features. You approve the plan before engineering starts.
→ **L2 (Collaborator)**: High-uncertainty tasks. You checkpoint at every phase.

This calibration means simple tasks complete in minutes without human intervention, while complex tasks get the oversight they need. The factory adapts — you do not need to configure each task manually.

---

## DORA Metrics: Proving the Amplification Works

Measuring matters because without data, "AI-assisted development" is an opinion. With DORA metrics, it is a measurable engineering practice.

The factory computes four metrics continuously:

→ **Lead Time** (spec written → PR opened): measures how long the factory takes to deliver validated code. Target: under 2 hours for standard features.

→ **Change Failure Rate** (tasks that did not complete / total attempted): measures reliability. Segmented by tech stack — you see where the factory is strong (Python: 92%) and where it needs investment (Java: 67%).

→ **Deployment Frequency** (tasks completed per week): measures throughput. Three projects in parallel means 3x the delivery cadence with the same engineering headcount.

→ **MTTR** (time from error → next successful completion): measures recovery speed. Automatic rollback + failure classification means the factory recovers without human intervention for 60% of issues.

The Factory Health Report classifies performance as Elite, High, Medium, or Low — using the same thresholds the DORA research team defined. You know exactly where you stand.

**The insight for engineering leaders**: DORA metrics applied to AI-assisted development answer the question "is this working?" with data instead of anecdotes. You can compare performance across tech stacks, across task types, and across time periods.

---

## The Architecture: Five Modular Planes

The factory is organized into five planes, each owning a specific responsibility:

**1. Source Management** — Each task runs in an isolated namespace (branch, workspace, storage prefix). Multiple tasks run in parallel without interference.

**2. Data** — A canonical data contract enters from any ALM platform. Every component reads from the same contract.

**3. Context** — Constraints are extracted from documents. Prompts are versioned with integrity checks. Scope boundaries define what the factory can and cannot do.

**4. Agent Pipeline** — Autonomy is computed. Specialized agents are provisioned from the Prompt Registry. The pipeline adapts its gates based on task complexity.

**5. Control** — SDLC gates enforce quality on every commit. DORA metrics measure performance. Automatic rollback protects the codebase when the pipeline encounters repeated errors.

---

## What This Does Not Do

Scope boundaries matter. The factory:

→ Opens PRs but never merges them (you approve outcomes)
→ Writes code but never deploys to production
→ Accepts tasks with acceptance criteria but declines vague requests
→ Measures its own confidence per task (high / medium / low)

These boundaries are enforced programmatically, not by convention. A task requesting production deployment is declined before any agent starts.

---

## Research Foundations

Four peer-reviewed studies inform the design:

→ Code reading is the dominant time investment in AI-assisted development, not code writing (Zhang et al., 2026). The reconnaissance phase addresses this.

→ Two stable collaboration patterns emerge in production: high-confidence changes (60%) and complex decisions requiring human revision (40%) (Mao et al., 2025). The autonomy levels map to these patterns.

→ Autonomy is a deliberate design decision, separate from capability (Feng et al., 2025). The data contract carries an explicit autonomy level field.

→ Agent scaffolding matters as much as model capability (Wong et al., 2026). Structured governance produces higher quality output than a more capable model without governance.

---

## Getting Started

The pattern is open source: **github.com/truerocha/forward-deployed-engineer-pattern**

The repo includes 5 architecture planes with diagrams, 14 quality gate hooks, 31 BDD test scenarios, Terraform IaC for AWS cloud deployment, and 13 ADRs documenting every design decision.

Setup takes 15 minutes with three scripts.

---

## The Question

If you could measure your AI-assisted development with DORA metrics today — Lead Time, Change Failure Rate, Deployment Frequency, MTTR — what would the data tell you?

Most teams do not measure. The ones that do discover where AI amplifies their engineers and where it needs more structure.

I am curious: what level of autonomy would you give your AI agents for your team's most common task type? L2 (human at every step) or L5 (autonomous with metrics)?

---

## Author Bio

[Your name] — [Your title]. Building enterprise-grade AI engineering systems at the intersection of autonomous agents, SDLC governance, and organizational design.

---

## HASHTAGS

#AIEngineering #EngineeringLeadership #DevOps #GenAI #SoftwareDevelopment

---

## POSTING STRATEGY

1. **Publish as LinkedIn Article**
2. **Share with hook post** (see separate hook post draft with VidFlow + WAFR highlights)
3. **Post Tuesday or Wednesday** 8-10am
4. **Respond to every comment** in the first 2 hours
5. **Re-share after 7 days**: "The most counterintuitive insight from 6 months of AI-assisted development: giving agents MORE structure produces BETTER code. Scaffolding matters more than model capability."
