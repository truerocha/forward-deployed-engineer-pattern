/**
 * ReadinessCard — SRE Dispatch Pipeline Readiness Card.
 *
 * Surfaces four operational health dimensions:
 *   1. Circuit breaker state (orchestrator routing health)
 *   2. Reaper healing actions (what it fixed and when)
 *   3. Agent readiness (can ECS tasks start?)
 *   4. Task flow health (where are tasks stuck?)
 *
 * Persona visibility: SRE (primary), Staff (secondary)
 * Data source: GET /status/sre-readiness
 * Refresh: 30s polling
 */
import { useEffect, useState } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import Badge from '@cloudscape-design/components/badge';
import SpaceBetween from '@cloudscape-design/components/space-between';
import BarChart from '@cloudscape-design/components/bar-chart';
import Table from '@cloudscape-design/components/table';
import { SreReadinessData, fetchSreReadiness } from '../services/factoryService';

export default function ReadinessCard() {
  const [data, setData] = useState<SreReadinessData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      const result = await fetchSreReadiness();
      setData(result);
      setLoading(false);
    };
    load();
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <Container header={<Header variant="h2">SRE Readiness</Header>}>
        <Box textAlign="center" padding="l">Loading readiness data...</Box>
      </Container>
    );
  }

  if (!data) {
    return (
      <Container header={<Header variant="h2">SRE Readiness</Header>}>
        <Box textAlign="center" padding="l">
          <StatusIndicator type="warning">Unable to fetch readiness data</StatusIndicator>
        </Box>
      </Container>
    );
  }

  const circuitColor = (state: string): 'success' | 'error' | 'warning' => {
    if (state === 'closed') return 'success';
    if (state === 'open') return 'error';
    return 'warning';
  };

  const circuitLabel = (state: string): string => {
    if (state === 'closed') return 'Closed (orchestrator active)';
    if (state === 'open') return 'Open (monolith fallback)';
    return 'Unknown';
  };

  const capacityStatus = (cap: string): 'success' | 'warning' | 'error' => {
    if (cap === 'available') return 'success';
    if (cap === 'near_limit') return 'warning';
    return 'error';
  };

  const formatMs = (ms: number): string => {
    if (ms === 0) return '—';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const formatRelativeTime = (iso: string | null): string => {
    if (!iso) return 'Never';
    try {
      const d = new Date(iso);
      const now = new Date();
      const diffMs = now.getTime() - d.getTime();
      const diffMin = Math.floor(diffMs / 60000);
      if (diffMin < 1) return 'Just now';
      if (diffMin < 60) return `${diffMin}m ago`;
      const diffHr = Math.floor(diffMin / 60);
      if (diffHr < 24) return `${diffHr}h ago`;
      return `${Math.floor(diffHr / 24)}d ago`;
    } catch {
      return iso || 'Unknown';
    }
  };

  // Build bar chart data for task status distribution
  const chartSeries = Object.entries(data.task_flow.status_distribution).map(([status, count]) => ({
    x: status,
    y: count as number,
  }));

  return (
    <Container
      header={
        <Header
          variant="h2"
          description="Dispatch pipeline operational readiness"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Badge color={data.circuit_breaker.state === 'closed' ? 'green' : 'red'}>
                Circuit: {data.circuit_breaker.state}
              </Badge>
              <Badge color={data.reaper_health.last_run ? 'blue' : 'grey'}>
                Reaper: {formatRelativeTime(data.reaper_health.last_run)}
              </Badge>
            </SpaceBetween>
          }
        >
          SRE Readiness
        </Header>
      }
    >
      <SpaceBetween size="l">
        {/* ── Circuit Breaker ─────────────────────────────────────────── */}
        <div>
          <Box variant="h3" padding={{ bottom: 'xs' }}>Circuit Breaker</Box>
          <ColumnLayout columns={2} variant="text-grid">
            <KeyValuePairs
              items={[
                {
                  label: 'State',
                  value: (
                    <StatusIndicator type={circuitColor(data.circuit_breaker.state)}>
                      {circuitLabel(data.circuit_breaker.state)}
                    </StatusIndicator>
                  ),
                },
                { label: 'Changed by', value: data.circuit_breaker.changed_by },
              ]}
            />
            <KeyValuePairs
              items={[
                { label: 'Last change', value: formatRelativeTime(data.circuit_breaker.last_change) },
                { label: 'Blast radius', value: `${data.circuit_breaker.blast_radius} tasks max` },
              ]}
            />
          </ColumnLayout>
        </div>

        {/* ── Reaper Health ───────────────────────────────────────────── */}
        <div>
          <Box variant="h3" padding={{ bottom: 'xs' }}>Reaper Health</Box>
          <ColumnLayout columns={3} variant="text-grid">
            <KeyValuePairs
              items={[
                { label: 'Last run', value: formatRelativeTime(data.reaper_health.last_run) },
                { label: 'Assessment', value: (
                  <StatusIndicator
                    type={data.reaper_health.orchestrator_assessment === 'healthy' ? 'success' :
                          data.reaper_health.orchestrator_assessment === 'degraded' ? 'warning' : 'error'}
                  >
                    {data.reaper_health.orchestrator_assessment}
                  </StatusIndicator>
                )},
              ]}
            />
            <KeyValuePairs
              items={[
                { label: 'Tasks reaped', value: String(data.reaper_health.tasks_reaped) },
                { label: 'Re-dispatched', value: String(data.reaper_health.tasks_redispatched) },
              ]}
            />
            <KeyValuePairs
              items={[
                { label: 'Counter fixes', value: String(data.reaper_health.counter_drift_corrections) },
              ]}
            />
          </ColumnLayout>

          {data.reaper_health.actions.length > 0 && (
            <Box padding={{ top: 's' }}>
              <Table
                variant="embedded"
                columnDefinitions={[
                  { id: 'ts', header: 'Time', cell: (item: { ts: string; action: string; detail: string }) => formatRelativeTime(item.ts), width: 100 },
                  { id: 'action', header: 'Action', cell: (item: { ts: string; action: string; detail: string }) => (
                    <Badge color={item.action === 'reaped' ? 'red' : item.action === 'redispatched' ? 'blue' : 'grey'}>
                      {item.action}
                    </Badge>
                  ), width: 130 },
                  { id: 'detail', header: 'Detail', cell: (item: { ts: string; action: string; detail: string }) => item.detail },
                ]}
                items={data.reaper_health.actions.slice(-5)}
                empty="No recent healing actions"
              />
            </Box>
          )}
        </div>

        {/* ── Agent Readiness ─────────────────────────────────────────── */}
        <div>
          <Box variant="h3" padding={{ bottom: 'xs' }}>Agent Readiness</Box>
          <ColumnLayout columns={2} variant="text-grid">
            <KeyValuePairs
              items={[
                { label: 'Task def', value: data.agent_readiness.task_def_version || 'Unknown' },
                { label: 'ECR pushed', value: formatRelativeTime(data.agent_readiness.ecr_last_pushed) },
              ]}
            />
            <KeyValuePairs
              items={[
                {
                  label: 'Fargate capacity',
                  value: (
                    <StatusIndicator type={capacityStatus(data.agent_readiness.fargate_capacity)}>
                      {data.agent_readiness.fargate_capacity} ({data.agent_readiness.running_count ?? 0} running)
                    </StatusIndicator>
                  ),
                },
              ]}
            />
          </ColumnLayout>

          {data.agent_readiness.recent_exit_codes.length > 0 && (
            <Box padding={{ top: 's' }}>
              <Box variant="small" color="text-status-inactive" padding={{ bottom: 'xxs' }}>Recent exit codes</Box>
              <SpaceBetween direction="horizontal" size="xs">
                {data.agent_readiness.recent_exit_codes.map((ec, i) => (
                  <span key={i}>
                    <Badge color={ec.exit_code === 0 ? 'green' : 'red'}>
                      {ec.task_arn}: exit {ec.exit_code}
                    </Badge>
                  </span>
                ))}
              </SpaceBetween>
            </Box>
          )}
        </div>

        {/* ── Task Flow Health ────────────────────────────────────────── */}
        <div>
          <Box variant="h3" padding={{ bottom: 'xs' }}>Task Flow Health</Box>
          <ColumnLayout columns={3} variant="text-grid">
            <KeyValuePairs
              items={[
                { label: 'Avg ingested time', value: formatMs(data.task_flow.avg_ingested_duration_ms) },
              ]}
            />
            <KeyValuePairs
              items={[
                { label: 'Dispatch→Start p50', value: formatMs(data.task_flow.dispatch_to_start_p50_ms) },
              ]}
            />
            <KeyValuePairs
              items={[
                { label: 'Dispatch→Start p95', value: formatMs(data.task_flow.dispatch_to_start_p95_ms) },
              ]}
            />
          </ColumnLayout>

          {chartSeries.length > 0 && (
            <Box padding={{ top: 's' }}>
              <BarChart
                series={[
                  {
                    title: 'Tasks',
                    type: 'bar',
                    data: chartSeries,
                  },
                ]}
                xDomain={Object.keys(data.task_flow.status_distribution)}
                yDomain={[0, Math.max(...(Object.values(data.task_flow.status_distribution) as number[]), 1)]}
                xTitle="Status"
                yTitle="Count"
                height={150}
                hideFilter
                hideLegend
                empty="No task data"
                noMatch="No matching data"
              />
            </Box>
          )}
        </div>
      </SpaceBetween>
    </Container>
  );
}
