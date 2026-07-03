import { create } from 'zustand'
import client from '@/api/client'

export const useFeatureFlagStore = create((set, get) => ({
  flags: {},
  loaded: false,
  loading: false,

  fetchFlags: async () => {
    if (get().loading) return
    set({ loading: true })
    try {
      const { data } = await client.get('/api/feature-flags')
      set({ flags: data, loaded: true })
    } catch {
      set({ flags: {}, loaded: true })
    } finally {
      set({ loading: false })
    }
  },

  isEnabled: (key) => !!get().flags[key],
}))
