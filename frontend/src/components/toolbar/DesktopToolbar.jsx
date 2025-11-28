import React from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import VoiceRecorder from './VoiceRecorder';
import TextStyleButtons from './TextStyleButtons';
import HeadingButtons from './HeadingButtons';
import AlignmentButtons from './AlignmentButtons';
import ListButtons from './ListButtons';
import InsertButtons from './InsertButtons';
import FileOperations from './FileOperations';

export default function DesktopToolbar({
  editor,
  currentDoc,
  glassClass,
  hoverClass,
  isCollapsed,
  onToggleCollapse,
  onShowColorPicker,
  onShowFontFamilyDialog,
  onShowFontSizeDialog,
  onShowLinkDialog,
  onMediaUpload,
  onFileUpload,
  showToast,
}) {
  return (
    <div
      className={`scroll-container hidden md:block ${glassClass} rounded-lg border border-[var(--color-border-light)] overflow-hidden transition-all duration-300 ${
        isCollapsed ? 'w-14' : 'w-72'
      }`}
    >
      {/* Header with Toggle */}
      <div className="flex items-center justify-between p-3 border-b border-[var(--color-border-light)] bg-[var(--color-bg-secondary)]">
        {!isCollapsed && (
          <h2 className="text-sm font-bold tracking-tight">Formatting</h2>
        )}
        <button
          onClick={onToggleCollapse}
          className={`p-1.5 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)]`}
          title={isCollapsed ? 'Expand Toolbar' : 'Collapse Toolbar'}
        >
          {isCollapsed ? (
            <ChevronLeft size={14} />
          ) : (
            <ChevronRight size={14} />
          )}
        </button>
      </div>

      {/* Toolbar Content */}
      {!isCollapsed && (
        <div className="p-4 space-y-4 overflow-y-auto max-h-[calc(100vh-200px)]">
          <VoiceRecorder
            editor={editor}
            showToast={showToast}
            hoverClass={hoverClass}
          />

          <TextStyleButtons
            editor={editor}
            hoverClass={hoverClass}
            onShowColorPicker={onShowColorPicker}
            onShowFontFamilyDialog={onShowFontFamilyDialog}
            onShowFontSizeDialog={onShowFontSizeDialog}
          />

          <HeadingButtons editor={editor} hoverClass={hoverClass} />

          <AlignmentButtons editor={editor} hoverClass={hoverClass} />

          <ListButtons editor={editor} hoverClass={hoverClass} />

          <InsertButtons
            editor={editor}
            hoverClass={hoverClass}
            onShowLinkDialog={onShowLinkDialog}
            onMediaUpload={onMediaUpload}
            showToast={showToast}
          />

          <FileOperations
            currentDoc={currentDoc}
            hoverClass={hoverClass}
            onFileUpload={onFileUpload}
            showToast={showToast}
          />
        </div>
      )}
    </div>
  );
}

