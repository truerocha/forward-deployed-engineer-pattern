/**
 * ConductorPlanCard — Conductor Orchestration Plan (ADR-020).
 *
 * Displays the active workflow plan:
 *   - Topology type (sequential, parallel, tree, debate, recursive)
 *   - Step-by-step execution with status, model tier, access list
 *   - Rationale for the chosen topology
 *   - Footer metrics (progress, tokens, confidence threshold)
 *
 * Migrated to Cloudscape Design System:
 *   - Container + Header shell (Dashboard Item pattern)
 *   - Badge for topology type and model tiers
 *   - StatusIndicator for step status
 *   - ProgressBar for overall progress
 *   - SpaceBetween for step layout
 *
 * Ref: docs/adr/ADR-020-conductor-orchestration-pattern.md
 */

import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Badge from '@cloudscape-design/components/badge';
import ProgressBar from '@cloudscape-design/components/progress-bar';

interface WorkflowStep {
  step_index: number;
  subtask: string;
  agent_role: string;
  model_tier: string;
  access_list: (number | string)[];
  status?: 'pending' | 'running' | 'complete' | 'failed';
}

interface ConductorPlanCardProps {
  topology?: string | null;
  steps?: WorkflowStep[] | null;
  rationale?: string | null;
  recursive_depth?: number;
  confidence_threshold?: number;
  estimated_tokens?: number;
}

const TOPOLOGY_LABELS: Record<string, string> = {
  sequential: 'Sequential',
  parallel: 'Parallel',
  tree: 'Tree',
  debate: 'Debate',
  recursive: 'Recursive',
};

function getTopologyBadgeColor(topology: string): 'blue' | 'green' | 'red' | 'grey' {
  switch (topology) {
    case 'parallel': return 'green';
    case 'recursive': return 'red';
    case 'debate': return 'blue';
    default: return 'grey';
  }
}

function getTierBadgeColor(tier: string): 'blue' | 'green' | 'red' | 'grey' {
  switch (tier) {
    case 'fast': return 'green';
    case 'reasoning': return 'blue';
    case 'deep': return 'red';
    default: return 'grey';
  }
}

function getStepStatus(status?: string): 'success' | 'error' | 'in-progress' | 'pending' | 'stopped' {
  switch (status) {
    case 'complete': return 'success';
    case 'failed': return 'error';
    case 'running': return 'in-progress';
    case 'pending': return 'pending';
    default: return 'stopped';
  }
}

function formatAccessList(accessList: (number | string)[]): string {
  if (!accessList || accessList.length === 0) return 'independent';
  if (accessList.includes('all')) return 'full access';
  return `steps [${accessList.join(', ')}]`;
}

export const ConductorPlanCard: React.FC<ConductorPlanCardProps> = ({
  topology,
  steps,
  rationale,
  recursive_depth = 0,
  confidence_threshold = 0.7,
  estimated_tokens = 0,
}) => {
  if (!steps || steps.length === 0) {
    return (
      <Container header={<Header variant="h3">Conductor Plan</Header>}>
        <Box textAlign="center" padding="l" color="inherit">
          <StatusIndicator type="pending">No active plan</StatusIndicator>
        </Box>
      </Container>
    );
  }

  const completedSteps = steps.filter((s) => s.status === 'complete').length;
  const topoLabel = TOPOLOGY_LABELS[topology || 'sequential'] || 'Sequential';
  const progressPercent = steps.length > 0 ? (completedSteps / steps.length) * 100 : 0;

  return (
    <Container
      header={
        <Header
          variant="h3"
          description="Orchestration workflow plan"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Badge color={getTopologyBadgeColor(topology || 'sequential')}>
                {topoLabel}
              </Badge>
              {recursive_depth > 0 && (
                <Badge color="red">depth {recursive_depth}</Badge>
              )}
            </SpaceBetween>
          }
        >
          Conductor Plan
        </Header>
      }
      footer={
        <Box fontSize="body-s" color="text-body-secondary">
          {completedSteps}/{steps.length} steps • ~{estimated_tokens.toLocaleString()} tokens • threshold: {(confidence_threshold * 100).toFixed(0)}%
        </Box>
      }
    >
      <SpaceBetween size="m">
        {/* Overall Progress */}
        <ProgressBar
          value={progressPercent}
          label="Plan execution"
          additionalInfo={`${completedSteps}/${steps.length} steps complete`}
          variant="standalone"
        />

        {/* Steps */}
        <div style={{ maxHeight: '220px', overflowY: 'auto' }}>
          <SpaceBetween size="xs">
            {steps.map((step) => (
              <div key={step.step_index} style={{ padding: '8px', borderRadius: '8px', background: 'var(--color-background-layout-main, #f2f3f3)' }}>
                <SpaceBetween size="xxs">
                  <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                    <StatusIndicator type={getStepStatus(step.status)}>
                      {step.agent_role}
                    </StatusIndicator>
                    <Badge color={getTierBadgeColor(step.model_tier)}>
                      {step.model_tier}
                    </Badge>
                    <Box fontSize="body-s" color="text-body-secondary">
                      #{step.step_index}
                    </Box>
                  </SpaceBetween>
                  <Box fontSize="body-s">{step.subtask}</Box>
                  <Box fontSize="body-s" color="text-body-secondary">
                    Access: {formatAccessList(step.access_list)}
                  </Box>
                </SpaceBetween>
              </div>
            ))}
          </SpaceBetween>
        </div>

        {/* Rationale */}
        {rationale && (
          <Box fontSize="body-s" color="text-body-secondary">
            <Box variant="awsui-key-label">Rationale</Box>
            {rationale}
          </Box>
        )}
      </SpaceBetween>
    </Container>
  );
};
