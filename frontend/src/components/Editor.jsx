import React, { useEffect, useState } from "react";
import { FileText, Clock, BookOpen, Save, AlertCircle } from "lucide-react";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import TextAlign from "@tiptap/extension-text-align";
import Underline from "@tiptap/extension-underline";
import { Color } from "@tiptap/extension-color";
import { TextStyle } from "@tiptap/extension-text-style";
import FontFamily from "@tiptap/extension-font-family";
import Link from "@tiptap/extension-link";
import { Table } from "@tiptap/extension-table";
import { TableRow } from "@tiptap/extension-table-row";
import { TableCell } from "@tiptap/extension-table-cell";
import { TableHeader } from "@tiptap/extension-table-header";
import { Extension } from "@tiptap/core";
import TextSelectionTooltip from "./TextSelectionTooltip";
import { ResizableImage } from "tiptap-extension-resizable-image";
import "tiptap-extension-resizable-image/styles.css";

// Custom Tab Handler Extension
const TabHandler = Extension.create({
  name: "tabHandler",

  addKeyboardShortcuts() {
    return {
      Tab: () => {
        // Insert tab character
        this.editor.commands.insertContent("\t");
        return true;
      },
    };
  },
});

export default function Editor({
  currentDoc,
  updateDocContent,
  onTextSelection,
  onShowAIPanel,
  glassClass,
  textClass,
  fontFamily,
  fontSize,
  onEditorReady,
  isSaving,
  lastSaved,
  onManualSave,
}) {
  const [wordCount, setWordCount] = useState(0);
  const [charCount, setCharCount] = useState(0);
  const [tooltipPosition, setTooltipPosition] = useState(null);

  // Handle Ctrl+S / Cmd+S for manual save
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        if (onManualSave) {
          onManualSave();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onManualSave]);

  // Initialize TipTap editor
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: {
          levels: [1, 2, 3, 4, 5, 6],
        },
        history: {
          depth: 100, // Keep reasonable history depth
        },
      }),
      TextAlign.configure({
        types: ["heading", "paragraph"],
      }),
      Underline,
      Color,
      TextStyle,
      FontFamily,
      Link.configure({
        openOnClick: false,
        HTMLAttributes: {
          class: "text-[var(--color-accent-primary)] underline cursor-pointer",
        },
      }),
      ResizableImage.configure({
        allowBase64: true,
        allowResize: true,
        inline: true,
        HTMLAttributes: {
          class: "rounded cursor-pointer",
        },
      }),
      Table.configure({
        resizable: true,
      }),
      TableRow,
      TableHeader,
      TableCell,
      TabHandler,
    ],
    content: "",
    editorProps: {
      attributes: {
        class: `focus:outline-none ${textClass}`,
        style: `font-size: ${fontSize}px; font-family: ${
          fontFamily || "system-ui, -apple-system, sans-serif"
        };`,
      },
      handlePaste: (view, event, slice) => {
        // Handle image paste
        const items = event.clipboardData?.items;
        if (items) {
          for (let i = 0; i < items.length; i++) {
            if (items[i].type.indexOf("image") !== -1) {
              event.preventDefault();
              const blob = items[i].getAsFile();
              if (blob) {
                const reader = new FileReader();
                reader.onload = (e) => {
                  const base64 = e.target.result;
                  // Use view.state and view.dispatch for reliable insertion
                  const { schema } = view.state;
                  const nodeType =
                    schema.nodes.resizableImage || schema.nodes.image;
                  const node = nodeType.create({ src: base64 });
                  const transaction = view.state.tr.replaceSelectionWith(node);
                  view.dispatch(transaction);
                };
                reader.readAsDataURL(blob);
              }
              return true;
            }
          }
        }
        return false;
      },
    },
    onUpdate: ({ editor }) => {
      // Get ProseMirror JSON
      const json = editor.getJSON();

      // Update document content with ProseMirror JSON
      updateDocContent(json);

      // Update word and character counts
      const text = editor.getText();
      const cleanText = text.trim();
      const words = cleanText.split(/\s+/).filter((word) => word.length > 0);
      setWordCount(words.length);
      setCharCount(cleanText.length);
    },
    onSelectionUpdate: ({ editor }) => {
      const { from, to } = editor.state.selection;
      const text = editor.state.doc.textBetween(from, to, " ").trim();

      if (text && onTextSelection) {
        onTextSelection(text);

        // Get editor position for tooltip
        const editorElement = editor.view.dom;
        const rect = editorElement.getBoundingClientRect();
        setTooltipPosition({
          x: rect.left + rect.width / 2,
          y: rect.top + window.scrollY,
        });
      } else {
        setTooltipPosition(null);
      }
    },
  });

  // Notify parent when editor is ready
  useEffect(() => {
    if (editor && onEditorReady) {
      onEditorReady(editor);
      console.log(editor?.extensionManager?.extensions.map((e) => e.name));
    }
  }, [editor, onEditorReady]);

  // Load document content when currentDoc changes
  useEffect(() => {
    if (editor && currentDoc) {
      // Check if content is ProseMirror JSON or plain text
      let content;

      if (
        typeof currentDoc.content === "object" &&
        currentDoc.content !== null
      ) {
        // Already ProseMirror JSON
        content = currentDoc.content;
      } else if (typeof currentDoc.content === "string") {
        try {
          // Try to parse as JSON
          content = JSON.parse(currentDoc.content);
        } catch {
          // Plain text, convert to ProseMirror format
          content = {
            type: "doc",
            content: [
              {
                type: "paragraph",
                content: currentDoc.content
                  ? [{ type: "text", text: currentDoc.content }]
                  : [],
              },
            ],
          };
        }
      } else {
        // Empty content
        content = {
          type: "doc",
          content: [{ type: "paragraph" }],
        };
      }

      // Set content without triggering onUpdate
      // Note: The Editor component is recreated with a key prop when switching documents,
      // so each document gets a fresh editor with no history
      editor.commands.setContent(content, false);

      // Update counts
      const text = editor.getText();
      const cleanText = text.trim();
      const words = cleanText.split(/\s+/).filter((word) => word.length > 0);
      setWordCount(words.length);
      setCharCount(cleanText.length);

      // Focus editor - defer to avoid flushSync warning during render
      // Use queueMicrotask to move focus outside the current render cycle
      queueMicrotask(() => {
        if (editor && !editor.isDestroyed) {
          editor.commands.focus("end");
        }
      });
    }
  }, [currentDoc?.id, editor]);

  // Update editor style when font settings change
  useEffect(() => {
    if (editor) {
      const editorElement = editor.view.dom;
      editorElement.style.fontSize = `${fontSize}px`;
      editorElement.style.fontFamily =
        fontFamily || "system-ui, -apple-system, sans-serif";
    }
  }, [fontFamily, fontSize, editor]);

  const handleAskAI = () => {
    setTooltipPosition(null);
    if (onShowAIPanel) {
      onShowAIPanel();
    }
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
        {/* Stats Bar - Responsive */}
        {currentDoc && (
          <div className="px-3 sm:px-6 py-2 sm:py-3 border-b border-[var(--color-border-light)] bg-[var(--color-bg-secondary)] flex-shrink-0">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-3 sm:gap-6">
                <div className="flex items-center gap-2">
                  <FileText
                    size={14}
                    strokeWidth={2}
                    className="text-[var(--color-text-muted)]"
                  />
                  <span className="text-xs font-bold tracking-tight truncate max-w-[150px] sm:max-w-none">
                    {currentDoc.title}
                  </span>
                </div>
                {/* Save Status */}
                <div className="flex items-center gap-1.5">
                  {isSaving ? (
                    <>
                      <Save
                        size={12}
                        strokeWidth={2}
                        className="text-yellow-500 dark:text-yellow-400 animate-pulse"
                      />
                      <span className="text-xs font-medium text-yellow-500 dark:text-yellow-400">
                        Not saved
                      </span>
                    </>
                  ) : lastSaved ? (
                    <>
                      <svg
                        className="w-3 h-3 text-green-600 dark:text-green-400"
                        fill="currentColor"
                        viewBox="0 0 20 20"
                      >
                        <path
                          fillRule="evenodd"
                          d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                          clipRule="evenodd"
                        />
                      </svg>
                      <span className="text-xs font-medium text-green-600 dark:text-green-400">
                        Saved
                      </span>
                    </>
                  ) : (
                    <>
                      <AlertCircle
                        size={12}
                        strokeWidth={2}
                        className="text-gray-400 dark:text-gray-500"
                      />
                      <span className="text-xs font-medium text-gray-400 dark:text-gray-500">
                        Not saved
                      </span>
                    </>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-3 sm:gap-6">
                <div className="flex items-center gap-2">
                  <BookOpen
                    size={14}
                    strokeWidth={2}
                    className="text-[var(--color-text-muted)]"
                  />
                  <span className="text-xs font-semibold tracking-tight">
                    {wordCount} {wordCount === 1 ? "word" : "words"}
                  </span>
                </div>
                <div className="hidden sm:block w-px h-4 bg-[var(--color-border-medium)]"></div>
                <div className="hidden sm:flex items-center gap-2">
                  <Clock
                    size={14}
                    strokeWidth={2}
                    className="text-[var(--color-text-muted)]"
                  />
                  <span className="text-xs font-semibold tracking-tight">
                    {Math.ceil(wordCount / 200)} min read
                  </span>
                </div>
                <div className="w-px h-4 bg-[var(--color-border-medium)]"></div>
                <span className="text-xs font-semibold tracking-tight text-[var(--color-text-muted)]">
                  {charCount} chars
                </span>
              </div>
            </div>
          </div>
        )}

        {/* TipTap Editor */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <EditorContent
            editor={editor}
            className="scroll-container tiptap-editor flex-1 w-full px-2 py-4 overflow-auto"
          />
        </div>
      </div>
    </>
  );
}
