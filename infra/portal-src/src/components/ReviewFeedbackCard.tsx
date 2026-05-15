/**
 * ReviewFeedbackCard — ICRL Review Feedback Loop Observability.
 *
 * Displays the closed-loop learning metrics from human PR reviews:
 *   - Review classification breakdown (full_rework / partial_fix / approval)
 *   - Rework cycle count and circuit breaker status
 *   - ICRL episode count and pattern digest availability
 *   - Verification gate pass rate (pre-PR deterministic checks)
 *   - Conditional autonomy adjustments from review feedback
 *
 * Migrated to Cloudscape Design System:
 *   - Container + Header shell (Dashboard Item pattern)
 *   - Alert for circuit breaker trips
 *   - Badge for classification counts
 *   - ProgressBar for verification gate pass rate
 *   - KeyValuePairs for metric rows
 *   - StatusIndicator for status displays
 *
 * Personas:
 *   - Staff Engineer: Full view (all metrics + ICRL episodes + autonomy adjustments)
 *   - SWE: Rework status, verification gate results, episode learning context
 *   - PM: Rework rate as DORA fifth metric, trust trend from reviews
 *   - SRE: Circuit breaker status, verification gate health
 *
 * Ref: docs/adr/ADR-027-review-feedback-loop.md (V2: ICRL Enhancement)
 */

import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import Badge from '@cloudscape-design/components/badge';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Alert from '@cloudscape-design/components/alert';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';

// ─── Types ──────────────────────────────────────────────────────

interface ReviewFeedbackMetrics {
  total_reviews: number;
  full_rework_count: number;
  partial_fix_count: number;
  approval_count: number;
  informational_count: number;
  active_rework_tasks: number;
  circuit_breaker_trips: number;
  avg_rework_attempts: number;
  icrl_episode_count: number;
  pattern_digest_available: boolean;
  last_episode_timestamp: string;
  verification_pass_rate: number;
  avg_verification_iterations: number;
  verification_level: string;
  autonomy_reductions: number;
  autonomy_increases: number;
  current_autonomy_level: number;
}

interface ReviewFeedbackCardProps {
  metrics?: ReviewFeedbackMetrics | null;
}

// ─── Helpers ────────────────────────────────────────────────────

function getReworkRateStatus(rate: number): 'success' | 'warning' | 'error' {
  if (rate <= 10) return 'success';
  if (rate <= 25) return 'warning';
  return 'error';
}

function getVerificationStatus(level: string): 'success' | 'warning' | 'error' {
  if (level === 'full') return 'success';
  if (level === 'bypass') return 'error';
  return 'warning';
}

// ─── Main Component ─────────────────────────────────────────────

export const ReviewFeedbackCard: React.FC<ReviewFeedbackCardProps> = ({ metrics }) => {
  if (!metrics) {
    return (
      <Container header={<Header variant="h3">ICRL Feedback Loop</Header>}>
        <Box textAlign="center" padding="l" color="inherit">
          <StatusIndicator type="pending">No ICRL data yet</StatusIndicator>
        </Box>
      </Container>
    );
  }

  const reworkRate = metrics.total_reviews > 0
    ? ((metrics.full_rework_count / metrics.total_reviews) * 100)
    : 0;

  const hasCircuitBreaker = metrics.circuit_breaker_trips > 0;

  return (
    <Container
      header={
        <Header
          variant="h3"
          description="Closed-loop learning from human PR reviews"
          actions={
            <Badge color={metrics.pattern_digest_available ? 'green' : 'grey'}>
              {metrics.icrl_episode_count} episodes
            </Badge>
          }
        >
          ICRL Feedback Loop
        </Header>
      }
      footer={
        <Box fontSize="body-s" color="text-body-secondary">
          ICRL closed-loop learning • {metrics.pattern_digest_available ? 'Pattern digest active' : 'Accumulating episodes'}
        </Box>
      }
    >
      <SpaceBetween size="m">
        {/* Circuit Breaker Alert */}
        {hasCircuitBreaker && (
          <Alert type="error" statusIconAriaLabel="Error">
            Circuit breaker tripped ({metrics.circuit_breaker_trips}x) — Staff Engineer review required
          </Alert>
        )}

        {/* Classification Breakdown */}
        <SpaceBetween direction="horizontal" size="xs">
          <Badge color="red">{metrics.full_rework_count} Rework</Badge>
          <Badge color="blue">{metrics.partial_fix_count} Fix</Badge>
          <Badge color="green">{metrics.approval_count} Approved</Badge>
        </SpaceBetween>

        {/* Verification Gate */}
        <ProgressBar
          value={metrics.verification_pass_rate}
          label="Verification Gate Pass Rate"
          variant="standalone"
          status={metrics.verification_pass_rate < 50 ? 'error' : undefined}
          additionalInfo={`${metrics.verification_pass_rate.toFixed(0)}%`}
        />

        {/* Key Metrics */}
        <KeyValuePairs
          columns={2}
          items={[
            {
              label: 'Rework Rate (5th DORA)',
              value: (
                <StatusIndicator type={getReworkRateStatus(reworkRate)}>
                  {reworkRate.toFixed(1)}%
                </StatusIndicator>
              ),
            },
            {
              label: 'Avg Verification Iterations',
              value: (
                <StatusIndicator type={metrics.avg_verification_iterations <= 1.5 ? 'success' : 'warning'}>
                  {metrics.avg_verification_iterations.toFixed(1)}
                </StatusIndicator>
              ),
            },
            {
              label: 'Autonomy Level',
              value: (
                <StatusIndicator type={metrics.current_autonomy_level >= 3 ? 'success' : 'warning'}>
                  L{metrics.current_autonomy_level}
                </StatusIndicator>
              ),
            },
            {
              label: 'Verification Level',
              value: (
                <StatusIndicator type={getVerificationStatus(metrics.verification_level)}>
                  {metrics.verification_level}
                </StatusIndicator>
              ),
            },
          ]}
        />

        {/* Autonomy Adjustments */}
        <ColumnLayout columns={2} variant="text-grid">
          <div>
            <Box variant="awsui-key-label">Autonomy Reductions (7d)</Box>
            <StatusIndicator type={metrics.autonomy_reductions > 0 ? 'error' : 'success'}>
              -{metrics.autonomy_reductions}
            </StatusIndicator>
          </div>
          <div>
            <Box variant="awsui-key-label">Autonomy Increases (7d)</Box>
            <StatusIndicator type={metrics.autonomy_increases > 0 ? 'success' : 'stopped'}>
              +{metrics.autonomy_increases}
            </StatusIndicator>
          </div>
        </ColumnLayout>
      </SpaceBetween>
    </Container>
  );
};
