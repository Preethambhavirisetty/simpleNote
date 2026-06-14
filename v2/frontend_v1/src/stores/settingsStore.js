import { create } from 'zustand'

// Lightweight store so Sidebar can open Settings without prop drilling through AppLayout
export const useSettingsStore = create((set) => ({
  isOpen: false,
  open: () => set({ isOpen: true }),
  close: () => set({ isOpen: false }),
  toggle: () => set((s) => ({ isOpen: !s.isOpen })),
}))
