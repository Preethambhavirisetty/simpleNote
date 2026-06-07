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
            <h2 className="text-sm font-bold tracking-tight">My Documents</h2>
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
            className={`${isCollapsed ? 'p-2' : 'p-1.5'} rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hidden md:block`}
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

