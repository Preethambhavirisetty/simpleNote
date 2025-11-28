import React from 'react';

export default function LoadingSpinner({
  size = 'md',
  message = '',
  className = '',
}) {
  const sizeClasses = {
    sm: 'w-6 h-6 border-2',
    md: 'w-12 h-12 border-4',
    lg: 'w-16 h-16 border-4',
  };

  return (
    <div className={`flex flex-col items-center gap-4 ${className}`}>
      <div
        className={`${sizeClasses[size] || sizeClasses.md} border-[var(--color-accent-primary)] border-t-transparent rounded-full animate-spin`}
      />
      {message && (
        <p className="text-[var(--color-text-primary)] text-lg font-medium">
          {message}
        </p>
      )}
    </div>
  );
}

