import React from 'react';
import { List, ListOrdered, Indent, Outdent } from 'lucide-react';

export default function ListButtons({ editor, hoverClass }) {
  if (!editor) return null;

  const buttonClass = (type) =>
    `p-2 rounded transition-all border ${
      editor.isActive(type)
        ? 'bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black'
        : `${hoverClass} border-[var(--color-border-medium)]`
    }`;

  return (
    <div>
      <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
        Lists
      </div>
      <div className="grid grid-cols-4 gap-1.5">
        <button
          onClick={() => editor.chain().focus().toggleBulletList().run()}
          className={buttonClass('bulletList')}
          title="Bullet List"
        >
          <List size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <button
          onClick={() => editor.chain().focus().toggleOrderedList().run()}
          className={buttonClass('orderedList')}
          title="Numbered List"
        >
          <ListOrdered size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <button
          onClick={() => editor.chain().focus().sinkListItem('listItem').run()}
          disabled={!editor.can().sinkListItem('listItem')}
          className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)] disabled:opacity-50`}
          title="Indent"
        >
          <Indent size={14} strokeWidth={2} className="mx-auto" />
        </button>
        <button
          onClick={() => editor.chain().focus().liftListItem('listItem').run()}
          disabled={!editor.can().liftListItem('listItem')}
          className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)] disabled:opacity-50`}
          title="Outdent"
        >
          <Outdent size={14} strokeWidth={2} className="mx-auto" />
        </button>
      </div>
    </div>
  );
}

