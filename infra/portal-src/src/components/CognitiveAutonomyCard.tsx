/**
 * CognitiveAutonomyCard — Dual-Axis Autonomy Visibility (ADR-029).
 *
 * Displays the cognitive autonomy decision for the factory:
 *   - Capability Depth: signal breakdown, squad composition, model tier
 *   - Delivery Authority: progress toward auto-merge, trust signals
 *   - Per-task depth comparison (recent tasks at different depths)
 *
 * This card IS the trust-building mechanism. Without visibility into
 * cognitive decisions, humans cannot validate the model and will never
 * enable auto-merge. The UX is not a display layer — it's the trust engine.
 *
 * Personas: Staff (full), PM (authority progress), SWE (per-task), SRE (health)
 *
 * Ref: docs/adr/ADR-029-cognitive-autonomy-model.md
 */

import React from 'react';
import { Brain, Shield, Zap, CheckCircle, Lock } from 'lucide-react';

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

const DepthGauge: React.FC<{ depth: number }> = ({ depth }) => {
  const percentage = depth * 100;
  const color = depth >= 0.7 ? 'bg-purple-500' : depth >= 0.5 ? 'bg-blue-500' : depth >= 0.3 ? 'bg-emerald-500' : 'bg-slate-400';
  const label = depth >= 0.7 ? 'Maximum' : depth >= 0.5 ? 'High' : depth >= 0.3 ? 'Medium' : 'Low';

  return (
    <div className="w-full">
      <div className="flex justify-between items-center mb-1">
        <span className="text-[9px] text-secondary-dynamic uppercase font-medium">Capability Depth</span>
        <span className="text-xs font-mono font-bold text-dynamic">{depth.toFixed(2)} <span className="text-[8px] text-secondary-dynamic">({label})</span></span>
      </div>
      <div className="w-full h-2.5 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-1000 ${color}`} style={{ width: `${percentage}%` }} />
      </div>
    </div>
  );
};

