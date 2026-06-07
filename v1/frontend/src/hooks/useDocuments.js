import { useState, useCallback, useRef, useEffect } from 'react';
import * as api from '../services/api';

export function useDocuments() {
  const [documents, setDocuments] = useState([]);
  const [activeDoc, setActiveDoc] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [lastSaved, setLastSaved] = useState(null);
  const saveTimeoutRef = useRef(null);

  const currentDoc = documents.find((doc) => doc.id === activeDoc);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
    };
  }, []);

  const loadDocuments = async () => {
    try {
      const docs = await api.fetchDocuments();
      setDocuments(docs);

      if (docs.length > 0) {
        const hash = window.location.hash;
        if (hash.startsWith('#doc/')) {
          const docId = hash.replace('#doc/', '');
          const doc = docs.find((d) => d.id === docId);
          setActiveDoc(doc ? docId : docs[0].id);
        } else {
          setActiveDoc(docs[0].id);
        }
      } else {
        setActiveDoc(null);
      }
    } catch (error) {
      console.error('Failed to load documents:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const addNewDocument = async (showToast) => {
    const newDoc = {
      id: Date.now().toString(),
      title: `Untitled ${documents.length + 1}`,
      content: '',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    showToast?.('Creating new document...', 'loading', 0);

    try {
      await api.createDocument(newDoc);
      setDocuments([newDoc, ...documents]);
      setActiveDoc(newDoc.id);
      showToast?.(`"${newDoc.title}" created successfully!`, 'success');
      return newDoc;
    } catch (error) {
      console.error('Failed to create document:', error);
      showToast?.('Failed to create document. Please try again.', 'error');
      throw error;
    }
  };

  const deleteDocument = async (id, showToast) => {
    if (documents.length === 1) {
      showToast?.('Cannot delete the last document', 'error');
      return;
    }

    const docToDelete = documents.find((doc) => doc.id === id);
    showToast?.(`Deleting "${docToDelete?.title}"...`, 'loading', 0);

    try {
      await api.deleteDocument(id);
      const filtered = documents.filter((doc) => doc.id !== id);
      setDocuments(filtered);
      if (activeDoc === id) {
        setActiveDoc(filtered[0].id);
      }
      showToast?.(`"${docToDelete?.title}" deleted successfully`, 'success');
    } catch (error) {
      console.error('Failed to delete document:', error);
      showToast?.('Failed to delete document. Please try again.', 'error');
    }
  };

  const updateDocContent = useCallback(
    async (content, showToast, isUserEdit = true) => {
      if (!currentDoc) return;

      const now = new Date().toISOString();
      const updatedDoc = { ...currentDoc, content, updated_at: now };

      // Only move document to top when user actually edits (not when loading)
      if (isUserEdit) {
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

        // Debounce the actual API call by 5 seconds
        saveTimeoutRef.current = setTimeout(async () => {
          try {
            await api.updateDocument(activeDoc, { title: currentDoc.title, content });
            setLastSaved(new Date());
          } catch (error) {
            console.error('Failed to update document:', error);
            showToast?.('Failed to save document', 'error', 3000);
          } finally {
            setIsSaving(false);
          }
        }, 5000);
      } else {
        // Just update content in place without moving to top or triggering save
        setDocuments((docs) => {
          return docs.map((doc) => 
            doc.id === activeDoc ? updatedDoc : doc
          );
        });
      }
    },
    [currentDoc, activeDoc]
  );

  const updateDocTitle = async (id, newTitle, showToast) => {
    const doc = documents.find((d) => d.id === id);
    if (!doc) return;

    const now = new Date().toISOString();
    const updatedDoc = { ...doc, title: newTitle, updated_at: now };

    setDocuments((docs) => {
      const filtered = docs.filter((d) => d.id !== id);
      return [updatedDoc, ...filtered];
    });

    try {
      await api.updateDocument(id, { title: newTitle, content: doc.content });
      showToast?.('Document title updated', 'success', 2000);
    } catch (error) {
      console.error('Failed to update title:', error);
      showToast?.('Failed to update title', 'error', 2000);
    }
  };

  const manualSave = useCallback(
    async (showToast) => {
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
          content: currentDoc.content,
        });
        setLastSaved(new Date());
        showToast?.('Document saved successfully', 'success', 2000);
      } catch (error) {
        console.error('Failed to save document:', error);
        showToast?.('Failed to save document', 'error', 3000);
      } finally {
        setIsSaving(false);
      }
    },
    [currentDoc, activeDoc]
  );

  const handleFileUpload = async (title, content, showToast) => {
    showToast?.('Uploading file...', 'loading', 0);

    const newDoc = {
      id: Date.now().toString(),
      title,
      content,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    try {
      await api.createDocument(newDoc);
      setDocuments([newDoc, ...documents]);
      setActiveDoc(newDoc.id);
      showToast?.(`"${title}" uploaded successfully!`, 'success', 4000);
    } catch (error) {
      console.error('Failed to create document from file:', error);
      showToast?.('Failed to upload file. Please try again.', 'error', 4000);
      throw error;
    }
  };

  return {
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
  };
}

