import React from 'react';

export default function Modal({
  isOpen,
  onClose,
  title,
  children,
  glassClass = 'glass',
  minWidth = '320px',
  maxWidth = 'md',
}) {
  if (!isOpen) return null;

  const maxWidthClass = {
    sm: 'max-w-sm',
    md: 'max-w-md',
    lg: 'max-w-lg',
    xl: 'max-w-xl',
  }[maxWidth] || 'max-w-md';

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-[1000]"
      onClick={onClose}
    >
      <div
        className={`${glassClass} rounded-lg p-6 ${maxWidthClass} border border-[var(--color-border-medium)] shadow-2xl`}
        style={{ minWidth }}
        onClick={(e) => e.stopPropagation()}
      >
        {title && <h3 className="text-sm font-bold mb-4">{title}</h3>}
        {children}
      </div>
    </div>
  );
}

