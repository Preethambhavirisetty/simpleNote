import React from 'react';
import { FONT_FAMILIES } from '../../../constants/toolbar';
import Modal from '../../ui/Modal';

export default function FontFamilyModal({
  isOpen,
  onClose,
  editor,
  glassClass,
  hoverClass,
  showToast,
}) {
  if (!editor) return null;

  // Get current font family from selection
  const currentFontFamily = editor.getAttributes('textStyle').fontFamily;

  const handleSelect = (font) => {
    // Apply font family to selected text using TipTap command
    editor.chain().focus().setFontFamily(font.value).run();
    onClose();
    showToast?.(`Font: ${font.name}`, 'success', 1500);
  };

  const handleClear = () => {
    // Remove font family from selected text
    editor.chain().focus().unsetFontFamily().run();
    onClose();
    showToast?.('Font cleared', 'success', 1500);
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Font Family" glassClass={glassClass}>
      <p className="text-xs text-[var(--color-text-muted)] mb-3">
        Select text first, then choose a font to apply.
      </p>
      <div className="space-y-2 max-h-[350px] overflow-y-auto mb-3">
        {FONT_FAMILIES.map((font) => (
          <button
            key={font.value}
            onClick={() => handleSelect(font)}
            className={`w-full p-3 rounded border text-left transition-all ${
              currentFontFamily === font.value
                ? 'bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black'
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            style={{ fontFamily: font.value }}
          >
            {font.name}
          </button>
        ))}
      </div>
      <button
        onClick={handleClear}
        className={`w-full p-2 rounded border ${hoverClass} border-[var(--color-border-medium)] text-sm`}
      >
        Clear Font Family
      </button>
    </Modal>
  );
}
