import React, { useEffect, useState, useMemo, useRef } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import TextSelectionTooltip from '../../components/TextSelectionTooltip';
import EditorStatsBar from './EditorStatsBar';
import { getEditorExtensions, handleImagePaste } from './extensions';
import { useEditorKeyboard } from './useEditorKeyboard';
import { DEFAULT_FONT_FAMILY, DEFAULT_FONT_SIZE } from '../../constants/editor';
import 'tiptap-extension-resizable-image/styles.css';

export default function Editor({
  currentDoc,
  updateDocContent,
  onTextSelection,
  onShowAIPanel,
  glassClass,
  textClass,
  onEditorReady,
  isSaving,
  lastSaved,
  onManualSave,
}) {
  const [wordCount, setWordCount] = useState(0);
  const [charCount, setCharCount] = useState(0);
  const [tooltipPosition, setTooltipPosition] = useState(null);
  const [showScrollToTop, setShowScrollToTop] = useState(false);
  const scrollContainerRef = useRef(null);
  const isLoadingContentRef = useRef(false);

  // Handle Ctrl+S / Cmd+S for manual save
  useEditorKeyboard(onManualSave);

  // Memoize extensions to prevent duplicate registration
  const extensions = useMemo(() => getEditorExtensions(), []);

  // Initialize TipTap editor
  const editor = useEditor({
    extensions,
    content: '',
    immediatelyRender: false, // Prevents flushSync warning during SSR/initial render
    editorProps: {
      attributes: {
        class: `focus:outline-none ${textClass}`,
        style: `font-size: ${DEFAULT_FONT_SIZE}px; font-family: ${DEFAULT_FONT_FAMILY};`,
      },
      handlePaste: handleImagePaste,
    },
    onUpdate: ({ editor }) => {
      // Don't trigger update if we're just loading content
      if (isLoadingContentRef.current) {
        updateCounts(editor);
        return;
      }
      const json = editor.getJSON();
      updateDocContent(json);
      updateCounts(editor);
    },
    onSelectionUpdate: ({ editor }) => {
      handleSelectionUpdate(editor);
    },
  });

  // Update word and character counts
  const updateCounts = (editor) => {
    const text = editor.getText();
    const cleanText = text.trim();
    const words = cleanText.split(/\s+/).filter((word) => word.length > 0);
    setWordCount(words.length);
    setCharCount(cleanText.length);
  };

  // Handle text selection for AI tooltip
  const handleSelectionUpdate = (editor) => {
    const { from, to } = editor.state.selection;
    const text = editor.state.doc.textBetween(from, to, ' ').trim();

    if (text && onTextSelection) {
      onTextSelection(text);

      const editorElement = editor.view.dom;
      const rect = editorElement.getBoundingClientRect();
      setTooltipPosition({
        x: rect.left + rect.width / 2,
        y: rect.top + window.scrollY,
      });
    } else {
      setTooltipPosition(null);
    }
  };

  // Notify parent when editor is ready
  useEffect(() => {
    if (editor && onEditorReady) {
      onEditorReady(editor);
    }
  }, [editor, onEditorReady]);

  // Handle scroll to top button visibility
  useEffect(() => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer) return;

    const handleScroll = () => {
      const scrollTop = scrollContainer.scrollTop;
      setShowScrollToTop(scrollTop > 300); // Show button after scrolling 300px
    };

    scrollContainer.addEventListener('scroll', handleScroll);
    
    // Check initial scroll position
    handleScroll();

    return () => {
      scrollContainer.removeEventListener('scroll', handleScroll);
    };
  }, [editor]);

  // Scroll to top function
  const scrollToTop = () => {
    const scrollContainer = scrollContainerRef.current;
    if (scrollContainer) {
      scrollContainer.scrollTo({
        top: 0,
        behavior: 'smooth',
      });
    }
  };

  // Load document content when currentDoc changes
  useEffect(() => {
    if (editor && currentDoc) {
      // Set flag to prevent updateDocContent from moving document to top
      isLoadingContentRef.current = true;
      
      // Defer content setting to avoid flushSync warning
      const timeoutId = setTimeout(() => {
        if (editor && !editor.isDestroyed) {
          const content = parseDocumentContent(currentDoc.content);
          editor.commands.setContent(content, false);
          updateCounts(editor);
          editor.commands.focus('end');
          
          // Reset flag after a short delay to allow any pending updates to complete
          setTimeout(() => {
            isLoadingContentRef.current = false;
          }, 100);
        } else {
          isLoadingContentRef.current = false;
        }
      }, 0);
      
      return () => {
        clearTimeout(timeoutId);
        isLoadingContentRef.current = false;
      };
    }
  }, [currentDoc?.id, editor]);


  const handleAskAI = () => {
    setTooltipPosition(null);
    onShowAIPanel?.();
  };

  if (!editor) {
    return (
      <div className="flex-1 flex items-center justify-center text-[var(--color-text-muted)]">
        Loading editor...
      </div>
    );
  }

  return (
    <>
      <TextSelectionTooltip position={tooltipPosition} onAskAI={handleAskAI} />

      <div
        className={`h-full ${glassClass} rounded-lg flex flex-col overflow-hidden`}
      >
        <EditorStatsBar
          currentDoc={currentDoc}
          wordCount={wordCount}
          charCount={charCount}
          isSaving={isSaving}
          lastSaved={lastSaved}
        />

        <div className="flex flex-col flex-1 overflow-hidden relative">
          <div
            ref={scrollContainerRef}
            className="flex-1 w-full px-2 py-4 overflow-auto scroll-container"
          >
            <EditorContent
              editor={editor}
              className="w-full tiptap-editor"
            />
          </div>
          
          {/* Scroll to Top Button */}
          {showScrollToTop && (
            <button
              onClick={scrollToTop}
              className="absolute bottom-6 right-6 z-10 p-3 rounded-full bg-[var(--color-bg-elevated)] border border-[var(--color-border-light)] shadow-lg hover:shadow-xl transition-all duration-200 hover:scale-110 active:scale-95 group"
              aria-label="Scroll to top"
              title="Scroll to top"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                className="h-5 w-5 text-[var(--color-text-primary)] group-hover:text-[var(--color-accent-primary)] transition-colors"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M5 10l7-7m0 0l7 7m-7-7v18"
                />
              </svg>
            </button>
          )}
        </div>
      </div>
    </>
  );
}

// Helper to parse document content
function parseDocumentContent(content) {
  if (typeof content === 'object' && content !== null) {
    return content;
  }

  if (typeof content === 'string') {
    try {
      return JSON.parse(content);
    } catch {
      return {
        type: 'doc',
        content: [
          {
            type: 'paragraph',
            content: content ? [{ type: 'text', text: content }] : [],
          },
        ],
      };
    }
  }

  return {
    type: 'doc',
    content: [{ type: 'paragraph' }],
  };
}
