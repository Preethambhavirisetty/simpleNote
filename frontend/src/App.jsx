import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from './context/AuthContext';
import { useDocuments, useTheme, useToast, useHashRouting } from './hooks';

// Components
import Sidebar from './components/Sidebar';
import Toolbar from './components/Toolbar';
import AIPanel from './components/AIPanel';
import Toast from './components/Toast';
import Editor from './core/editor/Editor';
import { TopBar, EmptyState } from './components/layout';
import { LoadingSpinner } from './components/ui';

// Style constants
const bgClass = 'bg-[var(--color-bg-secondary)]';
const glassClass = 'glass';
const textClass = 'text-[var(--color-text-primary)]';
const hoverClass = 'hover:bg-[var(--color-hover)] transition-all duration-150';

export default function App() {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme('light');
  const { toast, showToast, hideToast } = useToast();

  // Document management
  const {
    documents,
    activeDoc,
    setActiveDoc,
    currentDoc,
    isLoading,
    isSaving,
    lastSaved,
    loadDocuments,
    addNewDocument,
    deleteDocument,
    updateDocContent,
    updateDocTitle,
    manualSave,
    handleFileUpload,
  } = useDocuments();

  // UI state
  const [showAIPanel, setShowAIPanel] = useState(false);
  const [selectedText, setSelectedText] = useState('');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [toolbarCollapsed, setToolbarCollapsed] = useState(false);
  const [showMobileSidebar, setShowMobileSidebar] = useState(false);
  const [editorInstance, setEditorInstance] = useState(null);

  // Hash-based routing
  useHashRouting(activeDoc, documents, setActiveDoc);

  // Load documents on mount
  useEffect(() => {
    loadDocuments();
  }, []);

  // Handlers with toast integration
  const handleAddNewDocument = useCallback(() => {
    addNewDocument(showToast);
    setShowMobileSidebar(false);
  }, [addNewDocument, showToast]);

  const handleDeleteDocument = useCallback(
    (id) => deleteDocument(id, showToast),
    [deleteDocument, showToast]
  );

  const handleUpdateDocTitle = useCallback(
    (id, title) => updateDocTitle(id, title, showToast),
    [updateDocTitle, showToast]
  );

  const handleUpdateDocContent = useCallback(
    (content) => updateDocContent(content, showToast),
    [updateDocContent, showToast]
  );

  const handleManualSave = useCallback(
    () => manualSave(showToast),
    [manualSave, showToast]
  );

  const handleFileUploadWithToast = useCallback(
    (title, content) => handleFileUpload(title, content, showToast),
    [handleFileUpload, showToast]
  );

  const handleLogout = async () => {
    await logout();
    window.location.href = '/';
  };

  const handleTextSelection = (text) => {
    setSelectedText(text);
  };

  const handleSelectDoc = useCallback(
    (docId) => {
      setActiveDoc(docId);
      // Close mobile sidebar when document is selected
      if (window.innerWidth < 768) {
        setShowMobileSidebar(false);
      }
    },
    [setActiveDoc]
  );

  // Loading state
  if (isLoading) {
    return (
      <div className={`min-h-screen ${bgClass} flex items-center justify-center`}>
        <div className={`${glassClass} rounded-3xl p-12 animate-fade-in`}>
          <LoadingSpinner message="Loading your notes..." />
        </div>
      </div>
    );
  }

  return (
    <div className={`min-h-screen ${bgClass} ${textClass} p-2 sm:p-4 transition-all duration-300`}>
      {/* Top Bar */}
      <TopBar
        user={user}
        theme={theme}
        onToggleTheme={toggleTheme}
        onLogout={handleLogout}
        onToggleAIPanel={() => setShowAIPanel(!showAIPanel)}
        showAIPanel={showAIPanel}
        documentsCount={documents.length}
        hasActiveDoc={!!currentDoc}
        showMobileSidebar={showMobileSidebar}
        onToggleMobileSidebar={() => setShowMobileSidebar(!showMobileSidebar)}
        glassClass={glassClass}
        hoverClass={hoverClass}
      />

      {/* Mobile Toolbar - positioned at top for mobile */}
      {documents.length > 0 && currentDoc && (
        <div className="md:hidden mb-2">
          <Toolbar
            editor={editorInstance}
            currentDoc={currentDoc}
            glassClass={glassClass}
            hoverClass={hoverClass}
            updateDocContent={handleUpdateDocContent}
            onFileUpload={handleFileUploadWithToast}
            showToast={showToast}
            isCollapsed={toolbarCollapsed}
            onToggleCollapse={() => setToolbarCollapsed(!toolbarCollapsed)}
            mobileOnly
          />
        </div>
      )}

      <div className="flex flex-col md:flex-row gap-2 sm:gap-4 h-[calc(100vh-140px)] md:h-[calc(100vh-108px)]">
        {/* Mobile Sidebar Overlay */}
        {showMobileSidebar && (
          <div
            className="fixed inset-0 z-40 bg-black/50 md:hidden"
            onClick={() => setShowMobileSidebar(false)}
          />
        )}

        {/* Sidebar */}
        <div
          className={`
          fixed md:relative z-50 md:z-auto
          inset-y-0 left-0
          w-72 md:w-auto md:h-full
          transition-transform duration-300 ease-in-out
            ${showMobileSidebar ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}
        `}
        >
          <Sidebar
            documents={documents}
            activeDoc={activeDoc}
            setActiveDoc={handleSelectDoc}
            addNewDocument={handleAddNewDocument}
            deleteDocument={handleDeleteDocument}
            updateDocTitle={handleUpdateDocTitle}
            glassClass={glassClass}
            hoverClass={hoverClass}
            textClass={textClass}
            theme={theme}
            isCollapsed={sidebarCollapsed}
            onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
            isSaving={isSaving}
            lastSaved={lastSaved}
          />
        </div>

        {/* Main Content Area */}
        <div className="flex flex-col flex-1 gap-2 overflow-hidden md:flex-row md:gap-4">
          {documents.length === 0 ? (
            <EmptyState
              onCreateDocument={handleAddNewDocument}
              glassClass={glassClass}
            />
          ) : (
            <>
              {/* Editor */}
              <div className="flex-1 min-h-0">
                <Editor
                  key={activeDoc}
                  currentDoc={currentDoc}
                  updateDocContent={handleUpdateDocContent}
                  onTextSelection={handleTextSelection}
                  onShowAIPanel={() => setShowAIPanel(true)}
                  glassClass={glassClass}
                  textClass={textClass}
                  onEditorReady={setEditorInstance}
                  isSaving={isSaving}
                  lastSaved={lastSaved}
                  onManualSave={handleManualSave}
                />
              </div>

              {/* Toolbar */}
              <Toolbar
                editor={editorInstance}
                currentDoc={currentDoc}
                glassClass={glassClass}
                hoverClass={hoverClass}
                updateDocContent={handleUpdateDocContent}
                onFileUpload={handleFileUploadWithToast}
                showToast={showToast}
                isCollapsed={toolbarCollapsed}
                onToggleCollapse={() => setToolbarCollapsed(!toolbarCollapsed)}
              />
            </>
          )}
        </div>

        {/* AI Panel */}
        {showAIPanel && (
          <AIPanel
            documentId={activeDoc}
            selectedText={selectedText}
            onClose={() => setShowAIPanel(false)}
            glassClass={glassClass}
            hoverClass={hoverClass}
            textClass={textClass}
          />
        )}
      </div>

      {/* Toast Notifications */}
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          duration={toast.duration}
          onClose={hideToast}
        />
      )}
    </div>
  );
}
