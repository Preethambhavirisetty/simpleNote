import React from 'react';
import { Sparkles } from 'lucide-react';

export default function TextSelectionTooltip({ position, onAskAI }) {
  if (!position) return null;

  return (
    <div
      className="fixed z-[9998] animate-fade-in-quick"
      style={{
        left: `${position.x}px`,
        top: `${position.y - 50}px`,
        transform: 'translateX(-50%)'
      }}
    >
      <button
        onClick={onAskAI}
        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--color-accent-primary)] text-[var(--color-bg-primary)] font-semibold shadow-2xl hover:scale-105 transition-all border-2 border-[var(--color-accent-primary)]"
        style={{
          backdropFilter: 'blur(10px)',
          WebkitBackdropFilter: 'blur(10px)'
        }}
      >
        <Sparkles size={16} />
        <span className="text-sm">Ask AI</span>
      </button>
      <div
        className="absolute left-1/2 -translate-x-1/2 top-full w-0 h-0 border-l-8 border-r-8 border-t-8 border-transparent border-t-[var(--color-accent-primary)]"
      />
    </div>
  );
}

