import React from 'react';
import { Heading1, Heading2, Heading3 } from 'lucide-react';

export default function HeadingButtons({ editor, hoverClass }) {
  if (!editor) return null;

  const buttonClass = (level) =>
    `p-2 rounded transition-all border ${
      editor.isActive('heading', { level })
        ? 'bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black'
        : `${hoverClass} border-[var(--color-border-medium)]`
    }`;

  return (
    <div>
      <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
        Headings
      </div>
      <div className="grid grid-cols-3 gap-1.5">
        <button
          onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
          className={buttonClass(1)}
          title="Heading 1"
        >
          <Heading1 size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <button
          onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
          className={buttonClass(2)}
          title="Heading 2"
        >
          <Heading2 size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <button
          onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
          className={buttonClass(3)}
          title="Heading 3"
        >
          <Heading3 size={14} strokeWidth={2} className="mx-auto" />
        </button>
      </div>
    </div>
  );
}

