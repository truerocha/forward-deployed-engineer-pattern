/**
 * Factory Service — Connects to the Code Factory Status API.
 * All data comes from the real API. No simulations.
 */

export interface TaskEvent {
  ts: string;
  type: string;
  msg: string;
  phase?: string;
  gate_name?: string;
  gate_result?: string;
  criteria?: string;
  context?: string;
  autonomy_level?: string;
  confidence?: string;
}

export interface Task {
  task_id: string;
  title: string;
  status: string;
  current_stage: string;
  stage_progress: { current: number; total: number; percent: number };
  agent: { instance_id: string; name: string } | null;
  repo: string;
  source: string;
  issue_url: string;
  pr_url: string;
  pr_error: string;
  priority: string;
  elapsed_ms: number;
  duration_ms: number;
  events: TaskEvent[];
  updated_at?: string;
  created_at?: string;
  rework_attempt?: number;
  rework_feedback?: string;
  rework_constraint?: string;
  original_pr_url?: string;
}

export interface DashboardData {
  metrics: {
    active: number;
    completed_24h: number;
    failed_24h: number;
    avg_duration_ms: number;
    total_agents_provisioned: number;
    active_agents: number;
  };
  dora: {
    level: string;
    lead_time_avg_ms: number;
    success_rate_pct: number;
    throughput_24h: number;
    change_failure_rate_pct: number;
  } | null;
  tasks: Task[];
  pagination?: {
    page_size: number;
    total_count: number;
    has_more: boolean;
    next_token: string | null;
  };
  agents: { instance_id: string; name: string; task_id: string; status: string; started_at: string; execution_time_ms: number }[];
  projects: { repo: string; display_name: string; task_count: number; active: number }[];
}

function getApiUrl(): string {
  return document.querySelector('meta[name="factory-api-url"]')?.getAttribute('content') || '';
}

export async function fetchDashboardData(repoFilter?: string, pageSize?: number, nextToken?: string): Promise<DashboardData | null> {
  const api = getApiUrl();
  if (!api) return null;

  const params = new URLSearchParams();
  if (repoFilter) params.set('repo', repoFilter);
  if (pageSize) params.set('page_size', String(pageSize));
  if (nextToken) params.set('next_token', nextToken);

  const url = `${api}/status/tasks${params.toString() ? '?' + params.toString() : ''}`;

  try {
    const r = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

export async function fetchTaskReasoning(taskId: string): Promise<{ events: TaskEvent[]; gate_summary: { total: number; passed: number; failed: number } } | null> {
  const api = getApiUrl();
  if (!api) return null;

  try {
    const r = await fetch(`${api}/status/tasks/${taskId}/reasoning`, { headers: { Accept: 'application/json' } });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

export async function fetchHealth(): Promise<{ status: string; checks: { name: string; status: string; detail: string }[] } | null> {
  const api = getApiUrl();
  if (!api) return null;

  try {
    const r = await fetch(`${api}/status/health`, { headers: { Accept: 'application/json' } });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}



export interface CapacityData {
  concurrency: {
    max_per_repo: number;
    repos: { repo: string; active: number; max: number; utilization_pct: number; saturated: boolean }[];
    total_active: number;
    total_capacity: number;
  };
  queue: {
    total_queued: number;
    by_repo: Record<string, number>;
    queued_task_ids: string[];
  };
  ecs: {
    running_tasks: number;
    tasks: { task_arn: string; status: string; cpu: string; memory: string; started_at: string; group: string }[];
  };
  reaper: {
    status: string;
    last_invocation: string | null;
    last_result: string | null;
    memory_mb?: number;
    timeout_s?: number;
    last_modified?: string;
  };
  timestamp: string;
}

export async function fetchCapacity(): Promise<CapacityData | null> {
  const api = getApiUrl();
  if (!api) return null;

  try {
    const r = await fetch(`${api}/status/capacity`, { headers: { Accept: 'application/json' } });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}


export interface SreReadinessData {
  circuit_breaker: {
    state: 'closed' | 'open' | 'unknown';
    orchestrator_ready: boolean;
    last_change: string | null;
    changed_by: string;
    blast_radius: number;
    detection_window_min: number;
    error?: string;
  };
  reaper_health: {
    last_run: string | null;
    tasks_reaped: number;
    tasks_redispatched: number;
    counter_drift_corrections: number;
    orchestrator_assessment: string;
    actions: { ts: string; action: string; detail: string }[];
    error?: string;
  };
  agent_readiness: {
    task_def_version: string | null;
    task_def_family?: string;
    ecr_last_pushed: string | null;
    ecr_image_tags?: string[];
    fargate_capacity: string;
    running_count?: number;
    recent_exit_codes: { task_arn: string; exit_code: number; reason: string; stopped_at: string }[];
    error?: string;
  };
  task_flow: {
    status_distribution: Record<string, number>;
    avg_ingested_duration_ms: number;
    dispatch_to_start_p50_ms: number;
    dispatch_to_start_p95_ms: number;
    error?: string;
  };
  timestamp: string;
}

export async function fetchSreReadiness(): Promise<SreReadinessData | null> {
  const api = getApiUrl();
  if (!api) return null;

  try {
    const r = await fetch(`${api}/status/sre-readiness`, { headers: { Accept: 'application/json' } });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}


export interface HistoryTask {
  task_id: string;
  title: string;
  status: string;
  repo: string;
  source: string;
  priority: string;
  duration_ms: number;
  created_at: string;
  updated_at: string;
  issue_url: string;
  pr_url: string;
  current_stage: string;
  event_count: number;
  has_reasoning: boolean;
}

export interface HistoryData {
  tasks: HistoryTask[];
  pagination: {
    page_size: number;
    total_count: number;
    has_more: boolean;
    next_token: string | null;
  };
  periods: {
    last_7d: { completed: number; failed: number; total: number };
    last_30d: { completed: number; failed: number; total: number };
    last_90d: { completed: number; failed: number; total: number };
  };
  archive: {
    s3_bucket: string;
    prefix: string;
    ttl_days: number;
    note: string;
  };
  filters: {
    repo: string;
    status: string;
    days: number;
  };
  timestamp: string;
}

export async function fetchHistory(options?: {
  days?: number;
  pageSize?: number;
  nextToken?: string;
  repo?: string;
  status?: string;
}): Promise<HistoryData | null> {
  const api = getApiUrl();
  if (!api) return null;

  const params = new URLSearchParams();
  if (options?.days) params.set('days', String(options.days));
  if (options?.pageSize) params.set('page_size', String(options.pageSize));
  if (options?.nextToken) params.set('next_token', options.nextToken);
  if (options?.repo) params.set('repo', options.repo);
  if (options?.status) params.set('status', options.status);

  const url = `${api}/status/history${params.toString() ? '?' + params.toString() : ''}`;

  try {
    const r = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}
