import { useState, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import Editor from './components/Editor';
import Toolbar from './components/Toolbar';
import AIPanel from './components/AIPanel';
import Toast from './components/Toast';
import { useAuth } from './context/AuthContext';
import { API_URL } from './config';

export default function AppContent() {
  const { user, logout } = useAuth();
  const [documents, setDocuments] = useState([]);
  const [activeDoc, setActiveDoc] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'light');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [toolbarCollapsed, setToolbarCollapsed] = useState(false);
  const [selectedText, setSelectedText] = useState('');
  const [showAIPanel, setShowAIPanel] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [isExporting, setIsExporting] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const editorRef = useRef(null);

  useEffect(() => {
    loadDocuments();
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    localStorage.setItem('theme', theme);
  }, [theme]);

  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash.slice(1);
      if (hash && documents.length > 0) {
        const doc = documents.find(d => d.id === hash);
        if (doc) {
          setActiveDoc(hash);
        }
      }
    };

    window.addEventListener('hashchange', handleHashChange);
    handleHashChange();

    return () => window.removeEventListener('hashchange', handleHashChange);
  }, [documents]);

  const showToast = (message, type = 'info') => {
    const id = Date.now();
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 3000);
  };

  const loadDocuments = async () => {
    try {
      const response = await fetch(`${API_URL}/api/documents`, {
        credentials: 'include'
      });
      
      if (response.ok) {
        const docs = await response.json();
        
        if (docs.length === 0) {
          setDocuments([]);
          setActiveDoc(null);
        } else {
          setDocuments(docs);
          if (!activeDoc && docs.length > 0) {
            setActiveDoc(docs[0].id);
            window.location.hash = docs[0].id;
          }
        }
      }
    } catch (error) {
      console.error('Failed to load documents:', error);
      showToast('Failed to load documents', 'error');
    }
  };

  const addNewDocument = async () => {
    showToast('Creating document...', 'info');
    
    const newDoc = {
      id: Date.now().toString(),
      title: 'Untitled Document',
      content: '',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    };

    try {
      const response = await fetch(`${API_URL}/api/documents`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(newDoc)
      });

      if (response.ok) {
        setDocuments(prev => [newDoc, ...prev]);
        setActiveDoc(newDoc.id);
        window.location.hash = newDoc.id;
        showToast('Document created', 'success');
      } else {
        showToast('Failed to create document', 'error');
      }
    } catch (error) {
      console.error('Failed to create document:', error);
      showToast('Failed to create document', 'error');
    }
  };

  const deleteDocument = async (id) => {
    if (documents.length === 1) {
      showToast('Cannot delete the last document', 'error');
      return;
    }

    if (!confirm('Are you sure you want to delete this document?')) return;

    showToast('Deleting document...', 'info');

    try {
      const response = await fetch(`${API_URL}/api/documents/${id}`, {
        method: 'DELETE',
        credentials: 'include'
      });

      if (response.ok) {
        setDocuments(prev => prev.filter(doc => doc.id !== id));
        if (activeDoc === id) {
          const remainingDocs = documents.filter(doc => doc.id !== id);
          if (remainingDocs.length > 0) {
            setActiveDoc(remainingDocs[0].id);
            window.location.hash = remainingDocs[0].id;
          } else {
            setActiveDoc(null);
            window.location.hash = '';
          }
        }
        showToast('Document deleted', 'success');
      } else {
        showToast('Failed to delete document', 'error');
      }
    } catch (error) {
      console.error('Failed to delete document:', error);
      showToast('Failed to delete document', 'error');
    }
  };

  const updateDocContent = async (id, content) => {
    const doc = documents.find(d => d.id === id);
    if (!doc) return;

    const updatedDoc = { ...doc, content, updated_at: new Date().toISOString() };
    
    setDocuments(prev => {
      const filtered = prev.filter(d => d.id !== id);
      return [updatedDoc, ...filtered];
    });

    try {
      await fetch(`${API_URL}/api/documents/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(updatedDoc)
      });
    } catch (error) {
      console.error('Failed to save document:', error);
    }
  };

  const updateDocTitle = async (id, title) => {
    const doc = documents.find(d => d.id === id);
    if (!doc) return;

    const updatedDoc = { ...doc, title, updated_at: new Date().toISOString() };
    
    setDocuments(prev => {
      const filtered = prev.filter(d => d.id !== id);
      return [updatedDoc, ...filtered];
    });

    try {
      await fetch(`${API_URL}/api/documents/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(updatedDoc)
      });
    } catch (error) {
      console.error('Failed to update title:', error);
    }
  };

  const handleTextSelection = (text) => {
    setSelectedText(text);
  };

  const handleAskAI = () => {
    if (selectedText) {
      setShowAIPanel(true);
    }
  };

  const handleFileUpload = async (file) => {
    setIsUploading(true);
    showToast('Uploading file...', 'info');

    try {
      let content = '';
      let title = file.name.replace(/\.(docx|txt)$/, '');

      if (file.name.endsWith('.txt')) {
        content = await file.text();
      } else if (file.name.endsWith('.docx')) {
        const mammoth = (await import('mammoth')).default;
        const arrayBuffer = await file.arrayBuffer();
        const result = await mammoth.convertToHtml({ arrayBuffer });
        content = result.value;
      }

      const newDoc = {
        id: Date.now().toString(),
        title,
        content,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
      };

      const response = await fetch(`${API_URL}/api/documents`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(newDoc)
      });

      if (response.ok) {
        setDocuments(prev => [newDoc, ...prev]);
        setActiveDoc(newDoc.id);
        window.location.hash = newDoc.id;
        showToast('File uploaded successfully', 'success');
      } else {
        showToast('Failed to upload file', 'error');
      }
    } catch (error) {
      console.error('Upload error:', error);
      showToast('Failed to upload file', 'error');
    } finally {
      setIsUploading(false);
    }
  };

  const currentDoc = documents.find(d => d.id === activeDoc);

  return (
    <div className={`h-screen flex overflow-hidden ${theme === 'dark' ? 'dark' : ''}`}>
      <Sidebar
        documents={documents}
        activeDoc={activeDoc}
        setActiveDoc={setActiveDoc}
        addNewDocument={addNewDocument}
        deleteDocument={deleteDocument}
        updateDocTitle={updateDocTitle}
        collapsed={sidebarCollapsed}
        setCollapsed={setSidebarCollapsed}
        theme={theme}
        setTheme={setTheme}
        user={user}
        onLogout={logout}
      />

      <div className="flex-1 flex flex-col overflow-hidden">
        {documents.length === 0 ? (
          <div className="flex-1 flex items-center justify-center bg-white dark:bg-gray-900">
            <div className="text-center">
              <p className="text-2xl font-bold text-gray-800 dark:text-gray-200 mb-4">
                No Documents Yet
              </p>
              <p className="text-gray-600 dark:text-gray-400 mb-8">
                Create your first document to get started
              </p>
              <button
                onClick={addNewDocument}
                className="px-6 py-3 bg-black dark:bg-white text-white dark:text-black hover:bg-gray-800 dark:hover:bg-gray-200 transition-colors"
              >
                Create New Document
              </button>
            </div>
          </div>
        ) : (
          <>
            <Toolbar
              collapsed={toolbarCollapsed}
              setCollapsed={setToolbarCollapsed}
              editorRef={editorRef}
              onFileUpload={handleFileUpload}
              onAskAI={handleAskAI}
              showToast={showToast}
              currentDoc={currentDoc}
              isExporting={isExporting}
              isUploading={isUploading}
            />

            <div className="flex-1 flex overflow-hidden">
              <Editor
                content={currentDoc?.content || ''}
                onContentChange={(content) => updateDocContent(activeDoc, content)}
                onTextSelection={handleTextSelection}
                onAskAI={handleAskAI}
                editorRef={editorRef}
                theme={theme}
              />

              {showAIPanel && (
                <AIPanel
                  selectedText={selectedText}
                  onClose={() => setShowAIPanel(false)}
                />
              )}
            </div>
          </>
        )}
      </div>

      <Toast toasts={toasts} />
    </div>
  );
}

