import React from 'react';

export default function Divider({ orientation = 'horizontal', className = '' }) {
  if (orientation === 'vertical') {
    return (
      <div
        className={`w-px h-6 bg-[var(--color-border-medium)] flex-shrink-0 ${className}`}
      />
    );
  }

  return (
    <div
      className={`h-px w-full bg-[var(--color-border-medium)] ${className}`}
    />
  );
}

