import { create } from 'zustand'
import { persist } from 'zustand/middleware'

function applyTheme(theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

export const useThemeStore = create(
  persist(
    (set, get) => ({
      theme: 'dark',

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
    }),
    { name: 'notelite-theme' },
  ),
)
