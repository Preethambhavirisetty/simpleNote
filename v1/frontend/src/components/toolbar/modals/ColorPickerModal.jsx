import React, { useState } from 'react';
import { TEXT_COLORS } from '../../../constants/toolbar';
import Modal from '../../ui/Modal';

export default function ColorPickerModal({
  isOpen,
  onClose,
  editor,
  glassClass,
  hoverClass,
  showToast,
}) {
  const [textColor, setTextColor] = useState('#000000');

  const applyColor = (color) => {
    editor?.chain().focus().setColor(color).run();
    setTextColor(color);
    onClose();
    showToast?.('Color applied', 'success', 1500);
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Text Color" glassClass={glassClass}>
      <div className="grid grid-cols-5 gap-2 mb-4">
        {TEXT_COLORS.map((color) => (
          <button
            key={color}
            onClick={() => applyColor(color)}
            className="w-10 h-10 rounded border-2 border-[var(--color-border-medium)] hover:scale-110 transition-transform"
            style={{ backgroundColor: color }}
            title={color}
          />
        ))}
      </div>
      <div className="flex gap-2">
        <input
          type="color"
          value={textColor}
          onChange={(e) => setTextColor(e.target.value)}
          className="flex-1 h-10 rounded border border-[var(--color-border-medium)]"
        />
        <button
          onClick={() => applyColor(textColor)}
          className={`px-4 py-2 rounded bg-[var(--color-accent-primary)] text-[var(--color-bg-primary)] font-semibold ${hoverClass}`}
        >
          Apply
        </button>
      </div>
    </Modal>
  );
}

