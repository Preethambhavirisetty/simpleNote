import React, { useState, useRef } from 'react';
import { Plus, Trash2, ChevronLeft, ChevronRight, FileText, Clock, Check, X } from 'lucide-react';

export default function Sidebar({
  documents,
  activeDoc,
  setActiveDoc,
  addNewDocument,
  deleteDocument,
  updateDocTitle,
  glassClass,
  hoverClass,
  textClass,
  theme,
  isCollapsed,
  onToggleCollapse,
  isSaving,
  lastSaved
}) {
  const [editingId, setEditingId] = useState(null);
  const [editingValue, setEditingValue] = useState('');
  const inputRef = useRef(null);

  const startEditing = (doc) => {
    setEditingId(doc.id);
    setEditingValue(doc.title);
    setTimeout(() => inputRef.current?.select(), 0);
  };

  const confirmRename = () => {
    if (editingValue.trim() && editingId) {
      updateDocTitle(editingId, editingValue.trim());
    }
    setEditingId(null);
    setEditingValue('');
  };

  const cancelRename = () => {
    setEditingId(null);
    setEditingValue('');
  };

  return (
    <div 
      className={`scroll-container ${glassClass} rounded-lg overflow-hidden transition-all duration-300 ease-in-out flex flex-col border-r-2 border-[var(--color-accent-primary)] h-full ${
        isCollapsed ? 'hidden md:flex md:w-14' : 'w-full md:w-72'
      }`}
    >
      {/* Header */}
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
                    <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/>
                  </svg>
                  Saved
                </span>
              )}
            </div>
          )}
          <div className="flex items-center gap-2">
            {!isCollapsed && (
              <button
                onClick={addNewDocument}
                className={`p-1.5 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
                title="New Document"
              >
                <Plus size={14} strokeWidth={2.5} />
              </button>
            )}
            <button
              onClick={onToggleCollapse}
              className={`${isCollapsed ? "p-2" : "p-1.5"} rounded ${hoverClass} transition-all border border-[var(--color-border-medium)]`}
              title={isCollapsed ? "Expand Sidebar" : "Collapse Sidebar"}
            >
              {isCollapsed ? <ChevronRight size={14} strokeWidth={2.5} /> : <ChevronLeft size={14} strokeWidth={2.5} />}
            </button>
          </div>
        </div>
      </div>

      {/* Collapsed View */}
      {isCollapsed ? (
        <div className="flex-1 min-h-0 flex flex-col gap-2 p-2 overflow-y-auto">
          {documents.map(doc => (
            <button
              key={doc.id}
              onClick={() => setActiveDoc(doc.id)}
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
      ) : (
        /* Expanded View */
        <div className="flex-1 min-h-0 overflow-y-auto p-3">
          <div className="space-y-2">
            {documents.map((doc, index) => (
              <div
                key={doc.id}
                className={`rounded-md cursor-pointer transition-all duration-300 ease-out group border ${
                  activeDoc === doc.id
                    ? 'bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-[var(--color-bg-primary)] shadow-lg'
                    : `${hoverClass} border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`
                }`}
                style={{
                  animation: index === 0 ? 'slideInFromTop 0.3s ease-out' : 'none'
                }}
              >
                <div className="p-2">
                  <div className="flex items-start justify-between gap-2">
                    <div
                      onClick={() => setActiveDoc(doc.id)}
                      onDoubleClick={() => startEditing(doc)}
                      className="flex-1 min-w-0"
                    >
                      <div className="flex items-center gap-1">
                        <input
                          ref={editingId === doc.id ? inputRef : null}
                          type="text"
                          value={editingId === doc.id ? editingValue : doc.title}
                          onChange={(e) => {
                            if (editingId === doc.id) {
                              setEditingValue(e.target.value);
                            }
                          }}
                          onKeyDown={(e) => {
                            if (editingId === doc.id) {
                              if (e.key === 'Enter') {
                                confirmRename();
                              } else if (e.key === 'Escape') {
                                cancelRename();
                              }
                            }
                          }}
                          readOnly={editingId !== doc.id}
                          className={`bg-transparent border-none outline-none flex-1 font-semibold text-sm leading-tight ${
                            activeDoc === doc.id ? 'text-[var(--color-bg-primary)]' : textClass
                          } ${editingId === doc.id ? 'focus:ring-2 focus:ring-[var(--color-accent-primary)] px-2 py-1 bg-[var(--color-bg-elevated)]' : 'cursor-pointer px-1 py-1'} rounded -mx-1`}
                          onClick={(e) => {
                            if (editingId === doc.id) {
                              e.stopPropagation();
                            }
                          }}
                        />
                        {editingId === doc.id && (
                          <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                            <button
                              onClick={confirmRename}
                              className="p-1 rounded-full bg-green-500 hover:bg-green-600 text-white transition-colors shadow-sm"
                              title="Confirm (Enter)"
                            >
                              <Check size={12} strokeWidth={2.5} />
                            </button>
                            <button
                              onClick={cancelRename}
                              className="p-1 rounded-full bg-red-500 hover:bg-red-600 text-white transition-colors shadow-sm"
                              title="Cancel (Esc)"
                            >
                              <X size={12} strokeWidth={2.5} />
                            </button>
                          </div>
                        )}
                      </div>
                      <div className={`flex items-center gap-2 mt-2 text-xs font-medium ${
                        activeDoc === doc.id ? 'opacity-70' : 'text-[var(--color-text-muted)]'
                      }`}>
                        <Clock size={12} strokeWidth={2} />
                        <span>
                          {new Date(doc.created_at).toLocaleDateString('en-US', { 
                            month: 'short', 
                            day: 'numeric'
                          })}
                        </span>
                      </div>
                    </div>
                    {documents.length > 1 && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          if (window.confirm(`Delete "${doc.title}"?`)) {
                            deleteDocument(doc.id);
                          }
                        }}
                        className={`opacity-0 group-hover:opacity-100 transition-opacity p-2 rounded-md hover:bg-[var(--color-hover)] ${
                          activeDoc === doc.id ? 'hover:bg-white/20' : ''
                        }`}
                        title="Delete"
                      >
                        <Trash2 size={14} strokeWidth={2} />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Add button in collapsed mode */}
      {isCollapsed && (
        <div className="p-2 border-t border-[var(--color-border-medium)]">
          <button
            onClick={addNewDocument}
            className={`w-full p-2 rounded-md ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
            title="New Document"
          >
            <Plus size={18} strokeWidth={2.5} />
          </button>
        </div>
      )}
    </div>
  );
}
