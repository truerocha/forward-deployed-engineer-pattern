/**
 * A2ASquadCommunicationCard — AI Squad inter-agent development flow visualization.
 *
 * Shows the intentional communication between AI Squad agents during the
 * software development lifecycle via the A2A protocol:
 *
 *   SPEC → RECON (code mapping) → IMPLEMENT (code generation) → REVIEW (code review)
 *         → [FIX → RE-REVIEW] → MERGE-READY
 *
 * Contract semantics in the development context:
 *   - ConteudoBruto = Reconnaissance output: modules mapped, call graph edges,
 *     dependency analysis, spec constraints extracted, affected files identified
 *   - RelatorioFinal = Implementation output: code artifacts generated, tests written,
 *     files modified, lines added/modified, language breakdown
 *   - FeedbackRevisao = Code Review output: bugs found, security issues, SOLID violations,
 *     test coverage gaps, suggested refactoring, approval/rejection verdict
 *
 * The feedback loop represents the real code review cycle:
 *   Reviewer finds issues → Developer fixes → Reviewer re-reviews (max 3 rounds)
 *
 * Persona: Architect, Engineer, Staff Engineer, Tech Lead
 * Data Source: DynamoDB workflow state (ContextoWorkflow) + OTel span events
 *
 * Well-Architected Alignment:
 *   - OPS 6: Observable inter-agent development collaboration
 *   - REL 2: Code review loop visibility for quality assurance
 *   - COST 2: Rework cycles visible for engineering efficiency
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Badge from '@cloudscape-design/components/badge';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import ExpandableSection from '@cloudscape-design/components/expandable-section';

// ─── Types (mapped to real development flow) ────────────────────────────────

/** Reconnaissance output — what the code-context agent discovered */
interface ReconOutput {
  modulesScanned: number;
  edgesDiscovered: number;
  affectedFiles: string[];
  specConstraints: string[];
  dependencyDepth: number;
  confidence: number;
}

/** Implementation output — what the developer agent produced */
interface ImplementOutput {
  artifactsGenerated: number;
  filesModified: string[];
  linesAdded: number;
  linesModified: number;
  testsWritten: number;
  languages: string[];
}

/** Code Review output — what the adversarial/reviewer agent found */
interface ReviewOutput {
  verdict: 'APPROVED' | 'NEEDS_REVISION' | 'REJECTED';
  qualityScore: number;
  bugsFound: number;
  securityIssues: number;
  solidViolations: number;
  testCoverageGaps: number;
  suggestions: string[];
}

/** A single message in the development flow */
interface DevFlowMessage {
  id: string;
  phase: 'recon' | 'implement' | 'review' | 'fix' | 're-review';
  from: string;
  to: string;
  timestamp: string;
  durationMs: number;
  status: 'completed' | 'failed' | 'in-progress';
  attempt: number;
  /** Phase-specific payload summary */
  recon?: ReconOutput;
  implement?: ImplementOutput;
  review?: ReviewOutput;
}

/** A complete review cycle (review → fix → re-review) */
interface ReviewCycle {
  attempt: number;
  verdict: 'APPROVED' | 'NEEDS_REVISION' | 'REJECTED';
  qualityScore: number;
  issuesFound: number;
  issuesFixed: number;
  fixDurationMs: number;
  reviewDurationMs: number;
}

interface A2ASquadCommunicationCardProps {
  messages?: DevFlowMessage[];
  reviewCycles?: ReviewCycle[];
  workflowId?: string;
  currentPhase?: string;
  specTitle?: string;
  totalDurationMs?: number;
  approvedAtAttempt?: number;
  maxAttempts?: number;
}

// ─── Constants ──────────────────────────────────────────────────────────────

const PHASE_CONFIG: Record<string, { label: string; color: string; icon: string }> = {
  recon: { label: 'Reconnaissance', color: '#037f0c', icon: '🔍' },
  implement: { label: 'Implementation', color: '#0972d3', icon: '⚙️' },
  review: { label: 'Code Review', color: '#d91515', icon: '🔎' },
  fix: { label: 'Fix (Rework)', color: '#ff9900', icon: '🔧' },
  're-review': { label: 'Re-Review', color: '#d91515', icon: '🔄' },
};

const AGENT_ROLES: Record<string, { label: string; badge: 'blue' | 'green' | 'red' | 'grey' }> = {
  'swe-code-context-agent': { label: 'Code Context', badge: 'green' },
  'swe-developer-agent': { label: 'Developer', badge: 'blue' },
  'swe-adversarial-agent': { label: 'Reviewer', badge: 'red' },
  'fde-pr-reviewer-agent': { label: 'PR Reviewer', badge: 'red' },
  'swe-architect-agent': { label: 'Architect', badge: 'grey' },
  'fde-tech-lead-agent': { label: 'Tech Lead', badge: 'grey' },
  Orchestrator: { label: 'Orchestrator', badge: 'grey' },
};

