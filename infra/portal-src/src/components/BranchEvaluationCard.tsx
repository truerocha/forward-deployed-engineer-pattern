import React from 'react';
import { motion } from 'motion/react';
import { GitBranch, CheckCircle2, XCircle, AlertTriangle, Shield } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface DimensionResult {
  score: number;
  weight: number;
  weighted: number;
  issues: string[];
}

interface EvaluationReport {
  branch: string;
  base: string;
  evaluated_at: string;
  verdict: 'PASS' | 'CONDITIONAL_PASS' | 'CONDITIONAL_FAIL' | 'FAIL';
  aggregate_score: number;
  merge_eligible: boolean;
  auto_merge_eligible: boolean;
  veto_triggered: boolean;
  veto_reason: string;
  dimensions: Record<string, DimensionResult>;
  files_evaluated: number;
  pipeline_edges_affected: string[];
}

interface BranchEvaluationCardProps {
  report?: EvaluationReport | null;
}

const VERDICT_CONFIG = {
  PASS: { color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/20', icon: CheckCircle2, label: 'PASS' },
  CONDITIONAL_PASS: { color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20', icon: AlertTriangle, label: 'CONDITIONAL' },
  CONDITIONAL_FAIL: { color: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/20', icon: AlertTriangle, label: 'COND. FAIL' },
  FAIL: { color: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/20', icon: XCircle, label: 'FAIL' },
};

const DimensionBar: React.FC<{ name: string; score: number; weight: number; weighted: number }> = ({ name, score, weight, weighted }) => {
  const barColor = score >= 8 ? 'bg-emerald-500' : score >= 6 ? 'bg-amber-500' : 'bg-red-500';
  const displayName = name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px]">
        <span className="text-secondary-dynamic font-medium">{displayName}</span>
        <div className="flex gap-3">
          <span className="text-secondary-dynamic font-mono">{(weight * 100).toFixed(0)}%</span>
          <span className="text-aws-orange/80 font-mono font-bold">{score.toFixed(1)}</span>
        </div>
      </div>
      <div className="w-full h-1.5 bg-black/5 dark:bg-white/5 rounded-full overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${(score / 10) * 100}%` }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
          className={`h-full ${barColor} rounded-full`}
        />
      </div>
    </div>
  );
};

export const BranchEvaluationCard: React.FC<BranchEvaluationCardProps> = ({ report }) => {
  const { t } = useTranslation();

  if (!report) {
    return (
      <div className="h-full bento-card flex flex-col items-center justify-center transition-colors duration-300">
        <Shield className="w-12 h-12 text-slate-700 mb-4" aria-hidden="true" />
        <p className="text-sm font-medium text-dynamic mb-1">{t('branch_eval.title')}</p>
        <p className="text-[10px] text-secondary-dynamic font-mono uppercase tracking-widest">
          {t('branch_eval.awaiting')}
        </p>
      </div>
    );
  }

  const verdictConfig = VERDICT_CONFIG[report.verdict] || VERDICT_CONFIG.FAIL;
  const VerdictIcon = verdictConfig.icon;

  return (
    <div className="h-full bento-card flex flex-col overflow-hidden transition-colors duration-300">
      {/* Header */}
      <div className="flex justify-between items-start mb-4">
        <div>
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest mb-1">
            {t('branch_eval.title')}
          </h2>
          <p className="text-[10px] text-slate-500 font-mono">{t('branch_eval.subtitle')}</p>
        </div>
        <div className={`px-2 py-1 rounded ${verdictConfig.bg} border ${verdictConfig.border}`}>
          <div className="flex items-center gap-1.5">
            <VerdictIcon className={`w-3 h-3 ${verdictConfig.color}`} aria-hidden="true" />
            <span className={`text-[9px] font-bold uppercase ${verdictConfig.color}`}>
              {verdictConfig.label}
            </span>
          </div>
        </div>
      </div>

      {/* Score Summary */}
      <div className="flex items-center gap-4 mb-4 pb-4 border-b border-border-main">
        <div className="text-center">
          <p className="text-3xl font-mono font-bold text-dynamic">{report.aggregate_score.toFixed(1)}</p>
          <p className="text-[9px] text-secondary-dynamic uppercase">/10</p>
        </div>
        <div className="flex-1 space-y-1 text-[10px]">
          <div className="flex items-center gap-2">
            <GitBranch className="w-3 h-3 text-aws-orange" aria-hidden="true" />
            <span className="text-secondary-dynamic font-mono truncate">{report.branch}</span>
          </div>
          <div className="flex gap-3">
            <span className={`font-bold ${report.merge_eligible ? 'text-emerald-400' : 'text-red-400'}`}>
              {report.merge_eligible ? t('branch_eval.merge_yes') : t('branch_eval.merge_no')}
            </span>
            {report.auto_merge_eligible && (
              <span className="text-aws-orange font-bold">{t('branch_eval.auto_merge')}</span>
            )}
          </div>
          <span className="text-secondary-dynamic">
            {report.files_evaluated} {t('branch_eval.files')} | {report.pipeline_edges_affected.join(', ') || 'no edges'}
          </span>
        </div>
      </div>

      {/* Dimension Scores */}
      <div className="flex-1 overflow-y-auto pr-2 scrollbar-thin space-y-3">
        {Object.entries(report.dimensions).map(([name, dim]) => (
          <DimensionBar
            key={name}
            name={name}
            score={(dim as DimensionResult).score}
            weight={(dim as DimensionResult).weight}
            weighted={(dim as DimensionResult).weighted}
          />
        ))}
      </div>

      {/* Veto Warning */}
      {report.veto_triggered && (
        <div className="mt-3 p-2 rounded-lg bg-red-500/10 border border-red-500/20">
          <p className="text-[10px] text-red-400 font-mono">{report.veto_reason}</p>
        </div>
      )}

      {/* Footer */}
      <div className="mt-3 pt-3 border-t border-border-main flex justify-between text-[9px] text-secondary-dynamic font-mono">
        <span>{new Date(report.evaluated_at).toLocaleTimeString()}</span>
        <span>{t('branch_eval.agent_label')}</span>
      </div>
    </div>
  );
};
