import React from 'react';
import { Database, Box, FileText, Cpu, CheckCircle2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface RegistryItem {
  category: string;
  items: {
    name: string;
    version: string;
    status: 'ready' | 'stable' | 'deprecated';
    details: string;
  }[];
  icon: any;
}

export const RegistriesCard: React.FC = () => {
  const { t } = useTranslation();
  const registries: RegistryItem[] = [
    {
      category: 'Model Registries',
      icon: Cpu,
      items: [
        { name: 'Claude 3.5 Sonnet', version: 'v1.0', status: 'ready', details: 'us-east-1 / bedrock' },
        { name: 'Claude 3 Opus', version: 'v1.0', status: 'ready', details: 'us-east-1 / bedrock' },
        { name: 'Titan Text G1', version: 'v2.1', status: 'stable', details: 'Internal Embedding' },
      ]
    },
    {
      category: 'Agent Templates (ECS)',
      icon: Box,
      items: [
        { name: 'fde-strands-agent', version: 'v6', status: 'ready', details: 'Fargate / 785640717688' },
        { name: 'fde-onboarding-agent', version: 'v2', status: 'ready', details: 'Fargate / 785640717688' },
        { name: 'fde-compliance-gate', version: 'v3', status: 'stable', details: 'Lambda / 785640717688' },
      ]
    },
    {
      category: 'Prompt Manifests',
      icon: FileText,
      items: [
        { name: 'architect-standard', version: '2026.05', status: 'ready', details: 'DynamoDB: prompt-registry' },
        { name: 'reviewer-security', version: '2026.04', status: 'ready', details: 'DynamoDB: prompt-registry' },
        { name: 'coder-refactor-fde', version: '2026.05', status: 'ready', details: 'DynamoDB: prompt-registry' },
      ]
    },
    {
      category: 'Orchestration Rules',
      icon: Database,
      items: [
        { name: 'github-factory-ready', version: 'EB-1', status: 'ready', details: 'EventBridge: fde-factory-bus' },
        { name: 'asana-intake-sync', version: 'EB-2', status: 'ready', details: 'EventBridge: fde-factory-bus' },
      ]
    }
  ];

  return (
    <div className="flex-1 flex flex-col overflow-hidden transition-colors duration-300">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-xl font-medium text-dynamic">{t('registries.title')}</h2>
          <p className="text-xs text-secondary-dynamic font-mono">{t('registries.subtitle')}</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto pr-2 scrollbar-thin">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {registries.map((reg, idx) => (
            <div key={idx} className="bento-card flex flex-col h-full">
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2 rounded-xl bg-aws-orange/10 text-aws-orange">
                  <reg.icon className="w-5 h-5" />
                </div>
                <h3 className="text-sm font-bold text-dynamic uppercase tracking-widest">{reg.category}</h3>
              </div>
              
              <div className="space-y-3 flex-1">
                {reg.items.map((item, iIdx) => (
                  <div key={iIdx} className="bg-black/5 dark:bg-black/30 border border-border-main rounded-xl p-3 group hover:border-aws-orange/30 transition-all">
                    <div className="flex justify-between items-start mb-1">
                      <span className="text-xs font-bold text-dynamic">{item.name}</span>
                      <span className="text-[9px] font-mono bg-aws-orange/20 text-aws-orange px-1.5 py-0.5 rounded uppercase">{item.version}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-[10px] text-secondary-dynamic font-mono">{item.details}</span>
                      <div className="flex items-center gap-1">
                        <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                        <span className="text-[9px] font-bold text-emerald-500 uppercase">{item.status}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
