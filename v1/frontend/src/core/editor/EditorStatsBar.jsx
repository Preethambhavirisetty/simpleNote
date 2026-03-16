import React from 'react';
import { FileText, Clock, BookOpen, Save, AlertCircle } from 'lucide-react';
import { READING_SPEED_WPM } from '../../constants/editor';

export default function EditorStatsBar({
  currentDoc,
  wordCount,
  charCount,
  isSaving,
  lastSaved,
}) {
  if (!currentDoc) return null;

  const readTime = Math.ceil(wordCount / READING_SPEED_WPM);

  return (
    <div className="px-3 sm:px-6 py-2 sm:py-3 border-b border-[var(--color-border-light)] bg-[var(--color-bg-secondary)] flex-shrink-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3 sm:gap-6">
          {/* Document Title */}
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
          <SaveStatus isSaving={isSaving} lastSaved={lastSaved} />
        </div>

        <div className="flex items-center gap-3 sm:gap-6">
          {/* Word Count */}
          <div className="flex items-center gap-2">
            <BookOpen
              size={14}
              strokeWidth={2}
              className="text-[var(--color-text-muted)]"
            />
            <span className="text-xs font-semibold tracking-tight">
              {wordCount} {wordCount === 1 ? 'word' : 'words'}
            </span>
          </div>

          {/* Read Time */}
          <div className="hidden sm:block w-px h-4 bg-[var(--color-border-medium)]"></div>
          <div className="items-center hidden gap-2 sm:flex">
            <Clock
              size={14}
              strokeWidth={2}
              className="text-[var(--color-text-muted)]"
            />
            <span className="text-xs font-semibold tracking-tight">
              {readTime} min read
            </span>
          </div>

          {/* Character Count */}
          <div className="w-px h-4 bg-[var(--color-border-medium)]"></div>
          <span className="text-xs font-semibold tracking-tight text-[var(--color-text-muted)]">
            {charCount} chars
          </span>
        </div>
      </div>
    </div>
  );
}

function SaveStatus({ isSaving, lastSaved }) {
  if (isSaving) {
    return (
      <div className="flex items-center gap-1.5">
        <Save
          size={12}
          strokeWidth={2}
          className="text-yellow-500 dark:text-yellow-400 animate-pulse"
        />
        <span className="text-xs font-medium text-yellow-500 dark:text-yellow-400">
          Not saved
        </span>
      </div>
    );
  }

  if (lastSaved) {
    return (
      <div className="flex items-center gap-1.5">
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
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1.5">
      <AlertCircle
        size={12}
        strokeWidth={2}
        className="text-gray-400 dark:text-gray-500"
      />
      <span className="text-xs font-medium text-gray-400 dark:text-gray-500">
        Not saved
      </span>
    </div>
  );
}

