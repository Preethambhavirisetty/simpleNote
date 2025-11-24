import React, { useRef, useEffect, useState } from 'react';
import { FileText, Clock, BookOpen } from 'lucide-react';
import TextSelectionTooltip from './TextSelectionTooltip';

export default function Editor({
  content,
  onContentChange,
  onTextSelection,
  onAskAI,
  editorRef,
  theme
}) {
  const [fontSize, setFontSize] = useState(16);
  const [wordCount, setWordCount] = useState(0);
  const [charCount, setCharCount] = useState(0);
  const [tooltipPosition, setTooltipPosition] = useState(null);

  useEffect(() => {
    if (editorRef.current && content !== undefined) {
      editorRef.current.innerHTML = content;
      updateCounts(content);
    }
  }, [content]);

  const updateCounts = (html) => {
    const text = html.replace(/<[^>]*>/g, ' ').trim();
    const words = text.split(/\s+/).filter(word => word.length > 0);
    setWordCount(words.length);
    setCharCount(text.length);
  };

  const handleInput = () => {
    if (editorRef.current) {
      const newContent = editorRef.current.innerHTML;
      onContentChange(newContent);
      updateCounts(newContent);
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
    if (onAskAI) {
      onAskAI();
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
      
      const newContent = editorRef.current?.innerHTML;
      if (newContent) onContentChange(newContent);
    }
  };

  return (
    <>
      <TextSelectionTooltip
        position={tooltipPosition}
        onAskAI={handleAskAI}
      />
      
      <div className="flex-1 flex flex-col overflow-hidden bg-white dark:bg-gray-900">
        {/* Stats Bar */}
        <div className="px-4 sm:px-6 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <BookOpen size={14} strokeWidth={2} className="text-gray-500 dark:text-gray-400" />
                <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">
                  {wordCount} {wordCount === 1 ? 'word' : 'words'}
                </span>
              </div>
              <div className="w-px h-4 bg-gray-300 dark:bg-gray-600"></div>
              <div className="flex items-center gap-2">
                <Clock size={14} strokeWidth={2} className="text-gray-500 dark:text-gray-400" />
                <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">
                  {Math.ceil(wordCount / 200)} min read
                </span>
              </div>
              <div className="w-px h-4 bg-gray-300 dark:bg-gray-600"></div>
              <span className="text-xs font-semibold text-gray-500 dark:text-gray-400">
                {charCount} chars
              </span>
            </div>
          </div>
        </div>

        {/* Editor */}
        <div className="flex-1 overflow-y-auto">
          <div
            ref={editorRef}
            contentEditable
            className="p-4 sm:p-6 md:p-8 lg:p-12 prose prose-sm sm:prose-base lg:prose-lg max-w-none min-h-full focus:outline-none editor-content text-gray-900 dark:text-gray-100"
            onInput={handleInput}
            onMouseUp={handleMouseUp}
            onKeyDown={handleKeyDown}
            style={{
              fontSize: `${fontSize}px`,
              lineHeight: '1.8',
              minHeight: '100%',
              wordWrap: 'break-word',
              overflowWrap: 'break-word',
              whiteSpace: 'pre-wrap'
            }}
          />
        </div>
      </div>
    </>
  );
}
