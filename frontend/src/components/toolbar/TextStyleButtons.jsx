import React from 'react';
import {
  Bold,
  Italic,
  Strikethrough,
  Underline as UnderlineIcon,
  Code,
  Eraser,
  Palette,
  Type,
  CaseSensitive,
} from 'lucide-react';

export default function TextStyleButtons({
  editor,
  hoverClass,
  onShowColorPicker,
  onShowFontFamilyDialog,
  onShowFontSizeDialog,
}) {
  if (!editor) return null;

  const buttonClass = (isActive) =>
    `p-2 rounded transition-all border ${
      isActive
        ? 'bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black'
        : `${hoverClass} border-[var(--color-border-medium)]`
    }`;

  // Get current font attributes from selection
  const textStyleAttrs = editor.getAttributes('textStyle');
  const currentFontFamily = textStyleAttrs.fontFamily;
  const currentFontSize = textStyleAttrs.fontSize;

  return (
    <div>
      <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
        Style
      </div>
      <div className="grid grid-cols-3 gap-1.5">
        <button
          onClick={() => editor.chain().focus().toggleBold().run()}
          className={buttonClass(editor.isActive('bold'))}
          title="Bold"
        >
          <Bold size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <button
          onClick={() => editor.chain().focus().toggleItalic().run()}
          className={buttonClass(editor.isActive('italic'))}
          title="Italic"
        >
          <Italic size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <button
          onClick={() => editor.chain().focus().toggleStrike().run()}
          className={buttonClass(editor.isActive('strike'))}
          title="Strikethrough"
        >
          <Strikethrough size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <button
          onClick={() => editor.chain().focus().toggleUnderline().run()}
          className={buttonClass(editor.isActive('underline'))}
          title="Underline"
        >
          <UnderlineIcon size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <button
          onClick={() => editor.chain().focus().toggleCode().run()}
          className={buttonClass(editor.isActive('code'))}
          title="Inline Code"
        >
          <Code size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <button
          onClick={() => editor.chain().focus().unsetAllMarks().run()}
          className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)]`}
          title="Clear Formatting"
        >
          <Eraser size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <button
          onClick={onShowColorPicker}
          className={`w-full p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)] flex items-center justify-center gap-2`}
          title="Text Color"
        >
          <Palette size={14} strokeWidth={2} />
        </button>
        <button
          onClick={onShowFontFamilyDialog}
          className={`w-full p-2 rounded transition-all border ${
            currentFontFamily 
              ? 'bg-[var(--color-accent-primary)]/20 border-[var(--color-accent-primary)]' 
              : `${hoverClass} border-[var(--color-border-medium)]`
          } flex items-center justify-center gap-1 text-xs`}
          title="Font Family (select text first)"
        >
          <Type size={14} strokeWidth={2} />
          <span className="text-[10px]">Font</span>
        </button>
        <button
          onClick={onShowFontSizeDialog}
          className={`w-full p-2 rounded transition-all border ${
            currentFontSize 
              ? 'bg-[var(--color-accent-primary)]/20 border-[var(--color-accent-primary)]' 
              : `${hoverClass} border-[var(--color-border-medium)]`
          } flex items-center justify-center gap-1 text-xs`}
          title="Font Size (select text first)"
        >
          <CaseSensitive size={14} strokeWidth={2} />
          <span className="text-[10px]">Size</span>
        </button>
      </div>
    </div>
  );
}