const SignalBar: React.FC<{ signal: CapabilitySignal }> = ({ signal }) => {
  const pct = (signal.value / signal.max) * 100;
  const isFloorRaise = signal.contribution === 'raised floor';
  return (
    <div className="flex items-center gap-2 py-0.5">
      <span className="text-[8px] text-secondary-dynamic w-20 truncate">{signal.name}</span>
      <div className="flex-1 h-1 rounded-full bg-slate-200 dark:bg-slate-800">
        <div className={`h-full rounded-full ${isFloorRaise ? 'bg-amber-400' : 'bg-blue-400'}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <span className="text-[8px] font-mono text-dynamic w-8 text-right">{signal.value.toFixed(1)}</span>
    </div>
  );
};

const AuthorityProgress: React.FC<{ progress: number; authority: string; canAutoMerge: boolean }> = ({ progress, authority, canAutoMerge }) => {
  const icon = canAutoMerge
    ? <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
    : authority === 'blocked'
      ? <Lock className="w-3.5 h-3.5 text-red-400" />
      : <Shield className="w-3.5 h-3.5 text-amber-400" />;
  const label = canAutoMerge ? 'AUTO-MERGE EARNED' : authority === 'blocked' ? 'BLOCKED' : 'EARNING TRUST';
  const color = canAutoMerge ? 'text-emerald-400' : authority === 'blocked' ? 'text-red-400' : 'text-amber-400';
  const barColor = canAutoMerge ? 'bg-emerald-500' : authority === 'blocked' ? 'bg-red-500' : 'bg-amber-500';

  return (
    <div className="p-2 rounded-lg bg-black/5 dark:bg-white/5 border border-border-main">
      <div className="flex items-center gap-2 mb-1.5">
        {icon}
        <span className={`text-[9px] font-bold uppercase ${color}`}>{label}</span>
        <span className="text-[9px] font-mono text-secondary-dynamic ml-auto">{progress}%</span>
      </div>
      <div className="w-full h-1.5 rounded-full bg-slate-200 dark:bg-slate-800">
        <div className={`h-full rounded-full transition-all duration-700 ${barColor}`} style={{ width: `${progress}%` }} />
      </div>
    </div>
  );
};

const TaskDepthRow: React.FC<{ task: CognitiveAutonomyMetrics['recent_tasks'][0] }> = ({ task }) => {
  const depthColor = task.depth >= 0.7 ? 'bg-purple-500' : task.depth >= 0.5 ? 'bg-blue-500' : task.depth >= 0.3 ? 'bg-emerald-500' : 'bg-slate-400';
  return (
    <div className="flex items-center gap-2 py-1">
      <div className={`w-1.5 h-1.5 rounded-full ${depthColor}`} />
      <span className="text-[8px] text-dynamic truncate flex-1">{task.title.slice(0, 30)}</span>
      <span className="text-[8px] font-mono text-secondary-dynamic">{task.depth.toFixed(2)}</span>
      <span className="text-[8px] font-mono text-secondary-dynamic">{task.squad_size}ag</span>
    </div>
  );
};

export const CognitiveAutonomyCard: React.FC<CognitiveAutonomyCardProps> = ({ metrics }) => {
  if (!metrics) {
    return (
      <div className="h-full bento-card flex flex-col items-center justify-center transition-colors duration-300">
        <Brain className="w-12 h-12 text-slate-700 mb-4" aria-hidden="true" />
        <p className="text-sm font-medium text-dynamic mb-1">Cognitive Autonomy</p>
        <p className="text-[10px] text-secondary-dynamic font-mono uppercase tracking-widest">Awaiting first task</p>
      </div>
    );
  }

  return (
    <div className="h-full bento-card flex flex-col transition-colors duration-300">
      {/* Header */}
      <div className="flex justify-between items-start mb-2">
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-aws-orange" aria-hidden="true" />
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest">Cognitive Autonomy</h2>
        </div>
        <div className="flex items-center gap-1.5">
          <Zap className="w-3 h-3 text-purple-400" aria-hidden="true" />
          <span className="text-[10px] font-mono font-bold text-dynamic">{metrics.squad_size} agents</span>
        </div>
      </div>

      {/* Depth Gauge */}
      <DepthGauge depth={metrics.capability_depth} />

      {/* Squad Tags */}
      <div className="flex gap-1.5 mt-2 flex-wrap">
        <span className="text-[8px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 font-mono">{metrics.model_tier}</span>
        <span className="text-[8px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300 font-mono">{metrics.verification_level}</span>
        <span className="text-[8px] px-1.5 py-0.5 rounded bg-slate-500/20 text-secondary-dynamic font-mono">{metrics.topology}</span>
        {metrics.include_adversarial && <span className="text-[8px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 font-mono">adversarial</span>}
        {metrics.include_pr_reviewer && <span className="text-[8px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-mono">pr-reviewer</span>}
      </div>

      {/* Signals */}
      <div className="mt-2 space-y-0">
        {metrics.signals.slice(0, 4).map((signal) => <SignalBar key={signal.name} signal={signal} />)}
      </div>

      {/* Authority */}
      <div className="mt-2">
        <AuthorityProgress progress={metrics.auto_merge_progress} authority={metrics.authority_level} canAutoMerge={metrics.can_auto_merge} />
      </div>

      {/* Conditions */}
      <div className="mt-1.5 grid grid-cols-3 gap-1">
        <div className="text-center">
          <span className={`text-[9px] font-mono font-bold ${metrics.cfr_current < metrics.cfr_threshold ? 'text-emerald-400' : 'text-red-400'}`}>{(metrics.cfr_current * 100).toFixed(0)}%</span>
          <p className="text-[7px] text-secondary-dynamic">CFR</p>
        </div>
        <div className="text-center">
          <span className={`text-[9px] font-mono font-bold ${metrics.trust_score >= metrics.trust_threshold ? 'text-emerald-400' : 'text-amber-400'}`}>{metrics.trust_score.toFixed(0)}%</span>
          <p className="text-[7px] text-secondary-dynamic">Trust</p>
        </div>
        <div className="text-center">
          <span className={`text-[9px] font-mono font-bold ${metrics.consecutive_successes >= metrics.successes_needed ? 'text-emerald-400' : 'text-amber-400'}`}>{metrics.consecutive_successes}/{metrics.successes_needed}</span>
          <p className="text-[7px] text-secondary-dynamic">Streak</p>
        </div>
      </div>

      {/* Recent Tasks */}
      {metrics.recent_tasks.length > 0 && (
        <div className="mt-2 pt-2 border-t border-border-main">
          <p className="text-[8px] text-secondary-dynamic uppercase mb-1">Recent Task Depths</p>
          {metrics.recent_tasks.slice(0, 3).map((task) => <TaskDepthRow key={task.task_id} task={task} />)}
        </div>
      )}
    </div>
  );
};
