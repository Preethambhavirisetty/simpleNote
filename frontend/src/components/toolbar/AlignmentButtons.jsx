import React from 'react';
import { AlignLeft, AlignCenter, AlignRight } from 'lucide-react';

export default function AlignmentButtons({ editor, hoverClass }) {
  if (!editor) return null;

  const buttonClass = (alignment) =>
    `p-2 rounded transition-all border ${
      editor.isActive({ textAlign: alignment })
        ? 'bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black'
        : `${hoverClass} border-[var(--color-border-medium)]`
    }`;

  return (
    <div>
      <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
        Align
      </div>
      <div className="grid grid-cols-3 gap-1.5">
        <button
          onClick={() => editor.chain().focus().setTextAlign('left').run()}
          className={buttonClass('left')}
          title="Align Left"
        >
          <AlignLeft size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <button
          onClick={() => editor.chain().focus().setTextAlign('center').run()}
          className={buttonClass('center')}
          title="Center"
        >
          <AlignCenter size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <button
          onClick={() => editor.chain().focus().setTextAlign('right').run()}
          className={buttonClass('right')}
          title="Align Right"
        >
          <AlignRight size={14} strokeWidth={2} className="mx-auto" />
        </button>
      </div>
    </div>
  );
}

