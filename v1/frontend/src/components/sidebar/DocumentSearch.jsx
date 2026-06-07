import React, { useState } from 'react';
import { Search, X } from 'lucide-react';

export default function DocumentSearch({ documents, onSelectDoc, hoverClass, textClass }) {
  const [searchQuery, setSearchQuery] = useState('');
  const [isExpanded, setIsExpanded] = useState(false);

  const filteredDocs = searchQuery.trim()
    ? documents.filter((doc) =>
        doc.title.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : [];

  const handleSelect = (docId) => {
    onSelectDoc(docId);
    setSearchQuery('');
    setIsExpanded(false);
  };

  if (!isExpanded && !searchQuery) {
    return (
      <div className="p-2 border-b border-[var(--color-border-medium)]">
        <button
          onClick={() => setIsExpanded(true)}
          className={`w-full flex items-center gap-2 p-2 rounded-md ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)] text-sm`}
        >
          <Search size={16} strokeWidth={2} />
          <span className="text-[var(--color-text-muted)]">Search documents...</span>
        </button>
      </div>
    );
  }

  return (
    <div className="p-2 border-b border-[var(--color-border-medium)]">
      <div className="relative">
        <Search
          size={16}
          className="absolute left-2 top-1/2 transform -translate-y-1/2 text-[var(--color-text-muted)]"
          strokeWidth={2}
        />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search documents..."
          className={`w-full pl-8 pr-8 py-2 rounded-md ${textClass} bg-[var(--color-bg-secondary)] border border-[var(--color-border-medium)] focus:outline-none focus:border-[var(--color-accent-primary)] text-sm`}
          autoFocus
        />
        {searchQuery && (
          <button
            onClick={() => {
              setSearchQuery('');
              setIsExpanded(false);
            }}
            className="absolute right-2 top-1/2 transform -translate-y-1/2 text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
          >
            <X size={16} strokeWidth={2} />
          </button>
        )}
      </div>
      {searchQuery && filteredDocs.length > 0 && (
        <div className="mt-2 max-h-48 overflow-y-auto">
          {filteredDocs.map((doc) => (
            <button
              key={doc.id}
              onClick={() => handleSelect(doc.id)}
              className={`w-full text-left p-2 rounded-md ${hoverClass} transition-all text-sm mb-1`}
            >
              {doc.title}
            </button>
          ))}
        </div>
      )}
      {searchQuery && filteredDocs.length === 0 && (
        <div className="mt-2 text-sm text-[var(--color-text-muted)] text-center py-2">
          No documents found
        </div>
      )}
    </div>
  );
}

