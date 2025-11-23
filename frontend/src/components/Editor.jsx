import React, { useRef, useEffect, useState } from 'react';
import { FileText, Clock, BookOpen } from 'lucide-react';

export default function Editor({
  currentDoc,
  updateDocContent,
  onTextSelection,
  glassClass,
  textClass
}) {
  const editorRef = useRef(null);
  const [fontSize, setFontSize] = useState(16);
  const [wordCount, setWordCount] = useState(0);
  const [charCount, setCharCount] = useState(0);

  useEffect(() => {
    if (editorRef.current && currentDoc) {
      editorRef.current.innerHTML = currentDoc.content;
      updateCounts(currentDoc.content);
    }
  }, [currentDoc?.id]);

  const updateCounts = (html) => {
    const text = html.replace(/<[^>]*>/g, ' ').trim();
    const words = text.split(/\s+/).filter(word => word.length > 0);
    setWordCount(words.length);
    setCharCount(text.length);
  };

  const handleInput = () => {
    if (editorRef.current) {
      const content = editorRef.current.innerHTML;
      updateDocContent(content);
      updateCounts(content);
    }
  };

  const handleMouseUp = () => {
    const selection = window.getSelection();
    const text = selection.toString().trim();
    if (text) {
      onTextSelection(text);
    }
  };

  return (
    <div className={`flex-1 ${glassClass} rounded-lg overflow-hidden flex flex-col`}>
      {/* Stats Bar */}
      {currentDoc && (
        <div className="px-6 py-3 border-b border-[var(--color-border-light)] bg-[var(--color-bg-secondary)]">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-6">
              <div className="flex items-center gap-2">
                <FileText size={14} strokeWidth={2} className="text-[var(--color-text-muted)]" />
                <span className="text-xs font-bold tracking-tight">{currentDoc.title}</span>
              </div>
            </div>
            <div className="flex items-center gap-6">
              <div className="flex items-center gap-2">
                <BookOpen size={14} strokeWidth={2} className="text-[var(--color-text-muted)]" />
                <span className="text-xs font-semibold tracking-tight">
                  {wordCount} {wordCount === 1 ? 'word' : 'words'}
                </span>
              </div>
              <div className="w-px h-4 bg-[var(--color-border-medium)]"></div>
              <div className="flex items-center gap-2">
                <Clock size={14} strokeWidth={2} className="text-[var(--color-text-muted)]" />
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

      {/* Editor */}
      <div className="flex-1 overflow-y-auto">
        <div
          ref={editorRef}
          contentEditable
          className={`p-8 ${textClass} prose prose-lg max-w-none min-h-full focus:outline-none`}
          onInput={handleInput}
          onMouseUp={handleMouseUp}
          style={{
            fontSize: `${fontSize}px`,
            lineHeight: '1.75',
            minHeight: '100%',
            wordWrap: 'break-word',
            overflowWrap: 'break-word',
            whiteSpace: 'pre-wrap'
          }}
          placeholder="Start writing..."
        />
      </div>
    </div>
  );
}
