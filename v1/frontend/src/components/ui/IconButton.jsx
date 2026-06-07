import React from 'react';

export default function IconButton({
  onClick,
  icon: Icon,
  title,
  isActive = false,
  disabled = false,
  size = 14,
  className = '',
  hoverClass = 'hover:bg-[var(--color-hover)] transition-all duration-150',
}) {
  const baseClass = `p-2 rounded transition-all border`;
  const activeClass = isActive
    ? 'bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black'
    : `${hoverClass} border-[var(--color-border-medium)]`;

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`${baseClass} ${activeClass} ${className} ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
      title={title}
    >
      <Icon size={size} strokeWidth={2} className="mx-auto" />
    </button>
  );
}

