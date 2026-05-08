import React, { useState, useCallback, useRef, useEffect } from 'react';
import { 
  Play, 
  Cpu, 
  Eye, 
  ShieldCheck, 
  HeartPulse,
  Zap,
  Sun,
  Moon,
  Send,
  Database
} from 'lucide-react';
import { AgentSidebar } from './components/AgentSidebar';
import { Terminal } from './components/Terminal';
import { CodePreview } from './components/CodePreview';
import { Header } from './components/Header';
import { MetricsCard } from './components/MetricsCard';
import { ComponentHealthCard } from './components/ComponentHealthCard';
import { RegistriesCard } from './components/RegistriesCard';
import { BranchEvaluationCard } from './components/BranchEvaluationCard';
import { Agent, LogEntry, AppView } from './types';
import { runAgentStep, AgentRole } from './services/factoryService';
import factoryConfig from './factory-config.json';
import { useTranslation } from 'react-i18next';

const INITIAL_AGENTS: Agent[] = [
  { id: '1', name: 'Factory Orchestrator', role: 'planner', status: 'idle' },
  { id: '2', name: 'Forward Engineer A', role: 'coder', status: 'idle' },
  { id: '3', name: 'Autonomous Reviewer', role: 'reviewer', status: 'idle' },
];

export default function App() {
  const { t, i18n } = useTranslation();
  const [agents, setAgents] = useState<Agent[]>(INITIAL_AGENTS);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [prompt, setPrompt] = useState('');
  const [output, setOutput] = useState<string | undefined>();
  const [isProcessing, setIsProcessing] = useState(false);
  const [activeView, setActiveView] = useState<AppView>('pipeline');
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [apiStatus, setApiStatus] = useState<any>(null);
  const [factoryData, setFactoryData] = useState<any>(null);
  
  const isTabActive = useRef(true);

  const API_URL = document.querySelector('meta[name="factory-api-url"]')?.getAttribute('content') || '';

  // Fetch real health status
  const fetchHealth = useCallback(async () => {
    if (!API_URL) return;
    try {
      const res = await fetch(`${API_URL}/status/health`);
      if (res.ok) {
        const data = await res.json();
        setApiStatus(data);
      }
    } catch (err) {
      console.error('Failed to fetch factory health:', err);
    }
  }, [API_URL]);

  // Fetch real factory data (tasks, metrics, etc)
  const fetchFactoryData = useCallback(async () => {
    if (!API_URL) return;
    try {
      const res = await fetch(`${API_URL}/status/tasks`);
      if (res.ok) {
        const data = await res.json();
        setFactoryData(data);
      }
    } catch (err) {
      console.error('Failed to fetch factory data:', err);
    }
  }, [API_URL]);

  // Sync theme with document
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // Initial load
  useEffect(() => {
    fetchHealth();
    fetchFactoryData();
  }, [fetchHealth, fetchFactoryData]);

  // Sync state view with URL hash
  useEffect(() => {
    const handleHash = () => {
      const hash = window.location.hash.replace('#', '') as AppView;
      if (['pipeline', 'agents', 'reasoning', 'gates', 'health'].includes(hash)) {
        setActiveView(hash);
      }
    };
    window.addEventListener('hashchange', handleHash);
    handleHash();
    return () => window.removeEventListener('hashchange', handleHash);
  }, []);

  const changeView = (view: AppView) => {
    window.location.hash = view;
    setActiveView(view);
  };

  const addLog = useCallback((agentId: string, message: string, type: LogEntry['type']) => {
    setLogs(prev => [...prev, {
      id: Math.random().toString(36).substr(2, 9),
      timestamp: new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      agentId,
      agentName: INITIAL_AGENTS.find(a => a.id === agentId)?.name || 'System',
      message: message.substring(0, 1000),
      type
    }]);

    setAgents(prev => prev.map(a => a.id === agentId ? { 
      ...a, 
      status: type === 'working' ? 'working' : (type === 'action' ? 'thinking' : (type === 'complete' ? 'complete' : (type === 'thought' ? 'thinking' : a.status))), 
      lastMessage: message.substring(0, 50) + (message.length > 50 ? '...' : '')
    } : a));
  }, []);

  const provisionAgent = async (agentId: string) => {
    const agentName = INITIAL_AGENTS.find(a => a.id === agentId)?.name || 'Agent';
    
    setAgents(prev => prev.map(a => a.id === agentId ? { ...a, status: 'intake', lastMessage: 'Intake initiated...' } : a));
    addLog('system', `Factory orchestrator authorized intake for ${agentName}`, 'system');
    await new Promise(r => setTimeout(r, 600));

    setAgents(prev => prev.map(a => a.id === agentId ? { ...a, status: 'provisioning', progress: 0 } : a));
    for (let i = 0; i <= 60; i += 20) {
      if (!isTabActive.current) await new Promise(r => {
        const check = setInterval(() => {
          if (isTabActive.current) {
            clearInterval(check);
            r(null);
          }
        }, 1000);
      });
      setAgents(prev => prev.map(a => a.id === agentId ? { ...a, progress: i } : a));
      await new Promise(r => setTimeout(r, 200));
    }
    
    setAgents(prev => prev.map(a => a.id === agentId ? { ...a, status: 'setup', lastMessage: 'Configuring workspace...' } : a));
    addLog(agentId, 'Hydrating environment variables and AWS contexts...', 'thought');
    for (let i = 61; i <= 100; i += 13) {
      setAgents(prev => prev.map(a => a.id === agentId ? { ...a, progress: Math.min(i, 100) } : a));
      await new Promise(r => setTimeout(r, 150));
    }
    
    addLog(agentId, 'Provisioning successful. Agent onboarded to Cloud Mesh.', 'action');
    setAgents(prev => prev.map(a => a.id === agentId ? { ...a, status: 'thinking', progress: 100 } : a));
  };

  const startFactory = async () => {
    if (!prompt.trim() || isProcessing) return;
    setIsProcessing(true);
    setLogs([]);
    setOutput(undefined);
    setAgents(INITIAL_AGENTS);
    changeView('pipeline');
    
    addLog('system', `Factory intake initiated for project ${factoryConfig.project_id}...`, 'system');
    await new Promise(r => setTimeout(r, 600));

    try {
      await provisionAgent('1');
      const plan = await runAgentStep('planner', prompt);
      plan.thoughts.forEach(t => addLog('1', t, 'thought'));
      addLog('1', plan.message, 'action');

      await provisionAgent('2');
      addLog('2', 'Initializing workspace for target implementation...', 'working');
      
      const codeResult = await runAgentStep('coder', prompt, plan.message);
      codeResult.thoughts.forEach(t => addLog('2', t, 'thought'));
      if (codeResult.code) {
        const header = `/**\n * Generated by CODE_FACTORY (AWS ProServe Style)\n * FDE Pattern: Autonomous Workflow\n * Project: ${factoryConfig.project_id}\n * VPC: ${factoryConfig.vpc}\n */\n\n`;
        setOutput(header + codeResult.code);
      }
      addLog('2', codeResult.message, 'action');

      await provisionAgent('3');
      const reviewResult = await runAgentStep('reviewer', prompt, codeResult.code || codeResult.message);
      reviewResult.thoughts.forEach(t => addLog('3', t, 'thought'));
      addLog('3', reviewResult.message, reviewResult.message.toLowerCase().includes('fail') ? 'error' : 'complete');
      
    } catch (err) {
      addLog('system', `Factory Workflow Stalled: ${err instanceof Error ? err.message : 'Unknown error'}`, 'error');
    } finally {
      setIsProcessing(false);
    }
  };

  useEffect(() => {
    let pollingInterval: NodeJS.Timeout;
    const refreshData = () => {
      if (document.hidden) return;
      const rand = Math.random();
      if (rand > 0.8) {
        addLog('system', `Telemetry check: us-east-1a node throughput ${Math.floor(Math.random() * 100)}k tps`, 'system');
      }
    };
    const startPolling = () => {
      pollingInterval = setInterval(() => {
        refreshData();
        fetchHealth();
        fetchFactoryData();
      }, 15000);
    };
    const handleVisibility = () => {
      isTabActive.current = !document.hidden;
      if (document.hidden) {
        addLog('system', 'Factory monitor entering low-power standby.', 'system');
        clearInterval(pollingInterval);
      } else {
        addLog('system', 'Factory monitor resyncing with Cloud Mesh.', 'system');
        refreshData();
        startPolling();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    startPolling();
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      clearInterval(pollingInterval);
    };
  }, [addLog]);

  const RailItem = ({ view, icon: Icon, label }: { view: AppView, icon: any, label: string }) => (
    <button 
      type="button"
      onClick={() => changeView(view)}
      aria-label={label}
      aria-current={activeView === view ? 'page' : undefined}
      className={`rail-item ${activeView === view ? 'rail-item-active' : ''}`}
    >
      <Icon className="rail-icon" aria-hidden="true" />
      <span className="rail-label">{label}</span>
    </button>
  );

  return (
    <div className="h-screen w-screen bg-bg-main flex overflow-hidden font-sans transition-colors duration-300">
      <a 
        href="#main-content" 
        className="fixed top-4 left-20 z-50 bg-aws-orange text-white px-4 py-2 rounded-lg -translate-y-20 focus:translate-y-0 transition-transform font-bold text-sm shadow-xl"
      >
        Skip to main content
      </a>
      {/* Rail Navigation */}
      <aside 
        role="navigation"
        aria-label="Side navigation"
        className="w-16 bg-bg-card border-r border-border-main flex flex-col items-center py-6 shrink-0 relative transition-colors duration-300"
      >
        <div className="w-10 h-10 bg-aws-orange rounded-lg flex items-center justify-center text-white font-bold mb-8">
          <Zap className="w-6 h-6 fill-white" aria-hidden="true" />
        </div>
        
        <nav className="flex-1 flex flex-col gap-2">
          <RailItem view="pipeline" icon={Play} label={t('nav.flow')} />
          <RailItem view="agents" icon={Cpu} label={t('nav.units')} />
          <RailItem view="reasoning" icon={Eye} label={t('nav.reason')} />
          <RailItem view="gates" icon={ShieldCheck} label={t('nav.gates')} />
          <RailItem view="health" icon={HeartPulse} label={t('nav.health')} />
          <RailItem view="registries" icon={Database} label={t('nav.catalog')} />
        </nav>

        <div className="flex flex-col gap-2 mt-auto mb-4">
          <button 
            onClick={() => {
              const langs = ['en-US', 'pt-BR', 'es'];
              const currentIndex = langs.indexOf(i18n.language);
              const nextIndex = (currentIndex + 1) % langs.length;
              i18n.changeLanguage(langs[nextIndex]);
            }}
            className="w-10 h-10 rounded-xl border border-border-main flex items-center justify-center text-[9px] font-bold text-slate-500 hover:text-aws-orange hover:bg-black/5 dark:hover:bg-white/5 transition-all"
            aria-label="Toggle language"
          >
            {i18n.language === 'en-US' ? 'EN' : i18n.language === 'pt-BR' ? 'PT' : 'ES'}
          </button>
          
          <button 
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            className="w-10 h-10 rounded-xl border border-border-main flex items-center justify-center text-slate-500 hover:text-aws-orange hover:bg-black/5 dark:hover:bg-white/5 transition-all"
          >
            {theme === 'dark' ? <Sun className="w-5 h-5" aria-hidden="true" /> : <Moon className="w-5 h-5" aria-hidden="true" />}
          </button>
        </div>
      </aside>

      {/* Content Area */}
      <div className="flex-1 flex flex-col p-6 overflow-hidden">
        <Header isProcessing={isProcessing} />

        <main id="main-content" className="flex-1 flex flex-col overflow-hidden">
          {activeView === 'pipeline' && (
            <div className="flex-1 flex flex-col gap-4 overflow-hidden">
              <div className="flex-1 overflow-hidden">
                <CodePreview content={output} />
              </div>
              <div className="h-20 flex items-center gap-3 bg-bg-card border border-border-main rounded-2xl px-5 shrink-0 transition-colors duration-300 shadow-2xl">
                <div className="flex-1 relative">
                  <div className="absolute left-0 top-1/2 -translate-y-1/2 text-aws-orange/40">
                    <Cpu className="w-5 h-5 animate-pulse" aria-hidden="true" />
                  </div>
                  <input 
                    type="text" 
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && !isProcessing && startFactory()}
                    placeholder={t('pipeline.placeholder')} 
                    aria-label="Architectural instruction prompt"
                    className="w-full bg-transparent border-none pl-8 pr-4 py-3 text-sm focus:outline-none transition-all text-dynamic placeholder:text-text-secondary"
                  />
                </div>
                <div className="h-8 w-[1px] bg-border-main"></div>
                <button 
                  onClick={startFactory}
                  disabled={isProcessing || !prompt.trim()}
                  aria-label={isProcessing ? t('pipeline.processing') : t('pipeline.interact')}
                  className="flex items-center gap-2 px-6 py-2.5 bg-aws-orange hover:bg-orange-500 disabled:opacity-50 rounded-xl text-sm font-bold transition-all text-white shadow-lg shadow-orange-500/10 uppercase tracking-widest shrink-0"
                >
                  <Send className="w-4 h-4" aria-hidden="true" />
                  {isProcessing ? t('pipeline.processing') : t('pipeline.interact')}
                </button>
              </div>
            </div>
          )}

          {activeView === 'agents' && (
            <div className="flex-1 flex flex-col overflow-hidden">
              <AgentSidebar agents={agents} />
            </div>
          )}

          {activeView === 'reasoning' && (
            <div className="flex-1 flex flex-col overflow-hidden">
              <Terminal logs={logs} />
            </div>
          )}

          {activeView === 'gates' && (
            <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-4 overflow-hidden">
              <BranchEvaluationCard report={factoryData?.branch_evaluation || null} />
              <div className="flex flex-col items-center justify-center border border-white/5 bg-black/20 rounded-2xl">
                <ShieldCheck className="w-12 h-12 text-slate-700 mb-4" />
                <div className="text-center">
                  <p className="text-white font-medium mb-1">Gate Observability Matrix</p>
                  <p className="text-slate-500 font-mono text-[10px] uppercase tracking-widest">Awaiting Decision Flow for Project {factoryConfig.project_id}</p>
                </div>
              </div>
            </div>
          )}

          {activeView === 'health' && (
            <div className="flex-1 grid grid-cols-2 gap-4 overflow-hidden">
              <MetricsCard data={factoryData?.dora || factoryData?.metrics} />
              <ComponentHealthCard status={apiStatus} />
            </div>
          )}

          {activeView === 'registries' && (
            <div className="flex-1 flex flex-col overflow-hidden">
              <RegistriesCard />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
