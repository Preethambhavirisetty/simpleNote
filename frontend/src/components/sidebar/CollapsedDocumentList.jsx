import React from 'react';
import { FileText } from 'lucide-react';

export default function CollapsedDocumentList({
  documents,
  activeDoc,
  onSelectDoc,
  hoverClass,
}) {
  return (
    <div className="flex-1 min-h-0 flex flex-col gap-2 p-2 overflow-y-auto">
      {documents.map((doc) => (
        <button
          key={doc.id}
          onClick={() => onSelectDoc(doc.id)}
          className={`p-2 rounded-md transition-all border ${
            activeDoc === doc.id
              ? 'bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-[var(--color-bg-primary)]'
              : `${hoverClass} border-[var(--color-border-medium)]`
          }`}
          title={doc.title}
        >
          <FileText size={18} strokeWidth={2} />
        </button>
      ))}
    </div>
  );
}

