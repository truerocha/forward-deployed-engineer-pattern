/**
 * HistoryView — Historical Pipeline Activity with paginated access.
 *
 * Provides personas with visibility into past task execution, reasoning,
 * and activities performed by the AI Squad. Supports filtering by time
 * window, status, and repository.
 *
 * Data sources:
 *   - DynamoDB task_queue (up to 90 days via TTL)
 *   - S3 archived data (beyond 90 days)
 */
import React, { useState, useEffect, useCallback } from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Table, { TableProps } from '@cloudscape-design/components/table';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Link from '@cloudscape-design/components/link';
import Box from '@cloudscape-design/components/box';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Pagination from '@cloudscape-design/components/pagination';
import Select from '@cloudscape-design/components/select';
import Badge from '@cloudscape-design/components/badge';
import SegmentedControl from '@cloudscape-design/components/segmented-control';

import { fetchHistory, HistoryData, HistoryTask } from '../services/factoryService';

interface HistoryViewProps {
  repoFilter?: string;
}

function getHistoryStatus(status: string): { type: 'success' | 'error' | 'warning' | 'stopped' | 'pending'; text: string } {
  switch (status) {
    case 'completed': return { type: 'success', text: 'Completed' };
    case 'failed': return { type: 'error', text: 'Failed' };
    case 'completed_no_delivery': return { type: 'warning', text: 'No Delivery' };
    case 'dead_letter': return { type: 'error', text: 'Dead Letter' };
    default: return { type: 'stopped', text: status || 'Unknown' };
  }
}

function formatDuration(ms: number): string {
  if (!ms) return '—';
  if (ms < 60000) return `${Math.round(ms / 1000)}s`;
  if (ms < 3600000) return `${Math.round(ms / 60000)}m`;
  return `${(ms / 3600000).toFixed(1)}h`;
}

