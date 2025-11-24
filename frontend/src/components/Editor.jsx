import React, { useRef, useEffect, useState } from 'react';
import { FileText, Clock, BookOpen } from 'lucide-react';
import TextSelectionTooltip from './TextSelectionTooltip';

export default function Editor({
  currentDoc,
  updateDocContent,
  onTextSelection,
  onShowAIPanel,
  glassClass,
  textClass
}) {
  const editorRef = useRef(null);
  const [fontSize, setFontSize] = useState(16);
  const [wordCount, setWordCount] = useState(0);
  const [charCount, setCharCount] = useState(0);
  const [tooltipPosition, setTooltipPosition] = useState(null);

  useEffect(() => {
    if (editorRef.current && currentDoc) {
      editorRef.current.innerHTML = currentDoc.content;
      updateCounts(currentDoc.content);
      
      // Auto-focus and move cursor to end
      editorRef.current.focus();
      
      // Move cursor to the end
      const range = document.createRange();
      const selection = window.getSelection();
      
      if (editorRef.current.childNodes.length > 0) {
        const lastNode = editorRef.current.childNodes[editorRef.current.childNodes.length - 1];
        range.selectNodeContents(lastNode);
        range.collapse(false); // false = collapse to end
      } else {
        range.selectNodeContents(editorRef.current);
        range.collapse(false);
      }
      
      selection.removeAllRanges();
      selection.addRange(range);
      
      // Scroll to bottom
      editorRef.current.scrollTop = editorRef.current.scrollHeight;
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
      if (onTextSelection) {
        onTextSelection(text);
      }
      
      // Get selection position for tooltip
      const range = selection.getRangeAt(0);
      const rect = range.getBoundingClientRect();
      setTooltipPosition({
        x: rect.left + rect.width / 2,
        y: rect.top + window.scrollY
      });
    } else {
      setTooltipPosition(null);
    }
  };

  const handleAskAI = () => {
    setTooltipPosition(null);
    if (onShowAIPanel) {
      onShowAIPanel();
    }
  };

  const handleKeyDown = (e) => {
    // Handle Tab key for indentation/subpoints
    if (e.key === 'Tab') {
      e.preventDefault();
      
      if (e.shiftKey) {
        // Shift+Tab: Outdent
        document.execCommand('outdent', false, null);
      } else {
        // Tab: Indent
        document.execCommand('indent', false, null);
      }
      
      const content = editorRef.current?.innerHTML;
      if (content) updateDocContent(content);
    }
  };

  return (
    <>
      <TextSelectionTooltip
        position={tooltipPosition}
        onAskAI={handleAskAI}
      />
      
      <div className={`flex-1 ${glassClass} rounded-lg overflow-hidden flex flex-col`}>
        {/* Stats Bar - Responsive */}
      {currentDoc && (
        <div className="px-3 sm:px-6 py-2 sm:py-3 border-b border-[var(--color-border-light)] bg-[var(--color-bg-secondary)]">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-3 sm:gap-6">
              <div className="flex items-center gap-2">
                <FileText size={14} strokeWidth={2} className="text-[var(--color-text-muted)]" />
                <span className="text-xs font-bold tracking-tight truncate max-w-[150px] sm:max-w-none">{currentDoc.title}</span>
              </div>
            </div>
            <div className="flex items-center gap-3 sm:gap-6">
              <div className="flex items-center gap-2">
                <BookOpen size={14} strokeWidth={2} className="text-[var(--color-text-muted)]" />
                <span className="text-xs font-semibold tracking-tight">
                  {wordCount} {wordCount === 1 ? 'word' : 'words'}
                </span>
              </div>
              <div className="hidden sm:block w-px h-4 bg-[var(--color-border-medium)]"></div>
              <div className="hidden sm:flex items-center gap-2">
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

      {/* Editor - Responsive padding */}
      <div className="flex-1 overflow-y-auto">
        <div
          ref={editorRef}
          contentEditable
          className={`p-4 sm:p-6 md:p-8 ${textClass} prose prose-sm sm:prose-base md:prose-lg max-w-none min-h-full focus:outline-none editor-content`}
          onInput={handleInput}
          onMouseUp={handleMouseUp}
          onKeyDown={handleKeyDown}
          style={{
            fontSize: `${fontSize}px`,
            lineHeight: '1.5',
            minHeight: '100%',
            wordWrap: 'break-word',
            overflowWrap: 'break-word',
            whiteSpace: 'pre-wrap'
          }}
          placeholder="Start writing..."
        />
      </div>
    </div>
    </>
  );
}
