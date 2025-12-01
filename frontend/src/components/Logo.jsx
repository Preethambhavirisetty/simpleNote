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
    md: 'text-sm',      // Slightly smaller for compact views
    lg: 'text-xl',      // Larger for prominent placement
    xl: 'text-3xl',     // Extra large for hero sections
  };

  const imageSizes = {
    sm: 'w-12 h-12',    // Perfect for 13" MacBook Pro (48px)
    md: 'w-10 h-10',    // Slightly smaller for compact views (40px)
    lg: 'w-16 h-16',    // Larger for prominent placement (64px)
    xl: 'w-24 h-24',    // Extra large for hero sections (96px)
  };

  return (
    <div
      className={`${className} flex items-center gap-1 relative`}
    >
      {/* Logo Image */}
      <div className={`${imageSizes[size]} flex-shrink-0 relative`}>
        <img
          src={logoImage}
          alt="NoteLite Logo"
          className="w-full h-full object-contain"
          style={{
            // filter: 'drop-shadow(0 2px 8px rgba(0, 0, 0, 0.15))',
          }}
        />
        {/* Subtle glow effect */}
        <div
          className="absolute inset-0 rounded-full bg-gradient-to-br from-[var(--color-accent-primary)] via-[var(--color-accent-primary)] to-[var(--color-accent-secondary)] opacity-10 blur-md -z-10"
          style={{
            transform: 'scale(1.5)',
          }}
        />
      </div>

      {/* Logo Text with improved typography */}
      {showText && (
        <span
          className={`${textSizes[size]} font-bold tracking-tight relative`}
          style={{
            fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", "Roboto", "Helvetica Neue", sans-serif',
            background: 'linear-gradient(135deg, var(--color-accent-primary), var(--color-accent-secondary))',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
            letterSpacing: '-0.02em',
            fontWeight: 700,
            lineHeight: 1.2,
          }}
        >
          NoteLite
        </span>
      )}
    </div>
  );
}

