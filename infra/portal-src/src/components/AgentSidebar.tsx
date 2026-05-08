import React from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Bot, CheckCircle2, CircleDashed, Hammer, Search, Cpu } from 'lucide-react';
import { Agent, AgentStatus } from '../types';
import { useTranslation } from 'react-i18next';

interface AgentCardProps {
  agent: Agent;
}

const StatusIcon = ({ status }: { status: AgentStatus }) => {
  switch (status) {
    case 'intake': return <div className="w-2 h-2 rounded-full bg-blue-500/50 animate-pulse" />;
    case 'provisioning': return <CircleDashed className="w-4 h-4 text-aws-orange animate-spin" />;
    case 'setup': return <div className="w-2 h-2 rounded-full bg-aws-orange animate-ping" />;
    case 'thinking': return <CircleDashed className="w-4 h-4 text-blue-400 animate-spin" />;
    case 'working': return <Hammer className="w-4 h-4 text-aws-orange animate-pulse" />;
    case 'complete': return <CheckCircle2 className="w-4 h-4 text-emerald-400" />;
    case 'error': return <div className="w-2 h-2 rounded-full bg-red-500 animate-ping" />;
    default: return <div className="w-2 h-2 rounded-full bg-zinc-600" />;
  }
};

const RoleIcon = ({ role }: { role: Agent['role'] }) => {
  switch (role) {
    case 'planner': return <Search className="w-4 h-4" />;
    case 'coder': return <Cpu className="w-4 h-4" />;
    case 'reviewer': return <CheckCircle2 className="w-4 h-4" />;
    default: return <Bot className="w-4 h-4" />;
  }
};

const AgentCard: React.FC<AgentCardProps> = ({ agent }) => {
  const { t } = useTranslation();
  const isActive = agent.status !== 'idle';
  const isProvisioning = agent.status === 'provisioning' || agent.status === 'intake' || agent.status === 'setup';
  
  return (
    <motion.div 
      layout
      className={`p-3 border rounded-xl flex flex-col gap-2 transition-all duration-300 ${
        isActive 
          ? 'bg-aws-orange/5 border-aws-orange/20' 
          : 'bg-black/5 dark:bg-white/5 border-border-main opacity-60'
      }`}
    >
      <div className="flex items-center gap-3">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
          isActive ? 'bg-aws-orange/20 text-aws-orange font-bold' : 'bg-black/10 dark:bg-white/10 text-secondary-dynamic'
        }`}>
          <RoleIcon role={agent.role} />
        </div>
        <div className="min-w-0 flex-1">
          <p className={`text-xs font-semibold truncate ${isActive ? 'text-dynamic' : 'text-secondary-dynamic'}`}>{agent.name}</p>
          <AnimatePresence mode="wait">
            <motion.p 
              key={agent.lastMessage}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className={`text-[10px] truncate italic ${isActive ? 'text-aws-orange/80' : 'text-secondary-dynamic'}`}
            >
              {agent.lastMessage || (isActive ? (isProvisioning ? t('agents.onboarding') : t('agents.analyzing')) : t('agents.standby'))}
            </motion.p>
          </AnimatePresence>
        </div>
        {isActive && (
          <div className="shrink-0">
            <StatusIcon status={agent.status} />
          </div>
        )}
      </div>

      {isProvisioning && (
        <div className="space-y-1">
          <div className="flex justify-between text-[8px] font-mono text-aws-orange/60 px-1">
            <span>FDE_INTAKE</span>
            <span>{agent.progress || 0}%</span>
          </div>
          <div className="h-1 bg-white/5 rounded-full overflow-hidden">
            <motion.div 
              className="h-full bg-aws-orange"
              initial={{ width: 0 }}
              animate={{ width: `${agent.progress || 0}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>
        </div>
      )}
    </motion.div>
  );
};

export const AgentSidebar: React.FC<{ agents: Agent[] }> = ({ agents }) => {
  const { t } = useTranslation();
  return (
    <div className="h-full flex flex-col transition-colors duration-300">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-xl font-medium text-dynamic">{t('agents.title')}</h2>
          <p className="text-xs text-secondary-dynamic font-mono">{t('agents.subtitle')}</p>
        </div>
        <div className="flex flex-col items-end">
          <span className="text-[10px] text-aws-orange font-bold tracking-widest">{t('agents.autonomy_level')}</span>
          <span className="text-[10px] text-secondary-dynamic">{t('agents.pipeline_mode')}</span>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto space-y-4 pr-2 scrollbar-thin">
        {agents.map(agent => (
          <AgentCard key={agent.id} agent={agent} />
        ))}
      </div>
    </div>
  );
};
