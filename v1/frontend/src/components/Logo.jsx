import React from 'react';
import logoImage from '../assets/notelite_icon.png';

export default function Logo({ size = 'md', showText = false, className = '' }) {
  const sizeClasses = {
    sm: 'w-8 h-8',
    md: 'w-10 h-10',
    lg: 'w-16 h-16',
    xl: 'w-24 h-24',
  };

  const textSizes = {
    sm: 'text-md',      // Perfect for 13" MacBook Pro
    md: 'text-lg',      // Slightly smaller for compact views
    lg: 'text-xl',      // Larger for prominent placement
    xl: 'text-2xl',     // Extra large for hero sections
  };

  const imageSizes = {
    sm: 'w-12 h-12',    // Perfect for 13" MacBook Pro (48px)
    md: 'w-14 h-14',    // Slightly smaller for compact views (40px)
    lg: 'w-16 h-16',    // Larger for prominent placement (64px)
    xl: 'w-20 h-20',    // Extra large for hero sections (96px)
  };

  return (
    <div
      className={`${className} flex items-center -space-x-1.5 relative`}
    >
      {/* Logo Image */}
      <div className={`${imageSizes[size]} flex-shrink-0 relative`}>
        {/* Subtle glow effect */}
        {/* <div
          className="absolute inset-0 rounded-full bg-gradient-to-br from-[var(--color-accent-primary)] via-[var(--color-accent-primary)] to-[var(--color-accent-secondary)] opacity-10 blur-md -z-10"
          style={{
              transform: 'scale(1.5)',
            }}
        /> */}
        <img src={logoImage} alt="NoteLite Logo" className="w-full h-full object-contain" />
      </div>

      {/* Logo Text with improved typography */}
      {showText && (
        <div className="bg-red-0 w-full h-full flex items-center justify-center leading-7 tracking-wide">
        <span className={`${textSizes[size]} font-bold relative`}>
            Note
          </span>
          <span className={`${textSizes[size]} font-medium relative`}>
            Lite
          </span>
        </div>
      )}
    </div>
  );
}

