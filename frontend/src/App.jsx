import React, { useState, useEffect } from 'react';
import { Moon, Sun } from 'lucide-react';
import Sidebar from './components/Sidebar';
import Editor from './components/Editor';
import Toolbar from './components/Toolbar';
import TemplateSelector from './components/TemplateSelector';
import AIPanel from './components/AIPanel';
import * as api from './services/api';
import { templates } from './utils/templates';

export default function App() {
  const [theme, setTheme] = useState('light');
  const [documents, setDocuments] = useState([]);
  const [activeDoc, setActiveDoc] = useState(null);
  const [pageTemplate, setPageTemplate] = useState('blank');
  const [showTemplates, setShowTemplates] = useState(false);
  const [showAIPanel, setShowAIPanel] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedText, setSelectedText] = useState('');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [toolbarCollapsed, setToolbarCollapsed] = useState(false);

  // Load documents on mount
  useEffect(() => {
    loadDocuments();
  }, []);

  const loadDocuments = async () => {
    try {
      const docs = await api.fetchDocuments();
      if (docs.length === 0) {
        // Create welcome document if none exist
        const welcomeDoc = {
          id: Date.now().toString(),
          title: 'Welcome Note',
          content: '<h2>Welcome to SimpleNote!</h2><p>Start creating your notes here...</p>',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString()
        };
        await api.createDocument(welcomeDoc);
        setDocuments([welcomeDoc]);
        setActiveDoc(welcomeDoc.id);
      } else {
        setDocuments(docs);
        setActiveDoc(docs[0].id);
      }
    } catch (error) {
      console.error('Failed to load documents:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const currentDoc = documents.find(doc => doc.id === activeDoc);

  const addNewDocument = async () => {
    const newDoc = {
      id: Date.now().toString(),
      title: `Untitled ${documents.length + 1}`,
      content: '',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    };

    try {
      await api.createDocument(newDoc);
      setDocuments([newDoc, ...documents]);
      setActiveDoc(newDoc.id);
    } catch (error) {
      console.error('Failed to create document:', error);
    }
  };

  const deleteDocument = async (id) => {
    if (documents.length === 1) return;

    try {
      await api.deleteDocument(id);
      const filtered = documents.filter(doc => doc.id !== id);
      setDocuments(filtered);
      if (activeDoc === id) {
        setActiveDoc(filtered[0].id);
      }
    } catch (error) {
      console.error('Failed to delete document:', error);
    }
  };

  const updateDocContent = async (content) => {
    if (!currentDoc) return;

    const now = new Date().toISOString();
    const updatedDoc = { ...currentDoc, content, updated_at: now };
    
    // Update and move to top
    setDocuments(docs => {
      const filtered = docs.filter(doc => doc.id !== activeDoc);
      return [updatedDoc, ...filtered];
    });

    // Debounced save to backend
    try {
      await api.updateDocument(activeDoc, { title: currentDoc.title, content });
    } catch (error) {
      console.error('Failed to update document:', error);
    }
  };

  const updateDocTitle = async (id, newTitle) => {
    const doc = documents.find(d => d.id === id);
    if (!doc) return;

    const now = new Date().toISOString();
    const updatedDoc = { ...doc, title: newTitle, updated_at: now };
    
    // Update and move to top
    setDocuments(docs => {
      const filtered = docs.filter(d => d.id !== id);
      return [updatedDoc, ...filtered];
    });

    try {
      await api.updateDocument(id, { title: newTitle, content: doc.content });
    } catch (error) {
      console.error('Failed to update title:', error);
    }
  };

  const applyTemplate = (templateKey) => {
    if (currentDoc) {
      const content = templates[templateKey].content;
      updateDocContent(content);
      setPageTemplate(templateKey);
      setShowTemplates(false);
    }
  };

  const handleTextSelection = (text) => {
    setSelectedText(text);
    if (text.length > 0) {
      setShowAIPanel(true);
    }
  };

  // Apply theme to document
  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  const bgClass = 'bg-[var(--color-bg-secondary)]';
  const glassClass = 'glass';
  const textClass = 'text-[var(--color-text-primary)]';
  const hoverClass = 'hover:bg-[var(--color-hover)] transition-all duration-150';

  if (isLoading) {
    return (
      <div className={`min-h-screen ${bgClass} flex items-center justify-center`}>
        <div className={`${glassClass} rounded-3xl p-12 animate-fade-in`}>
          <div className="flex flex-col items-center gap-4">
            <div className="w-12 h-12 border-4 border-[var(--color-accent-primary)] border-t-transparent rounded-full animate-spin"></div>
            <p className={`${textClass} text-lg font-medium`}>Loading your notes...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`min-h-screen ${bgClass} ${textClass} p-4 transition-all duration-300`}>
      {/* Top Bar */}
      <div className={`${glassClass} rounded-lg p-3 mb-4 flex justify-between items-center relative z-50 border-b border-[var(--color-border-medium)]`}>
        <div className="flex items-center gap-4">
          <h1 className="text-2xl font-bold tracking-tight">
            SimpleNote
          </h1>
          <div className="h-6 w-px bg-[var(--color-border-light)]"></div>
          <TemplateSelector
            templates={templates}
            pageTemplate={pageTemplate}
            showTemplates={showTemplates}
            setShowTemplates={setShowTemplates}
            applyTemplate={applyTemplate}
            glassClass={glassClass}
            hoverClass={hoverClass}
          />
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowAIPanel(!showAIPanel)}
            className={`px-3 py-1.5 rounded ${hoverClass} text-xs font-semibold flex items-center gap-2 border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
          >
            <span className="text-sm">✨</span>
            <span className="hidden sm:inline">AI Tools</span>
          </button>
          <button
            onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}
            className={`p-2 rounded ${hoverClass} border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
          >
            {theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}
          </button>
        </div>
      </div>

      <div className="flex gap-4 h-[calc(100vh-108px)]">
        {/* Sidebar */}
        <Sidebar
          documents={documents}
          activeDoc={activeDoc}
          setActiveDoc={setActiveDoc}
          addNewDocument={addNewDocument}
          deleteDocument={deleteDocument}
          updateDocTitle={updateDocTitle}
          glassClass={glassClass}
          hoverClass={hoverClass}
          textClass={textClass}
          theme={theme}
          isCollapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        />

        {/* Editor */}
        <Editor
          currentDoc={currentDoc}
          updateDocContent={updateDocContent}
          onTextSelection={handleTextSelection}
          glassClass={glassClass}
          textClass={textClass}
        />

        {/* Right Toolbar */}
        <Toolbar
          glassClass={glassClass}
          hoverClass={hoverClass}
          updateDocContent={updateDocContent}
          isCollapsed={toolbarCollapsed}
          onToggleCollapse={() => setToolbarCollapsed(!toolbarCollapsed)}
        />

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
    </div>
  );
}

