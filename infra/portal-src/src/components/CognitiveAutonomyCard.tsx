/**
 * CognitiveAutonomyCard — Dual-Axis Autonomy Visibility (ADR-029).
 *
 * Displays the cognitive autonomy decision for the factory:
 *   - Capability Depth: signal breakdown, squad composition, model tier
 *   - Delivery Authority: progress toward auto-merge, trust signals
 *   - Per-task depth comparison (recent tasks at different depths)
 *
 * Migrated to Cloudscape Design System:
 *   - Container + Header shell (Dashboard Item pattern)
 *   - ProgressBar for depth gauge and authority progress
 *   - Badge for squad tags
 *   - ColumnLayout + KeyValuePairs for metrics
 *   - StatusIndicator for status displays
 *
 * Personas: Staff (full), PM (authority progress), SWE (per-task), SRE (health)
 *
 * Ref: docs/adr/ADR-029-cognitive-autonomy-model.md
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

interface CapabilitySignal {
  name: string;
  value: number;
  max: number;
  contribution: string;
}

interface CognitiveAutonomyMetrics {
  capability_depth: number;
  squad_size: number;
  model_tier: string;
  verification_level: string;
  topology: string;
  include_adversarial: boolean;
  include_pr_reviewer: boolean;
  signals: CapabilitySignal[];
  authority_level: string;
  can_auto_merge: boolean;
  cfr_current: number;
  cfr_threshold: number;
  trust_score: number;
  trust_threshold: number;
  consecutive_successes: number;
  successes_needed: number;
  auto_merge_progress: number;
  recent_tasks: Array<{
    task_id: string;
    title: string;
    depth: number;
    squad_size: number;
    authority: string;
    status: string;
  }>;
}

interface CognitiveAutonomyCardProps {
  metrics?: CognitiveAutonomyMetrics | null;
}

function getDepthLabel(depth: number): string {
  if (depth >= 0.7) return 'Maximum';
  if (depth >= 0.5) return 'High';
  if (depth >= 0.3) return 'Medium';
  return 'Low';
}

function getDepthStatus(depth: number): 'success' | 'in-progress' | 'warning' | 'stopped' {
  if (depth >= 0.7) return 'success';
  if (depth >= 0.5) return 'in-progress';
  if (depth >= 0.3) return 'warning';
  return 'stopped';
}

function getAuthorityStatus(canAutoMerge: boolean, authority: string): 'success' | 'error' | 'warning' {
  if (canAutoMerge) return 'success';
  if (authority === 'blocked') return 'error';
  return 'warning';
}

function getAuthorityLabel(canAutoMerge: boolean, authority: string): string {
  if (canAutoMerge) return 'Auto-merge earned';
  if (authority === 'blocked') return 'Blocked';
  return 'Earning trust';
}

export const CognitiveAutonomyCard: React.FC<CognitiveAutonomyCardProps> = ({ metrics }) => {
  if (!metrics) {
    return (
      <Container header={<Header variant="h3">Cognitive Autonomy</Header>}>
        <Box textAlign="center" padding="l" color="text-status-inactive">
          <SpaceBetween size="s" alignItems="center">
            <Box variant="h3" color="text-status-inactive">🧠</Box>
            <StatusIndicator type="pending">Awaiting first task</StatusIndicator>
          </SpaceBetween>
        </Box>
      </Container>
    );
  }

  const authorityStatus = getAuthorityStatus(metrics.can_auto_merge, metrics.authority_level);
  const authorityLabel = getAuthorityLabel(metrics.can_auto_merge, metrics.authority_level);

  return (
    <Container
      header={
        <Header
          variant="h3"
          description="Dual-axis autonomy visibility"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Badge color="blue">{metrics.squad_size} agents</Badge>
              <Badge color={metrics.can_auto_merge ? 'green' : 'grey'}>
                {authorityLabel}
              </Badge>
            </SpaceBetween>
          }
        >
          Cognitive Autonomy
        </Header>
      }
      footer={
        <Box fontSize="body-s" color="text-body-secondary">
          ADR-029 • Depth: {getDepthLabel(metrics.capability_depth)} • Authority: {authorityLabel}
        </Box>
      }
    >
      <SpaceBetween size="m">
        {/* Capability Depth */}
        <ProgressBar
          value={metrics.capability_depth * 100}
          label="Capability Depth"
          description={`${getDepthLabel(metrics.capability_depth)} (${metrics.capability_depth.toFixed(2)})`}
          variant="standalone"
        />

        {/* Squad Tags */}
        <SpaceBetween direction="horizontal" size="xs">
          <Badge color="blue">{metrics.model_tier}</Badge>
          <Badge color="blue">{metrics.verification_level}</Badge>
          <Badge color="grey">{metrics.topology}</Badge>
          {metrics.include_adversarial && <Badge color="red">adversarial</Badge>}
          {metrics.include_pr_reviewer && <Badge color="green">pr-reviewer</Badge>}
        </SpaceBetween>

        {/* Signals */}
        {metrics.signals.length > 0 && (
          <div>
            <Box fontSize="body-s" color="text-body-secondary" margin={{ bottom: 'xs' }}>
              Capability Signals
            </Box>
            <SpaceBetween size="xs">
              {metrics.signals.slice(0, 4).map((signal) => (
                <div key={signal.name}>
                  <ProgressBar
                    value={(signal.value / signal.max) * 100}
                    label={signal.name}
                    additionalInfo={`${signal.value.toFixed(1)}/${signal.max} (${signal.contribution})`}
                    variant="standalone"
                  />
                </div>
              ))}
            </SpaceBetween>
          </div>
        )}

        {/* Authority Progress */}
        <div>
          <Box fontSize="body-s" color="text-body-secondary" margin={{ bottom: 'xs' }}>
            Delivery Authority
          </Box>
          <ProgressBar
            value={metrics.auto_merge_progress}
            label="Auto-merge progress"
            variant="standalone"
            status={metrics.authority_level === 'blocked' ? 'error' : undefined}
            additionalInfo={
              <StatusIndicator type={authorityStatus}>
                {authorityLabel}
              </StatusIndicator>
            }
          />
        </div>

        {/* Conditions Grid */}
        <ColumnLayout columns={3} variant="text-grid">
          <div>
            <Box variant="awsui-key-label">CFR</Box>
            <StatusIndicator type={metrics.cfr_current < metrics.cfr_threshold ? 'success' : 'error'}>
              {(metrics.cfr_current * 100).toFixed(0)}%
            </StatusIndicator>
          </div>
          <div>
            <Box variant="awsui-key-label">Trust</Box>
            <StatusIndicator type={metrics.trust_score >= metrics.trust_threshold ? 'success' : 'warning'}>
              {metrics.trust_score.toFixed(0)}%
            </StatusIndicator>
          </div>
          <div>
            <Box variant="awsui-key-label">Streak</Box>
            <StatusIndicator type={metrics.consecutive_successes >= metrics.successes_needed ? 'success' : 'warning'}>
              {metrics.consecutive_successes}/{metrics.successes_needed}
            </StatusIndicator>
          </div>
        </ColumnLayout>

        {/* Recent Tasks */}
        {metrics.recent_tasks.length > 0 && (
          <div>
            <Box fontSize="body-s" color="text-body-secondary" margin={{ bottom: 'xs' }}>
              Recent Task Depths
            </Box>
            <SpaceBetween size="xs">
              {metrics.recent_tasks.slice(0, 3).map((task) => (
                <div key={task.task_id}>
                  <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                    <StatusIndicator type={getDepthStatus(task.depth)} />
                    <Box fontSize="body-s">{task.title.slice(0, 30)}</Box>
                    <Box fontSize="body-s" variant="code">{task.depth.toFixed(2)}</Box>
                    <Badge color="grey">{task.squad_size}ag</Badge>
                  </SpaceBetween>
                </div>
              ))}
            </SpaceBetween>
          </div>
        )}
      </SpaceBetween>
    </Container>
  );
};
