import React from 'react';
import { FONT_SIZES } from '../../../constants/toolbar';
import Modal from '../../ui/Modal';

export default function FontSizeModal({
  isOpen,
  onClose,
  editor,
  glassClass,
  hoverClass,
  showToast,
}) {
  if (!editor) return null;

  // Get current font size from selection
  const currentFontSize = editor.getAttributes('textStyle').fontSize;
  // Parse the number from fontSize (e.g., "16px" -> 16)
  const currentSizeNumber = currentFontSize ? parseInt(currentFontSize) : null;

  const handleSelect = (size) => {
    // Apply font size to selected text using TipTap command
    editor.chain().focus().setFontSize(`${size}px`).run();
    onClose();
    showToast?.(`Font size: ${size}px`, 'success', 1500);
  };

  const handleClear = () => {
    // Remove font size from selected text
    editor.chain().focus().unsetFontSize().run();
    onClose();
    showToast?.('Font size cleared', 'success', 1500);
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Font Size" glassClass={glassClass}>
      <p className="text-xs text-[var(--color-text-muted)] mb-3">
        Select text first, then choose a size to apply.
      </p>
      <div className="grid grid-cols-4 gap-2 mb-3">
        {FONT_SIZES.map((size) => (
          <button
            key={size}
            onClick={() => handleSelect(size)}
            className={`p-3 rounded border font-semibold transition-all ${
              currentSizeNumber === size
                ? 'bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black'
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
          >
            {size}
          </button>
        ))}
      </div>
      <button
        onClick={handleClear}
        className={`w-full p-2 rounded border ${hoverClass} border-[var(--color-border-medium)] text-sm`}
      >
        Clear Font Size
      </button>
    </Modal>
  );
}
