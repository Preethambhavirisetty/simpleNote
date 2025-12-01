import React from 'react';
import { Moon, Sun, LogOut, User, Menu, X } from 'lucide-react';
import Logo from '../Logo';

export default function TopBar({
  user,
  theme,
  onToggleTheme,
  onLogout,
  onToggleAIPanel,
  showAIPanel,
  documentsCount,
  hasActiveDoc,
  showMobileSidebar,
  onToggleMobileSidebar,
  glassClass,
  hoverClass,
}) {
  return (
    <div
      className={`${glassClass} rounded-lg p-1.5 sm:p-2 mb-1.5 sm:mb-4 flex justify-between items-center relative z-50 border-b border-[var(--color-border-medium)]`}
    >
      <div className="flex items-center gap-2 sm:gap-4">
        {/* Mobile Hamburger Menu */}
        <button
          onClick={onToggleMobileSidebar}
          className={`md:hidden p-1.5 rounded ${hoverClass} border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
          title="Toggle Sidebar"
        >
          {showMobileSidebar ? <X size={18} /> : <Menu size={18} />}
        </button>

        <Logo size="md" showText={true} />
        {hasActiveDoc && (
          <>
            <div className="hidden md:block h-6 w-px bg-[var(--color-border-light)]"></div>
            <div className="hidden md:block text-sm text-[var(--color-text-muted)]">
              {documentsCount} {documentsCount === 1 ? 'document' : 'documents'}
            </div>
          </>
        )}
      </div>
      <div className="flex items-center gap-1 sm:gap-2">
        {/* AI Tools Button */}
        {/* <button
          onClick={onToggleAIPanel}
          className={`px-2 sm:px-3 py-1.5 rounded ${hoverClass} text-xs font-semibold flex items-center gap-1 sm:gap-2 border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
        >
          <span className="text-sm">✨</span>
          <span className="hidden sm:inline">AI Tools</span>
        </button> */}

        {/* Theme Toggle */}
        <button
          onClick={onToggleTheme}
          className={`p-1.5 sm:p-2 border-none rounded ${hoverClass} border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
          title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
        >
          {theme === 'light' ? (
            <Moon size={16} className="sm:w-[18px] sm:h-[18px]" />
          ) : (
            <Sun size={16} className="sm:w-[18px] sm:h-[18px]" />
          )}
        </button>

        {/* Account Info */}
        {user && (
          <>
            <div className="hidden sm:block h-6 w-px bg-[var(--color-border-light)]"></div>
            <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 text-xs">
              <User size={16} className="text-[var(--color-text-muted)]" />
              <span className="text-[var(--color-text-secondary)] font-medium truncate max-w-[150px]">
                {user.email}
              </span>
            </div>
            <button
              onClick={onLogout}
              className={`px-2 sm:px-3 py-1.5 rounded ${hoverClass} text-xs font-semibold flex items-center gap-1 sm:gap-2 border border-[var(--color-border-medium)] hover:border-red-500 hover:text-red-500 transition-colors`}
              title={`Logout ${user.email}`}
            >
              <LogOut size={16} />
              <span className="hidden sm:inline">Logout</span>
            </button>
          </>
        )}
      </div>
    </div>
  );
}

