import React, { useState } from 'react';
import { FileCode, Copy, Check } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export const CodePreview = ({ content }: { content?: string }) => {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    if (content) {
      navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden transition-colors duration-300">
      <div className="flex justify-between items-center mb-6 shrink-0">
        <div>
          <h2 className="text-xl font-medium text-dynamic">{t('pipeline.title')}</h2>
          <p className="text-xs text-secondary-dynamic font-mono">{t('pipeline.subtitle')}</p>
        </div>
        <div className="flex gap-2">
           {content && (
             <button 
               onClick={handleCopy}
               className="px-4 py-1.5 bg-white/5 hover:bg-white/10 border border-border-color rounded-lg text-[10px] font-bold transition-all text-secondary-dynamic hover:text-white uppercase tracking-widest"
             >
               {copied ? 'COPIED' : 'Download Artifact'}
             </button>
           )}
           <div className="px-3 py-1.5 bg-aws-orange/10 border border-aws-orange/20 rounded-lg text-[10px] text-aws-orange font-bold uppercase tracking-widest">
             FDE_ACTIVE
           </div>
        </div>
      </div>
      
      <div className="flex-1 bg-black/10 dark:bg-black/40 rounded-2xl border border-border-color overflow-hidden flex flex-col">
        {content ? (
          <div className="flex-1 overflow-auto p-6 font-mono text-[13px] leading-relaxed scrollbar-thin">
            <div className="space-y-1 text-dynamic">
              {content.split('\n').map((line, i) => (
                <div key={i} className="flex gap-4 group/line">
                  <span className="w-8 text-slate-600 text-right select-none opacity-40">{String(i + 1).padStart(2, '0')}</span>
                  <span className="text-emerald-400/90 group-hover/line:text-emerald-300 transition-colors whitespace-pre">
                    {line || ' '}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-secondary-dynamic gap-4">
            <div className="w-16 h-16 rounded-full border-2 border-border-main flex items-center justify-center">
              <FileCode className="w-8 h-8 opacity-40" aria-hidden="true" />
            </div>
            <p className="text-sm font-mono uppercase tracking-[0.3em] font-bold">{t('pipeline.awaiting_signal')}</p>
          </div>
        )}
      </div>
    </div>
  );
};
