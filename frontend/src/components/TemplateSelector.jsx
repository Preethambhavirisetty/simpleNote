import React from 'react';
import { FileText, ChevronDown, Check } from 'lucide-react';

export default function TemplateSelector({
  templates,
  pageTemplate,
  showTemplates,
  setShowTemplates,
  applyTemplate,
  glassClass,
  hoverClass
}) {
  return (
    <div className="relative">
      <button
        onClick={() => setShowTemplates(!showTemplates)}
        className={`flex items-center gap-2 px-3 py-1.5 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
      >
        <FileText size={14} strokeWidth={2} />
        <span className="text-xs font-semibold tracking-tight">
          {templates[pageTemplate].name}
        </span>
        <ChevronDown 
          size={12} 
          strokeWidth={2}
          className={`transition-transform duration-200 ${showTemplates ? 'rotate-180' : ''}`}
        />
      </button>
      {showTemplates && (
        <div className={`absolute top-full mt-2 left-0 ${glassClass} rounded-lg p-2 min-w-[240px] z-[100] animate-fade-in shadow-2xl border border-[var(--color-border-medium)]`}>
          <div className="px-2 py-1.5 border-b border-[var(--color-border-light)] mb-1">
            <p className="text-xs font-bold tracking-wider uppercase text-[var(--color-text-secondary)]">
              Templates
            </p>
          </div>
          {Object.entries(templates).map(([key, template]) => (
            <button
              key={key}
              onClick={() => applyTemplate(key)}
              className={`w-full text-left px-4 py-3 rounded-md ${hoverClass} transition-all flex items-center justify-between group border mb-1 ${
                pageTemplate === key 
                  ? 'bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-[var(--color-bg-primary)]' 
                  : 'border-transparent hover:border-[var(--color-border-medium)]'
              }`}
            >
              <span className={`text-sm font-semibold tracking-tight ${
                pageTemplate === key ? 'text-[var(--color-bg-primary)]' : ''
              }`}>
                {template.name}
              </span>
              {pageTemplate === key && (
                <Check size={16} strokeWidth={3} />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
