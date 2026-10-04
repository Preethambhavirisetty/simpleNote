import { create } from 'zustand'
import { persist } from 'zustand/middleware'

const DEFAULT_THEME = 'dark'

function applyTheme(theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

export const useThemeStore = create(
  persist(
    (set, get) => ({
      theme: DEFAULT_THEME,

      // Call once on app mount to re-apply persisted theme
      init: () => applyTheme(get().theme),

      setTheme: (theme) => {
        set({ theme })
        applyTheme(theme)
      },

      toggleTheme: () => {
        const next = get().theme === 'dark' ? 'light' : 'dark'
        set({ theme: next })
        applyTheme(next)
      },

      reset: () => {
        set({ theme: DEFAULT_THEME })
        applyTheme(DEFAULT_THEME)
      },
    }),
    { name: 'notelite-theme' },
  ),
)
