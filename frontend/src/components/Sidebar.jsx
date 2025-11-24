import React, { useState } from 'react';
import { Plus, Trash2, ChevronLeft, ChevronRight, FileText, Clock, LogOut, User } from 'lucide-react';

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
  user,
  onLogout
}) {
  const [editingId, setEditingId] = useState(null);
  return (
    <div 
      className={`${glassClass} rounded-lg overflow-hidden transition-all duration-300 ease-in-out flex flex-col border-r-2 border-[var(--color-accent-primary)] ${
        isCollapsed ? 'w-16' : 'w-72'
      }`}
    >
      {/* Header */}
      <div className="p-3 border-b border-[var(--color-border-medium)] bg-[var(--color-bg-tertiary)]">
        <div className="flex items-center justify-between">
          {!isCollapsed && (
            <h2 className="text-sm font-bold tracking-tight uppercase">Documents</h2>
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
              className={`p-1.5 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)]`}
              title={isCollapsed ? "Expand Sidebar" : "Collapse Sidebar"}
            >
              {isCollapsed ? <ChevronRight size={14} strokeWidth={2.5} /> : <ChevronLeft size={14} strokeWidth={2.5} />}
            </button>
          </div>
        </div>
      </div>

      {/* Collapsed View */}
      {isCollapsed ? (
        <div className="flex flex-col gap-2 p-2 overflow-y-auto">
          {documents.map(doc => (
            <button
              key={doc.id}
              onClick={() => setActiveDoc(doc.id)}
              className={`p-3 rounded-md transition-all border ${
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
        <div className="flex-1 overflow-y-auto p-3">
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
                      onDoubleClick={() => setEditingId(doc.id)}
                      className="flex-1 min-w-0"
                    >
                      <input
                        type="text"
                        value={doc.title}
                        onChange={(e) => updateDocTitle(doc.id, e.target.value)}
                        onBlur={() => setEditingId(null)}
                        readOnly={editingId !== doc.id}
                        className={`bg-transparent border-none outline-none w-full font-semibold text-sm leading-tight ${
                          activeDoc === doc.id ? 'text-[var(--color-bg-primary)]' : textClass
                        } ${editingId === doc.id ? 'focus:ring focus:ring-gray-400' : 'cursor-pointer'} rounded px-1 -mx-1 py-1`}
                        onClick={(e) => {
                          if (editingId === doc.id) {
                            e.stopPropagation();
                          }
                        }}
                      />
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
            className={`w-full p-3 rounded-md ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
            title="New Document"
          >
            <Plus size={18} strokeWidth={2.5} />
          </button>
        </div>
      )}
      
      {/* User Info Section */}
      {!isCollapsed && user && (
        <div className="p-3 border-t border-[var(--color-border-medium)] bg-[var(--color-bg-tertiary)]">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 min-w-0">
              <div className="w-8 h-8 rounded-full bg-[var(--color-accent-primary)] flex items-center justify-center text-[var(--color-bg-primary)] text-xs font-bold">
                {user.name.charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium truncate">{user.name}</p>
                <p className="text-xs text-[var(--color-text-muted)] truncate">{user.email}</p>
              </div>
            </div>
            <button
              onClick={onLogout}
              className={`p-1.5 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-red-500`}
              title="Logout"
            >
              <LogOut size={14} strokeWidth={2.5} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
