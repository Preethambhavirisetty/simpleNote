import React from 'react';
import { Plus, ChevronLeft, ChevronRight } from 'lucide-react';

export default function SidebarHeader({
  isCollapsed,
  onToggleCollapse,
  onAddDocument,
  isSaving,
  lastSaved,
  hoverClass,
}) {
  return (
    <div className="p-3 border-b border-[var(--color-border-medium)] bg-[var(--color-bg-tertiary)]">
      <div className="flex items-center justify-between">
        {!isCollapsed && (
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-bold tracking-tight uppercase">Documents</h2>
            {isSaving && (
              <span className="text-xs text-gray-500 dark:text-gray-400 animate-pulse">
                Saving...
              </span>
            )}
            {!isSaving && lastSaved && (
              <span className="text-xs text-green-600 dark:text-green-400 flex items-center gap-1">
                <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fillRule="evenodd"
                    d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                    clipRule="evenodd"
                  />
                </svg>
                Saved
              </span>
            )}
          </div>
        )}
        <div className="flex items-center gap-2">
          {!isCollapsed && (
            <button
              onClick={onAddDocument}
              className={`p-1.5 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="New Document"
            >
              <Plus size={14} strokeWidth={2.5} />
            </button>
          )}
          <button
            onClick={onToggleCollapse}
            className={`${isCollapsed ? 'p-2' : 'p-1.5'} rounded ${hoverClass} transition-all border border-[var(--color-border-medium)]`}
            title={isCollapsed ? 'Expand Sidebar' : 'Collapse Sidebar'}
          >
            {isCollapsed ? (
              <ChevronRight size={14} strokeWidth={2.5} />
            ) : (
              <ChevronLeft size={14} strokeWidth={2.5} />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

