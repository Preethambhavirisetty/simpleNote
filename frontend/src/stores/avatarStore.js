import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export const useAvatarStore = create(
  persist(
    (set) => ({
      avatar: { type: 'character', value: 0 },
      setCharacter: (value) => set({ avatar: { type: 'character', value } }),
      setImage: (value) => set({ avatar: { type: 'image', value } }),
    }),
    { name: 'notelite-avatar' },
  ),
)
