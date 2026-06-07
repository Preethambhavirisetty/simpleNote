import React, { useState } from 'react';
import Modal from '../../ui/Modal';

export default function LinkDialog({
  isOpen,
  onClose,
  editor,
  glassClass,
  hoverClass,
  showToast,
}) {
  const [linkUrl, setLinkUrl] = useState('');

  const insertLink = () => {
    if (!linkUrl) {
      showToast?.('Please enter a URL', 'info', 2000);
      return;
    }

    editor?.chain().focus().setLink({ href: linkUrl }).run();
    onClose();
    setLinkUrl('');
    showToast?.('Link added', 'success', 1500);
  };

  const handleClose = () => {
    setLinkUrl('');
    onClose();
  };

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="Insert Link" glassClass={glassClass}>
      <div className="space-y-3">
        <input
          type="url"
          placeholder="https://example.com"
          value={linkUrl}
          onChange={(e) => setLinkUrl(e.target.value)}
          className="w-full px-3 py-2 rounded border border-[var(--color-border-medium)] bg-[var(--color-bg-primary)] focus:outline-none focus:border-[var(--color-accent-primary)]"
          autoFocus
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              insertLink();
            }
          }}
        />
        <div className="flex gap-2">
          <button
            onClick={insertLink}
            className={`flex-1 px-4 py-2 rounded bg-[var(--color-accent-primary)] text-[var(--color-bg-primary)] font-semibold ${hoverClass}`}
          >
            Insert
          </button>
          <button
            onClick={handleClose}
            className={`flex-1 px-4 py-2 rounded ${hoverClass} border border-[var(--color-border-medium)] font-semibold`}
          >
            Cancel
          </button>
        </div>
      </div>
    </Modal>
  );
}

