import React from 'react';
import { motion } from 'motion/react';
import { useTranslation } from 'react-i18next';

interface MetricBarProps {
  label: string;
  value: number;
  color: string;
}

const MetricBar: React.FC<MetricBarProps> = ({ label, value, color }) => (
  <div>
    <div className="flex justify-between text-xs mb-2">
      <span className="text-secondary-dynamic">{label}</span>
      <span className="text-aws-orange/80 font-mono">{typeof value === 'number' ? `${value}%` : value}</span>
    </div>
    <div className="w-full h-1.5 bg-black/5 dark:bg-white/5 rounded-full overflow-hidden">
      <motion.div 
        initial={{ width: 0 }}
        animate={{ width: typeof value === 'number' ? `${value}%` : '100%' }}
        className={`h-full ${color}`}
      />
    </div>
  </div>
);

interface MetricsCardProps {
  data?: any;
}

export const MetricsCard: React.FC<MetricsCardProps> = ({ data }) => {
  const { t } = useTranslation();
  const deploymentFrequency = data?.success_rate_pct ?? (data?.completed_24h ? 90 : 0);
  const changeFailureRate = data?.failed_24h ?? 4;
  const leadTime = data?.lead_time_avg_ms ? `${Math.round(data.lead_time_avg_ms / 60000)}m` : '14m';
  const mttr = data?.avg_duration_ms ? `${Math.round(data.avg_duration_ms / 60000)}m` : '8m';

  return (
    <div className="h-full bento-card flex flex-col transition-colors duration-300">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest">{t('metrics.dora_performance')}</h2>
        {data && <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />}
      </div>
      <div className="space-y-6 flex-1">
        <MetricBar label={t('metrics.success_rate')} value={deploymentFrequency} color="bg-aws-orange" />
        <MetricBar label={t('metrics.failure_rate')} value={changeFailureRate} color="bg-emerald-500" />
        <div className="grid grid-cols-2 gap-4 pt-4 border-t border-border-main">
          <div>
            <p className="text-[10px] text-secondary-dynamic uppercase">{t('metrics.lead_time')}</p>
            <p className="text-xl font-mono text-dynamic">{leadTime}</p>
          </div>
          <div>
            <p className="text-[10px] text-secondary-dynamic uppercase">{t('metrics.mttr')}</p>
            <p className="text-xl font-mono text-dynamic">{mttr}</p>
          </div>
        </div>
      </div>
    </div>
  );
};
