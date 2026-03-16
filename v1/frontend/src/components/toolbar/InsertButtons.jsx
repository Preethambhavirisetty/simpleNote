import React from 'react';
import {
  Link as LinkIcon,
  Image as ImageIcon,
  Code,
  Quote,
  Minus,
  Table as TableIcon,
} from 'lucide-react';

export default function InsertButtons({
  editor,
  hoverClass,
  onShowLinkDialog,
  onMediaUpload,
  showToast,
}) {
  if (!editor) return null;

  const buttonClass = (type) =>
    `p-2 rounded transition-all border ${
      editor.isActive(type)
        ? 'bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black'
        : `${hoverClass} border-[var(--color-border-medium)]`
    }`;

  const insertTable = () => {
    editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run();
    showToast?.('Table inserted', 'success', 1500);
  };

  return (
    <div>
      <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-[var(--color-border-light)]">
        Insert
      </div>
      <div className="grid grid-cols-3 gap-1.5">
        <button
          onClick={onShowLinkDialog}
          className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)]`}
          title="Insert Link (Select text first)"
        >
          <LinkIcon size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <label
          className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)] cursor-pointer flex items-center justify-center`}
          title="Upload Image/Video/File"
        >
          <ImageIcon size={14} strokeWidth={2} className="mx-auto" />
          <input
            type="file"
            accept="image/*,video/*,*"
            onChange={onMediaUpload}
            className="hidden"
          />
        </label>
        <button
          onClick={insertTable}
          className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)]`}
          title="Insert Table"
        >
          <TableIcon size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <button
          onClick={() => editor.chain().focus().toggleCodeBlock().run()}
          className={buttonClass('codeBlock')}
          title="Code Block"
        >
          <Code size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <button
          onClick={() => editor.chain().focus().toggleBlockquote().run()}
          className={buttonClass('blockquote')}
          title="Blockquote"
        >
          <Quote size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <button
          onClick={() => editor.chain().focus().setHorizontalRule().run()}
          className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)]`}
          title="Horizontal Line"
        >
          <Minus size={14} strokeWidth={2} className="mx-auto" />
        </button>
      </div>
    </div>
  );
}