const VERDICT_STATUS: Record<string, 'success' | 'warning' | 'error'> = {
  APPROVED: 'success',
  NEEDS_REVISION: 'warning',
  REJECTED: 'error',
};

// ─── Component ──────────────────────────────────────────────────────────────

export const A2ASquadCommunicationCard: React.FC<A2ASquadCommunicationCardProps> = ({
  messages = [],
  reviewCycles = [],
  workflowId = '',
  currentPhase = '',
  specTitle = '',
  totalDurationMs = 0,
  approvedAtAttempt = 0,
  maxAttempts = 3,
}) => {
  const hasData = messages.length > 0 || reviewCycles.length > 0;

  return (
    <Container
      header={
        <Header
          variant="h3"
          description={specTitle || 'AI Squad development flow — spec to merge-ready'}
          info={
            <SpaceBetween direction="horizontal" size="xs">
              {currentPhase && (
                <Badge color="blue">
                  {PHASE_CONFIG[currentPhase]?.icon} {PHASE_CONFIG[currentPhase]?.label || currentPhase}
                </Badge>
              )}
              {workflowId && <Badge color="grey">{workflowId.slice(-8)}</Badge>}
            </SpaceBetween>
          }
        >
          Squad Communication
        </Header>
      }
    >
      {!hasData ? (
        <Box textAlign="center" padding="xl" color="text-status-inactive">
          No active squad communication. Messages appear when the AI Squad executes a task.
        </Box>
      ) : (
        <SpaceBetween size="l">
          {/* ─── Development Flow Pipeline ────────────────────────── */}
          <Box textAlign="center" padding="xs">
            <span style={{ fontFamily: 'monospace', fontSize: '13px', color: '#5f6b7a' }}>
              SPEC → 🔍 RECON → ⚙️ IMPLEMENT → 🔎 REVIEW → [🔧 FIX → 🔄 RE-REVIEW] → ✅ MERGE-READY
            </span>
          </Box>

          {/* ─── Message Sequence (Development Timeline) ──────────── */}
          <SpaceBetween size="xs">
            <Box variant="h4">Development Timeline</Box>
            <div style={{ borderLeft: '3px solid #0972d3', paddingLeft: '16px' }}>
              {messages.map((msg) => {
                const phaseConf = PHASE_CONFIG[msg.phase] || PHASE_CONFIG.implement;
                const fromRole = AGENT_ROLES[msg.from] || { label: msg.from, badge: 'grey' as const };
                const toRole = AGENT_ROLES[msg.to] || { label: msg.to, badge: 'grey' as const };

                return (
                  <div
                    key={msg.id}
                    style={{
                      marginBottom: '12px',
                      padding: '10px 14px',
                      borderRadius: '6px',
                      backgroundColor: msg.phase === 'fix'
                        ? 'var(--color-background-status-warning, #fff8e1)'
                        : 'var(--color-background-layout-main, #fafafa)',
                      borderLeft: `4px solid ${phaseConf.color}`,
                    }}
                  >
                    {/* Header: phase + agents + timing */}
                    <SpaceBetween direction="horizontal" size="xs">
                      <Box variant="small" color="text-body-secondary">{msg.timestamp}</Box>
                      <span style={{ fontSize: '14px' }}>{phaseConf.icon}</span>
                      <Badge color={fromRole.badge}>{fromRole.label}</Badge>
                      <span style={{ color: '#5f6b7a' }}>→</span>
                      <Badge color={toRole.badge}>{toRole.label}</Badge>
                      <Box variant="small" color="text-body-secondary">{(msg.durationMs / 1000).toFixed(1)}s</Box>
                      {msg.attempt > 1 && <Badge color="red">attempt #{msg.attempt}</Badge>}
                      <StatusIndicator
                        type={msg.status === 'completed' ? 'success' : msg.status === 'failed' ? 'error' : 'in-progress'}
                      >
                        {msg.status}
                      </StatusIndicator>
                    </SpaceBetween>

                    {/* Phase-specific payload summary */}
                    {msg.recon && (
                      <Box variant="small" padding={{ top: 'xxs' }} color="text-body-secondary">
                        Scanned {msg.recon.modulesScanned} modules • {msg.recon.edgesDiscovered} edges
                        • {msg.recon.affectedFiles.length} affected files
                        • confidence {(msg.recon.confidence * 100).toFixed(0)}%
                      </Box>
                    )}
                    {msg.implement && (
                      <Box variant="small" padding={{ top: 'xxs' }} color="text-body-secondary">
                        {msg.implement.artifactsGenerated} artifacts • +{msg.implement.linesAdded} lines
                        • ~{msg.implement.linesModified} modified
                        • {msg.implement.testsWritten} tests
                        • [{msg.implement.languages.join(', ')}]
                      </Box>
                    )}
                    {msg.review && (
                      <Box variant="small" padding={{ top: 'xxs' }} color="text-body-secondary">
                        <StatusIndicator type={VERDICT_STATUS[msg.review.verdict]}>
                          {msg.review.verdict}
                        </StatusIndicator>
                        {' '}score {(msg.review.qualityScore * 100).toFixed(0)}%
                        • {msg.review.bugsFound} bugs
                        • {msg.review.securityIssues} security
                        • {msg.review.solidViolations} SOLID
                        • {msg.review.testCoverageGaps} coverage gaps
                      </Box>
                    )}
                  </div>
                );
              })}
            </div>
          </SpaceBetween>

          {/* ─── Code Review Feedback Loop ────────────────────────── */}
          {reviewCycles.length > 0 && (
            <SpaceBetween size="xs">
              <Box variant="h4">
                Code Review Loop ({reviewCycles.length}/{maxAttempts} rounds)
              </Box>
              <ColumnLayout columns={Math.min(reviewCycles.length, 3)} variant="text-grid">
                {reviewCycles.map((cycle) => (
                  <div key={cycle.attempt} style={{
                    padding: '12px',
                    borderRadius: '6px',
                    border: cycle.verdict === 'APPROVED'
                      ? '2px solid #037f0c'
                      : '1px solid var(--color-border-divider-default, #e9ebed)',
                  }}>
                    <SpaceBetween size="xxs">
                      <Box variant="small" fontWeight="bold">
                        Round {cycle.attempt}
                      </Box>
                      <StatusIndicator type={VERDICT_STATUS[cycle.verdict] || 'pending'}>
                        {cycle.verdict}
                      </StatusIndicator>
                      <ProgressBar
                        value={cycle.qualityScore * 100}
                        label="Code Quality"
                        description={`${cycle.issuesFound} found → ${cycle.issuesFixed} fixed`}
                        resultText={`${(cycle.qualityScore * 100).toFixed(0)}%`}
                      />
                      <KeyValuePairs
                        columns={2}
                        items={[
                          { label: 'Review', value: `${(cycle.reviewDurationMs / 1000).toFixed(1)}s` },
                          { label: 'Fix', value: cycle.fixDurationMs > 0 ? `${(cycle.fixDurationMs / 1000).toFixed(1)}s` : '—' },
                        ]}
                      />
                    </SpaceBetween>
                  </div>
                ))}
              </ColumnLayout>
            </SpaceBetween>
          )}

          {/* ─── Affected Files (from Recon) ─────────────────────── */}
          {messages.some(m => m.recon && m.recon.affectedFiles.length > 0) && (
            <ExpandableSection headerText="Affected Files (from Reconnaissance)" variant="footer">
              <Box padding="xs">
                <pre style={{
                  fontSize: '12px',
                  fontFamily: 'monospace',
                  backgroundColor: 'var(--color-background-code-default, #f4f4f4)',
                  padding: '8px',
                  borderRadius: '4px',
                  maxHeight: '150px',
                  overflowY: 'auto',
                }}>
                  {messages
                    .filter(m => m.recon)
                    .flatMap(m => m.recon!.affectedFiles)
                    .join('\n')}
                </pre>
              </Box>
            </ExpandableSection>
          )}

          {/* ─── Review Suggestions (from last review) ───────────── */}
          {messages.some(m => m.review && m.review.suggestions.length > 0) && (
            <ExpandableSection headerText="Reviewer Suggestions (latest)" variant="footer">
              <Box padding="xs">
                <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '13px' }}>
                  {messages
                    .filter(m => m.review)
                    .slice(-1)
                    .flatMap(m => m.review!.suggestions)
                    .map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              </Box>
            </ExpandableSection>
          )}

          {/* ─── Summary Metrics ──────────────────────────────────── */}
          <KeyValuePairs
            columns={4}
            items={[
              { label: 'Total Duration', value: `${(totalDurationMs / 1000).toFixed(1)}s` },
              { label: 'Phases Completed', value: String(messages.filter(m => m.status === 'completed').length) },
              { label: 'Approved At', value: approvedAtAttempt > 0 ? `Round ${approvedAtAttempt}` : 'Pending' },
              { label: 'Rework Rounds', value: String(reviewCycles.filter(c => c.verdict === 'NEEDS_REVISION').length) },
            ]}
          />
        </SpaceBetween>
      )}
    </Container>
  );
};
