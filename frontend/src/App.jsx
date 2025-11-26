import React, { useState, useEffect, useRef, useCallback } from "react";
import { Moon, Sun, LogOut, User, Menu, X } from "lucide-react";
import { useAuth } from "./context/AuthContext";
import Sidebar from "./components/Sidebar";
import Editor from "./components/Editor";
import Toolbar from "./components/Toolbar";
import AIPanel from "./components/AIPanel";
import Toast from "./components/Toast";
import * as api from "./services/api";

export default function App() {
  const { user, logout } = useAuth();
  const [theme, setTheme] = useState("light");
  const [documents, setDocuments] = useState([]);
  const [activeDoc, setActiveDoc] = useState(null);
  const [showAIPanel, setShowAIPanel] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedText, setSelectedText] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [toolbarCollapsed, setToolbarCollapsed] = useState(false);
  const [toast, setToast] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [lastSaved, setLastSaved] = useState(null);
  const [showMobileSidebar, setShowMobileSidebar] = useState(false);
  const [fontFamily, setFontFamily] = useState(
    "system-ui, -apple-system, sans-serif"
  );
  const [fontSize, setFontSize] = useState(16);
  const [editorInstance, setEditorInstance] = useState(null);

  // Ref for debouncing document saves
  const saveTimeoutRef = useRef(null);

  const handleLogout = async () => {
    await logout();
    window.location.href = "/";
  };

  // Load documents on mount
  useEffect(() => {
    loadDocuments();
  }, []);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
    };
  }, []);

  // Hash-based routing: sync URL with active document
  useEffect(() => {
    if (activeDoc) {
      window.location.hash = `#doc/${activeDoc}`;
    }
  }, [activeDoc]);

  // Handle hash change for routing
  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash;
      if (hash.startsWith("#doc/")) {
        const docId = hash.replace("#doc/", "");
        if (documents.find((doc) => doc.id === docId)) {
          setActiveDoc(docId);
        }
      }
    };

    window.addEventListener("hashchange", handleHashChange);

    // Check initial hash on load
    if (documents.length > 0) {
      handleHashChange();
    }

    return () => window.removeEventListener("hashchange", handleHashChange);
  }, [documents]);

  const loadDocuments = async () => {
    try {
      const docs = await api.fetchDocuments();
      setDocuments(docs);

      if (docs.length > 0) {
        // Check if there's a hash in URL
        const hash = window.location.hash;
        if (hash.startsWith("#doc/")) {
          const docId = hash.replace("#doc/", "");
          const doc = docs.find((d) => d.id === docId);
          setActiveDoc(doc ? docId : docs[0].id);
        } else {
          setActiveDoc(docs[0].id);
        }
      } else {
        setActiveDoc(null);
      }
    } catch (error) {
      console.error("Failed to load documents:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const currentDoc = documents.find((doc) => doc.id === activeDoc);

  const addNewDocument = async () => {
    const newDoc = {
      id: Date.now().toString(),
      title: `Untitled ${documents.length + 1}`,
      content: "",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    showToast("Creating new document...", "loading", 0);

    try {
      await api.createDocument(newDoc);
      setDocuments([newDoc, ...documents]);
      setActiveDoc(newDoc.id);
      showToast(`"${newDoc.title}" created successfully!`, "success");
    } catch (error) {
      console.error("Failed to create document:", error);
      showToast("Failed to create document. Please try again.", "error");
    }
  };

  const deleteDocument = async (id) => {
    if (documents.length === 1) {
      showToast("Cannot delete the last document", "error");
      return;
    }

    const docToDelete = documents.find((doc) => doc.id === id);
    showToast(`Deleting "${docToDelete?.title}"...`, "loading", 0);

    try {
      await api.deleteDocument(id);
      const filtered = documents.filter((doc) => doc.id !== id);
      setDocuments(filtered);
      if (activeDoc === id) {
        setActiveDoc(filtered[0].id);
      }
      showToast(`"${docToDelete?.title}" deleted successfully`, "success");
    } catch (error) {
      console.error("Failed to delete document:", error);
      showToast("Failed to delete document. Please try again.", "error");
    }
  };

  // Manual save function (called on Ctrl+S)
  const manualSave = useCallback(async () => {
    if (!currentDoc || !activeDoc) return;

    // Clear any pending debounced save
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
      saveTimeoutRef.current = null;
    }

    // Save immediately
    setIsSaving(true);
    try {
      await api.updateDocument(activeDoc, { 
        title: currentDoc.title, 
        content: currentDoc.content 
      });
      console.log("Document saved successfully");
      setLastSaved(new Date());
      setToast({ message: "Document saved successfully", type: "success", duration: 2000 });
    } catch (error) {
      console.error("Failed to save document:", error);
      setToast({ message: "Failed to save document", type: "error", duration: 3000 });
    } finally {
      setIsSaving(false);
    }
  }, [currentDoc, activeDoc]);

  const updateDocContent = useCallback(async (content) => {
    if (!currentDoc) return;

    const now = new Date().toISOString();
    const updatedDoc = { ...currentDoc, content, updated_at: now };

    // Update local state immediately for responsive UI
    setDocuments((docs) => {
      const filtered = docs.filter((doc) => doc.id !== activeDoc);
      return [updatedDoc, ...filtered];
    });

    // Clear existing timeout
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }

    // Show saving indicator
    setIsSaving(true);
    setLastSaved(null);

    // Debounce the actual API call by 1 second
    saveTimeoutRef.current = setTimeout(async () => {
      try {
        await api.updateDocument(activeDoc, { title: currentDoc.title, content });
        console.log("Document saved successfully");
        setLastSaved(new Date());
      } catch (error) {
        console.error("Failed to update document:", error);
        setToast({ message: "Failed to save document", type: "error", duration: 3000 });
      } finally {
        setIsSaving(false);
      }
    }, 1000); // Wait 1 second after last keystroke before saving
  }, [currentDoc, activeDoc]);

  const updateDocTitle = async (id, newTitle) => {
    const doc = documents.find((d) => d.id === id);
    if (!doc) return;

    const now = new Date().toISOString();
    const updatedDoc = { ...doc, title: newTitle, updated_at: now };

    // Update and move to top
    setDocuments((docs) => {
      const filtered = docs.filter((d) => d.id !== id);
      return [updatedDoc, ...filtered];
    });

    try {
      await api.updateDocument(id, { title: newTitle, content: doc.content });
      showToast("Document title updated", "success", 2000);
    } catch (error) {
      console.error("Failed to update title:", error);
      showToast("Failed to update title", "error", 2000);
    }
  };

  const showToast = (message, type = "info", duration = 3000) => {
    setToast({ message, type, duration });
  };

  const handleFileUpload = async (title, content) => {
    showToast("Uploading file...", "loading", 0);

    const newDoc = {
      id: Date.now().toString(),
      title: title,
      content: content,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    try {
      await api.createDocument(newDoc);
      setDocuments([newDoc, ...documents]);
      setActiveDoc(newDoc.id);
      showToast(`"${title}" uploaded successfully!`, "success", 4000);
    } catch (error) {
      console.error("Failed to create document from file:", error);
      showToast("Failed to upload file. Please try again.", "error", 4000);
      throw error;
    }
  };

  const handleTextSelection = (text) => {
    setSelectedText(text);
    // Don't auto-open AI panel - let user click "Ask AI" button instead
  };

  // Apply theme to document
  useEffect(() => {
    if (theme === "dark") {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }, [theme]);

  const bgClass = "bg-[var(--color-bg-secondary)]";
  const glassClass = "glass";
  const textClass = "text-[var(--color-text-primary)]";
  const hoverClass =
    "hover:bg-[var(--color-hover)] transition-all duration-150";

  if (isLoading) {
    return (
      <div
        className={`min-h-screen ${bgClass} flex items-center justify-center`}
      >
        <div className={`${glassClass} rounded-3xl p-12 animate-fade-in`}>
          <div className="flex flex-col items-center gap-4">
            <div className="w-12 h-12 border-4 border-[var(--color-accent-primary)] border-t-transparent rounded-full animate-spin"></div>
            <p className={`${textClass} text-lg font-medium`}>
              Loading your notes...
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`min-h-screen ${bgClass} ${textClass} p-2 sm:p-4 transition-all duration-300`}
    >
      {/* Top Bar - Responsive */}
      <div
        className={`${glassClass} rounded-lg p-2 sm:p-3 mb-2 sm:mb-4 flex justify-between items-center relative z-50 border-b border-[var(--color-border-medium)]`}
      >
        <div className="flex items-center gap-2 sm:gap-4">
          {/* Mobile Hamburger Menu */}
          <button
            onClick={() => setShowMobileSidebar(!showMobileSidebar)}
            className={`md:hidden p-1.5 rounded ${hoverClass} border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
            title="Toggle Sidebar"
          >
            {showMobileSidebar ? <X size={18} /> : <Menu size={18} />}
          </button>

          <h1 className="text-lg sm:text-2xl font-bold tracking-tight">
            SimpleNote
          </h1>
          {currentDoc && (
            <>
              <div className="hidden md:block h-6 w-px bg-[var(--color-border-light)]"></div>
              <div className="hidden md:block text-sm text-[var(--color-text-muted)]">
                {documents.length}{" "}
                {documents.length === 1 ? "document" : "documents"}
              </div>
            </>
          )}
        </div>
        <div className="flex items-center gap-1 sm:gap-2">
          {/* AI Tools Button */}
          <button
            onClick={() => setShowAIPanel(!showAIPanel)}
            className={`px-2 sm:px-3 py-1.5 rounded ${hoverClass} text-xs font-semibold flex items-center gap-1 sm:gap-2 border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
          >
            <span className="text-sm">✨</span>
            <span className="hidden sm:inline">AI Tools</span>
          </button>

          {/* Theme Toggle */}
          <button
            onClick={() => setTheme(theme === "light" ? "dark" : "light")}
            className={`p-1.5 sm:p-2 rounded ${hoverClass} border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
            title={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
          >
            {theme === "light" ? (
              <Moon size={16} className="sm:w-[18px] sm:h-[18px]" />
            ) : (
              <Sun size={16} className="sm:w-[18px] sm:h-[18px]" />
            )}
          </button>

          {/* Account Info - Responsive */}
          {user && (
            <>
              <div className="hidden sm:block h-6 w-px bg-[var(--color-border-light)]"></div>
              <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 text-xs">
                <User size={16} className="text-[var(--color-text-muted)]" />
                <span className="text-[var(--color-text-secondary)] font-medium truncate max-w-[150px]">
                  {user.email}
                </span>
              </div>
              <button
                onClick={handleLogout}
                className={`px-2 sm:px-3 py-1.5 rounded ${hoverClass} text-xs font-semibold flex items-center gap-1 sm:gap-2 border border-[var(--color-border-medium)] hover:border-red-500 hover:text-red-500 transition-colors`}
                title={`Logout ${user.email}`}
              >
                <LogOut size={16} />
                <span className="hidden sm:inline">Logout</span>
              </button>
            </>
          )}
        </div>
      </div>

      <div className="flex flex-col md:flex-row gap-2 sm:gap-4 h-[calc(100vh-80px)] sm:h-[calc(100vh-108px)]">
        {/* Mobile Sidebar Overlay */}
        {showMobileSidebar && (
          <div
            className="fixed inset-0 bg-black/50 z-40 md:hidden"
            onClick={() => setShowMobileSidebar(false)}
          />
        )}

        {/* Sidebar - Desktop: Always visible, Mobile: Slide-in overlay */}
        <div
          className={`
          fixed md:relative z-50 md:z-auto
          inset-y-0 left-0
          w-72 md:w-auto md:h-full
          transition-transform duration-300 ease-in-out
          ${
            showMobileSidebar
              ? "translate-x-0"
              : "-translate-x-full md:translate-x-0"
          }
        `}
        >
          <Sidebar
            documents={documents}
            activeDoc={activeDoc}
            setActiveDoc={(docId) => {
              setActiveDoc(docId);
              setShowMobileSidebar(false); // Close mobile sidebar on selection
            }}
            addNewDocument={() => {
              addNewDocument();
              setShowMobileSidebar(false);
            }}
            deleteDocument={deleteDocument}
            updateDocTitle={updateDocTitle}
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

        {/* Main Content Area - Mobile: Flex Column (Editor + Toolbar), Desktop: Flex Row */}
        <div className="flex flex-col md:flex-row flex-1 gap-2 md:gap-4 overflow-hidden">
          {/* Editor or No Documents State */}
          {documents.length === 0 ? (
            <div
              className={`flex-1 ${glassClass} rounded-lg flex flex-col items-center justify-center gap-6 p-12`}
            >
              <div className="text-6xl opacity-30">📝</div>
              <div className="text-center">
                <h2 className="text-2xl font-bold mb-2 text-[var(--color-text-primary)]">
                  No Documents Yet
                </h2>
                <p className="text-[var(--color-text-muted)] mb-6">
                  Create your first document to get started
                </p>
                <button
                  onClick={addNewDocument}
                  className={`px-6 py-3 rounded-lg bg-[var(--color-accent-primary)] text-[var(--color-bg-primary)] font-semibold hover:opacity-80 transition-all shadow-lg`}
                >
                  Create New Document
                </button>
              </div>
            </div>
          ) : (
            <>
              {/* Editor - Takes remaining space */}
              <div className="flex-1 min-h-0">
                <Editor
                  key={activeDoc}
                  currentDoc={currentDoc}
                  updateDocContent={updateDocContent}
                  onTextSelection={handleTextSelection}
                  onShowAIPanel={() => setShowAIPanel(true)}
                  glassClass={glassClass}
                  textClass={textClass}
                  fontFamily={fontFamily}
                  fontSize={fontSize}
                  onEditorReady={setEditorInstance}
                  isSaving={isSaving}
                  lastSaved={lastSaved}
                  onManualSave={manualSave}
                />
              </div>

              {/* Toolbar */}
              <Toolbar
                editor={editorInstance}
                currentDoc={currentDoc}
                glassClass={glassClass}
                hoverClass={hoverClass}
                updateDocContent={updateDocContent}
                onFileUpload={handleFileUpload}
                showToast={showToast}
                isCollapsed={toolbarCollapsed}
                onToggleCollapse={() => setToolbarCollapsed(!toolbarCollapsed)}
                fontFamily={fontFamily}
                onFontChange={setFontFamily}
                fontSize={fontSize}
                onFontSizeChange={setFontSize}
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
          onClose={() => setToast(null)}
        />
      )}
    </div>
  );
}
