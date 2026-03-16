import React, { useRef } from 'react';
import { Trash2, Clock, Check, X } from 'lucide-react';

export default function DocumentItem({
  doc,
  isActive,
  isEditing,
  editingValue,
  onSelect,
  onStartEditing,
  onEditChange,
  onConfirmRename,
  onCancelRename,
  onDelete,
  canDelete,
  hoverClass,
  textClass,
  index,
}) {
  const inputRef = useRef(null);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      onConfirmRename();
    } else if (e.key === 'Escape') {
      onCancelRename();
    }
  };

  return (
    <div
      className={`rounded-md cursor-pointer transition-all duration-300 ease-out group border ${
        isActive
          ? 'bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-[var(--color-bg-primary)] shadow-lg'
          : `${hoverClass} border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`
      }`}
      style={{
        animation: index === 0 ? 'slideInFromTop 0.3s ease-out' : 'none',
      }}
    >
      <div className="p-2">
        <div className="flex items-start justify-between gap-2">
          <div
            onClick={onSelect}
            onDoubleClick={() => onStartEditing(doc)}
            className="flex-1 min-w-0"
          >
            <div className="flex items-center gap-1">
              <input
                ref={isEditing ? inputRef : null}
                type="text"
                value={isEditing ? editingValue : doc.title}
                onChange={(e) => isEditing && onEditChange(e.target.value)}
                onKeyDown={handleKeyDown}
                readOnly={!isEditing}
                className={`bg-transparent border-none outline-none flex-1 font-semibold text-sm leading-tight ${
                  isActive ? 'text-[var(--color-bg-primary)]' : textClass
                } ${
                  isEditing
                    ? 'focus:ring-2 focus:ring-[var(--color-accent-primary)] px-2 py-1 bg-[var(--color-bg-elevated)]'
                    : 'cursor-pointer px-1 py-1'
                } rounded -mx-1`}
                onClick={(e) => {
                  if (isEditing) {
                    e.stopPropagation();
                  }
                }}
              />
              {isEditing && (
                <div
                  className="flex items-center gap-1"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button
                    onClick={onConfirmRename}
                    className="p-1 rounded-full bg-green-500 hover:bg-green-600 text-white transition-colors shadow-sm"
                    title="Confirm (Enter)"
                  >
                    <Check size={12} strokeWidth={2.5} />
                  </button>
                  <button
                    onClick={onCancelRename}
                    className="p-1 rounded-full bg-red-500 hover:bg-red-600 text-white transition-colors shadow-sm"
                    title="Cancel (Esc)"
                  >
                    <X size={12} strokeWidth={2.5} />
                  </button>
                </div>
              )}
            </div>
            <div
              className={`flex items-center gap-2 mt-2 text-xs font-medium ${
                isActive ? 'opacity-70' : 'text-[var(--color-text-muted)]'
              }`}
            >
              <Clock size={12} strokeWidth={2} />
              <span>
                {new Date(doc.created_at).toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                })}
              </span>
            </div>
          </div>
          {canDelete && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                if (window.confirm(`Delete "${doc.title}"?`)) {
                  onDelete(doc.id);
                }
              }}
              className={`opacity-0 group-hover:opacity-100 transition-opacity p-2 rounded-md hover:bg-[var(--color-hover)] ${
                isActive ? 'hover:bg-white/20' : ''
              }`}
              title="Delete"
            >
              <Trash2 size={14} strokeWidth={2} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

