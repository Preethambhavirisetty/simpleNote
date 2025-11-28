import React, { useState } from 'react';
import { Plus } from 'lucide-react';
import SidebarHeader from './sidebar/SidebarHeader';
import DocumentItem from './sidebar/DocumentItem';
import CollapsedDocumentList from './sidebar/CollapsedDocumentList';

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
  lastSaved,
}) {
  const [editingId, setEditingId] = useState(null);
  const [editingValue, setEditingValue] = useState('');

  const startEditing = (doc) => {
    setEditingId(doc.id);
    setEditingValue(doc.title);
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
      <SidebarHeader
        isCollapsed={isCollapsed}
        onToggleCollapse={onToggleCollapse}
        onAddDocument={addNewDocument}
        isSaving={isSaving}
        lastSaved={lastSaved}
        hoverClass={hoverClass}
      />

      {isCollapsed ? (
        <>
          <CollapsedDocumentList
            documents={documents}
            activeDoc={activeDoc}
            onSelectDoc={setActiveDoc}
            hoverClass={hoverClass}
          />
          
          {/* Add button in collapsed mode */}
          <div className="p-2 border-t border-[var(--color-border-medium)]">
            <button
              onClick={addNewDocument}
              className={`w-full p-2 rounded-md ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="New Document"
            >
              <Plus size={18} strokeWidth={2.5} />
            </button>
          </div>
        </>
      ) : (
        /* Expanded View */
        <div className="flex-1 min-h-0 overflow-y-auto p-3">
          <div className="space-y-2">
            {documents.map((doc, index) => (
              <DocumentItem
                key={doc.id}
                doc={doc}
                isActive={activeDoc === doc.id}
                isEditing={editingId === doc.id}
                editingValue={editingValue}
                onSelect={() => setActiveDoc(doc.id)}
                onStartEditing={startEditing}
                onEditChange={setEditingValue}
                onConfirmRename={confirmRename}
                onCancelRename={cancelRename}
                onDelete={deleteDocument}
                canDelete={documents.length > 1}
                hoverClass={hoverClass}
                textClass={textClass}
                index={index}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
