import React, { useEffect, useState, useMemo } from 'react';
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

  // Load document content when currentDoc changes
  useEffect(() => {
    if (editor && currentDoc) {
      // Defer content setting to avoid flushSync warning
      const timeoutId = setTimeout(() => {
        if (editor && !editor.isDestroyed) {
          const content = parseDocumentContent(currentDoc.content);
          editor.commands.setContent(content, false);
          updateCounts(editor);
          editor.commands.focus('end');
        }
      }, 0);
      
      return () => clearTimeout(timeoutId);
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

        <div className="flex flex-col flex-1 overflow-hidden">
          <EditorContent
            editor={editor}
            className="flex-1 w-full px-2 py-4 overflow-auto scroll-container tiptap-editor"
          />
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
