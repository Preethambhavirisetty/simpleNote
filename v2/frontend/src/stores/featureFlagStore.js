import { create } from 'zustand'
import client from '@/api/client'

export const useFeatureFlagStore = create((set, get) => ({
  flags: {},
  loaded: false,

  fetchFlags: async () => {
    try {
      const { data } = await client.get('/api/feature-flags')
      set({ flags: data, loaded: true })
    } catch {
      set({ flags: {}, loaded: true })
    }
  },

  isEnabled: (key) => !!get().flags[key],
}))
