/**
 * CapacityCard — Concurrency utilization, queue depth, and reaper health.
 *
 * Persona visibility: SRE (primary), Staff (secondary)
 * Data source: GET /status/capacity
 */
import { useEffect, useState } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import Badge from '@cloudscape-design/components/badge';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { CapacityData, fetchCapacity } from '../services/factoryService';

export default function CapacityCard() {
  const [data, setData] = useState<CapacityData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      const result = await fetchCapacity();
      setData(result);
      setLoading(false);
    };
    load();
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <Container header={<Header variant="h2">Capacity & Concurrency</Header>}>
        <Box textAlign="center" padding="l">Loading capacity data...</Box>
      </Container>
    );
  }

  if (!data) {
    return (
      <Container header={<Header variant="h2">Capacity & Concurrency</Header>}>
        <Box textAlign="center" padding="l">
          <StatusIndicator type="warning">Unable to fetch capacity data</StatusIndicator>
        </Box>
      </Container>
    );
  }

  const reaperStatusType = (status: string): 'success' | 'error' | 'warning' => {
    if (status === 'healthy') return 'success';
    if (status === 'never_invoked' || status === 'not_deployed') return 'error';
    return 'warning';
  };

  const reaperResultLabel = (result: string | null) => {
    if (!result) return 'No data';
    if (result === 'clean') return 'Clean';
    if (result === 'drift_corrected') return 'Drift corrected';
    if (result === 'tasks_reaped') return 'Tasks reaped';
    return result;
  };

  return (
    <Container
      header={
        <Header
          variant="h2"
          description="Concurrency slots, queue depth, and self-healing status"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Badge color={data.queue.total_queued > 0 ? 'red' : 'green'}>
                Queue: {data.queue.total_queued}
              </Badge>
              <Badge color={data.ecs.running_tasks > 0 ? 'blue' : 'grey'}>
                ECS: {data.ecs.running_tasks}
              </Badge>
            </SpaceBetween>
          }
        >
          Capacity & Concurrency
        </Header>
      }
    >
      <SpaceBetween size="l">
        {/* Concurrency per repo */}
        <div>
          <Box variant="h3" padding={{ bottom: 'xs' }}>Concurrency Slots</Box>
          <SpaceBetween size="s">
            {data.concurrency.repos.length === 0 ? (
              <Box color="text-status-inactive">No active repos</Box>
            ) : (
              data.concurrency.repos.map((repo) => (
                <div key={repo.repo}>
                  <ProgressBar
                    value={repo.utilization_pct}
                    label={repo.repo.split('/').pop() || repo.repo}
                    description={`${repo.active} / ${repo.max} slots`}
                    status={repo.saturated ? 'error' : 'in-progress'}
                    additionalInfo={repo.saturated ? 'Saturated — tasks queued' : undefined}
                  />
                </div>
              ))
            )}
          </SpaceBetween>
        </div>

        {/* Key metrics */}
        <ColumnLayout columns={3} variant="text-grid">
          <KeyValuePairs
            items={[
              { label: 'Total Active', value: String(data.concurrency.total_active) },
              { label: 'Max per Repo', value: String(data.concurrency.max_per_repo) },
            ]}
          />
          <KeyValuePairs
            items={[
              { label: 'Queued Tasks', value: String(data.queue.total_queued) },
              { label: 'ECS Running', value: String(data.ecs.running_tasks) },
            ]}
          />
          <KeyValuePairs
            items={[
              {
                label: 'Reaper',
                value: (
                  <StatusIndicator type={reaperStatusType(data.reaper.status)}>
                    {data.reaper.status}
                  </StatusIndicator>
                ),
              },
              { label: 'Last Heal', value: reaperResultLabel(data.reaper.last_result) },
            ]}
          />
        </ColumnLayout>

        {/* Queue details */}
        {data.queue.total_queued > 0 && (
          <div>
            <Box variant="h3" padding={{ bottom: 'xs' }}>Queued by Repo</Box>
            <SpaceBetween size="xs">
              {Object.entries(data.queue.by_repo).map(([repo, count]) => (
                <div key={repo}>
                  <Box>
                    <StatusIndicator type="warning">
                      {repo.split('/').pop()}: {(count as number)} task{(count as number) > 1 ? 's' : ''} waiting
                    </StatusIndicator>
                  </Box>
                </div>
              ))}
            </SpaceBetween>
          </div>
        )}
      </SpaceBetween>
    </Container>
  );
}
