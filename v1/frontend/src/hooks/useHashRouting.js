import { useEffect } from 'react';

export function useHashRouting(activeDoc, documents, setActiveDoc) {
  // Sync URL with active document
  useEffect(() => {
    if (activeDoc) {
      window.location.hash = `#doc/${activeDoc}`;
    }
  }, [activeDoc]);

  // Handle hash change for routing
  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash;
      if (hash.startsWith('#doc/')) {
        const docId = hash.replace('#doc/', '');
        if (documents.find((doc) => doc.id === docId)) {
          setActiveDoc(docId);
        }
      }
    };

    window.addEventListener('hashchange', handleHashChange);

    // Check initial hash on load
    if (documents.length > 0) {
      handleHashChange();
    }

    return () => window.removeEventListener('hashchange', handleHashChange);
  }, [documents, setActiveDoc]);
}

