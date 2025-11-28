import React from 'react';
import {
  Bold,
  Italic,
  Strikethrough,
  Underline as UnderlineIcon,
  Heading1,
  Heading2,
  Heading3,
  List,
  ListOrdered,
  AlignLeft,
  AlignCenter,
  AlignRight,
  Link as LinkIcon,
  Image as ImageIcon,
  Code,
  Quote,
  Table as TableIcon,
  Upload,
  Download,
  Mic,
  Palette,
  Type,
} from 'lucide-react';
import { Divider } from '../ui';

export default function MobileToolbar({
  editor,
  glassClass,
  hoverClass,
  currentDoc,
  isRecording,
  onVoiceRecording,
  onShowColorPicker,
  onShowFontFamilyDialog,
  onShowFontSizeDialog,
  onShowLinkDialog,
  onMediaUpload,
  onImport,
  onExportPDF,
  onExportDocx,
  onInsertTable,
}) {
  if (!editor) return null;

  const buttonClass = (type, options = null) => {
    // Handle null type (used for non-toggle buttons)
    if (!type) {
      return `p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)]`;
    }
    const isActive = options ? editor.isActive(type, options) : editor.isActive(type);
    return `p-2 rounded flex-shrink-0 transition-all border ${
      isActive
        ? 'bg-[var(--color-accent-primary)] text-white dark:text-black'
        : `${hoverClass} border-[var(--color-border-medium)]`
    }`;
  };

  const alignmentButtonClass = (alignment) => {
    const isActive = editor.isActive({ textAlign: alignment });
    return `p-2 rounded flex-shrink-0 transition-all border ${
      isActive
        ? 'bg-[var(--color-accent-primary)] text-white dark:text-black border-[var(--color-accent-primary)]'
        : `${hoverClass} border-[var(--color-border-medium)]`
    }`;
  };

  return (
    <div
      className={`md:hidden ${glassClass} border-t border-[var(--color-border-light)] bg-[var(--color-bg-secondary)]/95 backdrop-blur-lg rounded-lg overflow-hidden`}
    >
      <div className="flex items-center gap-1 p-2 overflow-x-auto scrollbar-thin scrollbar-thumb-[var(--color-border-medium)] scrollbar-track-transparent">
        {/* Voice */}
        <button
          onClick={onVoiceRecording}
          className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)] ${
            isRecording ? 'animate-pulse bg-red-500/20' : ''
          }`}
          title="Voice Input"
        >
          <Mic size={16} strokeWidth={2} />
        </button>

        {/* Basic Formatting */}
        <button
          onClick={() => editor.chain().focus().toggleBold().run()}
          className={buttonClass('bold')}
          disabled={!editor.can().chain().focus().toggleBold().run()}
          title="Bold"
        >
          <Bold size={16} strokeWidth={2} />
        </button>

        <button
          onClick={() => editor.chain().focus().toggleItalic().run()}
          className={buttonClass('italic')}
          disabled={!editor.can().chain().focus().toggleItalic().run()}
          title="Italic"
        >
          <Italic size={16} strokeWidth={2} />
        </button>

        <button
          onClick={() => editor.chain().focus().toggleUnderline().run()}
          className={buttonClass('underline')}
          disabled={!editor.can().chain().focus().toggleUnderline().run()}
          title="Underline"
        >
          <UnderlineIcon size={16} strokeWidth={2} />
        </button>

        <button
          onClick={() => editor.chain().focus().toggleStrike().run()}
          className={buttonClass('strike')}
          disabled={!editor.can().chain().focus().toggleStrike().run()}
          title="Strikethrough"
        >
          <Strikethrough size={16} strokeWidth={2} />
        </button>

        <Divider orientation="vertical" />

        {/* Headings */}
        <button
          onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
          className={buttonClass('heading', { level: 1 })}
          title="Heading 1"
        >
          <Heading1 size={16} strokeWidth={2} />
        </button>

        <button
          onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
          className={buttonClass('heading', { level: 2 })}
          title="Heading 2"
        >
          <Heading2 size={16} strokeWidth={2} />
        </button>

        <button
          onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
          className={buttonClass('heading', { level: 3 })}
          title="Heading 3"
        >
          <Heading3 size={16} strokeWidth={2} />
        </button>

        <Divider orientation="vertical" />

        {/* Lists */}
        <button
          onClick={() => editor.chain().focus().toggleBulletList().run()}
          className={buttonClass('bulletList')}
          title="Bullet List"
        >
          <List size={16} strokeWidth={2} />
        </button>

        <button
          onClick={() => editor.chain().focus().toggleOrderedList().run()}
          className={buttonClass('orderedList')}
          title="Numbered List"
        >
          <ListOrdered size={16} strokeWidth={2} />
        </button>

        <Divider orientation="vertical" />

        {/* Alignment */}
        <button
          onClick={() => editor.chain().focus().setTextAlign('left').run()}
          className={alignmentButtonClass('left')}
          title="Align Left"
        >
          <AlignLeft size={16} strokeWidth={2} />
        </button>

        <button
          onClick={() => editor.chain().focus().setTextAlign('center').run()}
          className={alignmentButtonClass('center')}
          title="Align Center"
        >
          <AlignCenter size={16} strokeWidth={2} />
        </button>

        <button
          onClick={() => editor.chain().focus().setTextAlign('right').run()}
          className={alignmentButtonClass('right')}
          title="Align Right"
        >
          <AlignRight size={16} strokeWidth={2} />
        </button>

        <Divider orientation="vertical" />

        {/* Color & Font */}
        <button
          onClick={onShowColorPicker}
          className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)]`}
          title="Text Color"
        >
          <Palette size={16} strokeWidth={2} />
        </button>

        <button
          onClick={onShowFontFamilyDialog}
          className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)]`}
          title="Font Family"
        >
          <Type size={16} strokeWidth={2} />
        </button>

        <button
          onClick={onShowFontSizeDialog}
          className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)]`}
          title="Font Size"
        >
          <span className="text-xs font-bold">Aa</span>
        </button>

        <Divider orientation="vertical" />

        {/* Link */}
        <button
          onClick={onShowLinkDialog}
          className={buttonClass('link')}
          title="Link"
        >
          <LinkIcon size={16} strokeWidth={2} />
        </button>

        {/* Media Upload */}
        <label
          className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)] cursor-pointer flex items-center justify-center`}
          title="Upload Media"
        >
          <ImageIcon size={16} strokeWidth={2} />
          <input
            type="file"
            accept="image/*,video/*,*"
            onChange={onMediaUpload}
            className="hidden"
          />
        </label>

        <Divider orientation="vertical" />

        {/* Code */}
        <button
          onClick={() => editor.chain().focus().toggleCode().run()}
          className={buttonClass('code')}
          disabled={!editor.can().chain().focus().toggleCode().run()}
          title="Code"
        >
          <Code size={16} strokeWidth={2} />
        </button>

        <button
          onClick={() => editor.chain().focus().toggleCodeBlock().run()}
          className={buttonClass('codeBlock')}
          title="Code Block"
        >
          <Code size={16} strokeWidth={2} />
        </button>

        <button
          onClick={() => editor.chain().focus().toggleBlockquote().run()}
          className={buttonClass('blockquote')}
          title="Blockquote"
        >
          <Quote size={16} strokeWidth={2} />
        </button>

        <Divider orientation="vertical" />

        {/* Table */}
        <button
          onClick={onInsertTable}
          className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)]`}
          title="Insert Table"
        >
          <TableIcon size={16} strokeWidth={2} />
        </button>

        <Divider orientation="vertical" />

        {/* File Actions */}
        <label
          className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)] cursor-pointer flex items-center justify-center gap-1.5`}
          title="Import"
        >
          <Upload size={16} strokeWidth={2} />
          <input
            type="file"
            accept=".txt,.md,.json"
            onChange={onImport}
            className="hidden"
          />
        </label>

        <button
          onClick={onExportPDF}
          className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)] flex items-center justify-center gap-1.5`}
          title="Export to PDF"
          disabled={!currentDoc}
        >
          <Download size={16} strokeWidth={2} />
        </button>

        <button
          onClick={onExportDocx}
          className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)] flex items-center justify-center`}
          title="Export to DOCX"
          disabled={!currentDoc}
        >
          <Download size={16} strokeWidth={2} />
        </button>
      </div>
    </div>
  );
}

