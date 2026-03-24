import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { tagsApi } from '@/api/tags'
import { unwrap, unwrapList } from '@/lib/api'

export const useTagStore = create(
  devtools(
    (set) => ({
      tags: [],
      isLoading: false,

      fetchTags: async () => {
        set({ isLoading: true })
        try {
          const { data } = await tagsApi.list()
          set({ tags: unwrapList(data) })
        } catch (err) {
          console.error('[tagStore] fetchTags:', err.response?.data ?? err.message)
        } finally {
          set({ isLoading: false })
        }
      },

      createTag: async (name) => {
        try {
          const { data } = await tagsApi.create({ name })
          const tag = unwrap(data)
          set((s) => ({
            tags: [...s.tags, tag].sort((a, b) => a.name.localeCompare(b.name)),
          }))
          return { ok: true, tag }
        } catch (err) {
          return { ok: false, error: err.response?.data?.detail ?? err.message }
        }
      },

      updateTag: async (tagId, name) => {
        try {
          const { data } = await tagsApi.update(tagId, { name })
          const tag = unwrap(data)
          set((s) => ({ tags: s.tags.map((t) => (t.id === tagId ? tag : t)) }))
          return { ok: true }
        } catch (err) {
          return { ok: false, error: err.response?.data?.detail ?? err.message }
        }
      },

      deleteTag: async (tagId) => {
        try {
          await tagsApi.delete(tagId)
          set((s) => ({ tags: s.tags.filter((t) => t.id !== tagId) }))
          return { ok: true }
        } catch (err) {
          return { ok: false, error: err.response?.data?.detail ?? err.message }
        }
      },
    }),
    { name: 'tag-store' },
  ),
)