function formatDate(iso: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

const columnDefinitions: TableProps.ColumnDefinition<HistoryTask>[] = [
  {
    id: 'title',
    header: 'Task',
    cell: (item) => <Box fontWeight="bold">{item.title}</Box>,
    sortingField: 'title',
    isRowHeader: true,
    minWidth: 200,
  },
  {
    id: 'status',
    header: 'Status',
    cell: (item) => {
      const s = getHistoryStatus(item.status);
      return <StatusIndicator type={s.type}>{s.text}</StatusIndicator>;
    },
    sortingField: 'status',
    minWidth: 120,
  },
  {
    id: 'repo',
    header: 'Repository',
    cell: (item) => <Box variant="code">{item.repo || '—'}</Box>,
    sortingField: 'repo',
    minWidth: 120,
  },
  {
    id: 'duration',
    header: 'Duration',
    cell: (item) => <Box>{formatDuration(item.duration_ms)}</Box>,
    minWidth: 80,
  },
  {
    id: 'created_at',
    header: 'Started',
    cell: (item) => <Box fontSize="body-s">{formatDate(item.created_at)}</Box>,
    sortingField: 'created_at',
    minWidth: 140,
  },
  {
    id: 'reasoning',
    header: 'Reasoning',
    cell: (item) => (
      item.has_reasoning
        ? <Badge color="blue">{item.event_count} events</Badge>
        : <Box color="text-body-secondary">—</Box>
    ),
    minWidth: 100,
  },
  {
    id: 'links',
    header: 'Links',
    cell: (item) => (
      <SpaceBetween direction="horizontal" size="xs">
        {item.pr_url && <Link href={item.pr_url} external>PR</Link>}
        {item.issue_url && <Link href={item.issue_url} external>Issue</Link>}
      </SpaceBetween>
    ),
    minWidth: 100,
  },
];

export const HistoryView: React.FC<HistoryViewProps> = ({ repoFilter }) => {
  const [data, setData] = useState<HistoryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [daysBack, setDaysBack] = useState('30');
  const [statusFilter, setStatusFilter] = useState('');
  const [pageTokens, setPageTokens] = useState<Record<number, string | undefined>>({ 1: undefined });

  const loadData = useCallback(async (token?: string) => {
    setLoading(true);
    const result = await fetchHistory({
      days: Number(daysBack),
      pageSize,
      nextToken: token,
      repo: repoFilter,
      status: statusFilter || undefined,
    });
    setData(result);
    setLoading(false);

    // Store next page token
    if (result?.pagination?.next_token) {
      setPageTokens(prev => ({ ...prev, [currentPage + 1]: result.pagination.next_token! }));
    }
  }, [daysBack, pageSize, repoFilter, statusFilter, currentPage]);

  useEffect(() => {
    loadData();
  }, [daysBack, pageSize, repoFilter, statusFilter]);

  const handlePageChange = useCallback((detail: { currentPageIndex: number }) => {
    const newPage = detail.currentPageIndex;
    setCurrentPage(newPage);
    loadData(pageTokens[newPage]);
  }, [pageTokens, loadData]);

  const handleDaysChange = useCallback((value: string) => {
    setDaysBack(value);
    setCurrentPage(1);
    setPageTokens({ 1: undefined });
  }, []);

  const handleStatusChange = useCallback((value: string) => {
    setStatusFilter(value);
    setCurrentPage(1);
    setPageTokens({ 1: undefined });
  }, []);

  const totalPages = data?.pagination
    ? Math.ceil(data.pagination.total_count / data.pagination.page_size) || 1
    : 1;

  return (
    <SpaceBetween size="l">
      {/* Period aggregation summary */}
      {data?.periods && (
        <Container
          header={<Header variant="h3" description="Aggregated activity across time periods">Activity Summary</Header>}
        >
          <ColumnLayout columns={3} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">Last 7 Days</Box>
              <SpaceBetween direction="horizontal" size="xs">
                <StatusIndicator type="success">{data.periods.last_7d.completed} completed</StatusIndicator>
                <StatusIndicator type="error">{data.periods.last_7d.failed} failed</StatusIndicator>
                <Box color="text-body-secondary">({data.periods.last_7d.total} total)</Box>
              </SpaceBetween>
            </div>
            <div>
              <Box variant="awsui-key-label">Last 30 Days</Box>
              <SpaceBetween direction="horizontal" size="xs">
                <StatusIndicator type="success">{data.periods.last_30d.completed} completed</StatusIndicator>
                <StatusIndicator type="error">{data.periods.last_30d.failed} failed</StatusIndicator>
                <Box color="text-body-secondary">({data.periods.last_30d.total} total)</Box>
              </SpaceBetween>
            </div>
            <div>
              <Box variant="awsui-key-label">Last 90 Days</Box>
              <SpaceBetween direction="horizontal" size="xs">
                <StatusIndicator type="success">{data.periods.last_90d.completed} completed</StatusIndicator>
                <StatusIndicator type="error">{data.periods.last_90d.failed} failed</StatusIndicator>
                <Box color="text-body-secondary">({data.periods.last_90d.total} total)</Box>
              </SpaceBetween>
            </div>
          </ColumnLayout>
        </Container>
      )}

      {/* Filters */}
      <Container>
        <SpaceBetween direction="horizontal" size="l">
          <div>
            <Box variant="awsui-key-label">Time Window</Box>
            <SegmentedControl
              selectedId={daysBack}
              onChange={({ detail }) => handleDaysChange(detail.selectedId)}
              options={[
                { id: '7', text: '7 days' },
                { id: '30', text: '30 days' },
                { id: '60', text: '60 days' },
                { id: '90', text: '90 days' },
              ]}
            />
          </div>
          <div>
            <Box variant="awsui-key-label">Status</Box>
            <Select
              selectedOption={
                statusFilter
                  ? { label: statusFilter, value: statusFilter }
                  : { label: 'All statuses', value: '' }
              }
              onChange={({ detail }) => handleStatusChange(detail.selectedOption.value || '')}
              options={[
                { label: 'All statuses', value: '' },
                { label: 'Completed', value: 'COMPLETED' },
                { label: 'Failed', value: 'FAILED' },
                { label: 'Dead Letter', value: 'DEAD_LETTER' },
                { label: 'Running', value: 'RUNNING' },
              ]}
            />
          </div>
          <div>
            <Box variant="awsui-key-label">Page Size</Box>
            <Select
              selectedOption={{ label: `${pageSize} items`, value: String(pageSize) }}
              onChange={({ detail }) => {
                setPageSize(Number(detail.selectedOption.value));
                setCurrentPage(1);
                setPageTokens({ 1: undefined });
              }}
              options={[
                { label: '10 items', value: '10' },
                { label: '20 items', value: '20' },
                { label: '50 items', value: '50' },
                { label: '100 items', value: '100' },
              ]}
            />
          </div>
        </SpaceBetween>
      </Container>

      {/* Historical task table */}
      <Table
        columnDefinitions={columnDefinitions}
        items={data?.tasks || []}
        loading={loading}
        loadingText="Loading historical data..."
        variant="container"
        header={
          <Header
            variant="h2"
            counter={data?.pagination ? `(${data.pagination.total_count})` : ''}
            description="Historical pipeline activity — task execution, reasoning, and decisions by the AI Squad"
          >
            Pipeline History
          </Header>
        }
        pagination={
          data?.pagination ? (
            <Pagination
              currentPageIndex={currentPage}
              pagesCount={totalPages}
              openEnd={data.pagination.has_more}
              onChange={({ detail }) => handlePageChange(detail)}
            />
          ) : undefined
        }
        empty={
          <Box margin={{ vertical: 'xs' }} textAlign="center" color="inherit">
            <SpaceBetween size="m">
              <b>No historical data</b>
              <Box variant="p" color="inherit">
                No tasks found for the selected filters. Try expanding the time window.
              </Box>
            </SpaceBetween>
          </Box>
        }
        sortingDisabled
        enableKeyboardNavigation
      />

      {/* Archive notice */}
      {data?.archive && data.archive.s3_bucket && (
        <Container>
          <Box fontSize="body-s" color="text-body-secondary">
            <StatusIndicator type="info">
              Tasks older than {data.archive.ttl_days} days are archived to S3 ({data.archive.s3_bucket}/{data.archive.prefix}).
              Contact your administrator for access to archived data.
            </StatusIndicator>
          </Box>
        </Container>
      )}
    </SpaceBetween>
  );
};
