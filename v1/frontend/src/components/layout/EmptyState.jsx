import React from 'react';

export default function EmptyState({ onCreateDocument, glassClass }) {
  return (
    <div
      className={`flex-1 ${glassClass} rounded-lg flex flex-col items-center justify-center gap-6 p-12`}
    >
      <div className="text-6xl opacity-30">📝</div>
      <div className="text-center">
        <h2 className="text-2xl font-bold mb-2 text-[var(--color-text-primary)]">
          No Documents Yet
        </h2>
        <p className="text-[var(--color-text-muted)] mb-6">
          Create your first document to get started
        </p>
        <button
          onClick={onCreateDocument}
          className="px-6 py-3 rounded-lg bg-[var(--color-accent-primary)] text-[var(--color-bg-primary)] font-semibold hover:opacity-80 transition-all shadow-lg"
        >
          Create New Document
        </button>
      </div>
    </div>
  );
}

