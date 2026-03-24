import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { foldersApi } from '@/api/folders'
import { unwrap, unwrapList } from '@/lib/api'

function normalize(f) {
  if (!f) return f
  return { ...f, id: f.id ?? f.folder_id }
}

export const useFolderStore = create(
  devtools(
    (set) => ({
      folders: [],
      isLoading: false,

      fetchFolders: async () => {
        set({ isLoading: true })
        try {
          const { data } = await foldersApi.list()
          set({ folders: unwrapList(data).map(normalize) })
        } catch (err) {
          console.error('[folderStore] fetchFolders:', err.response?.data ?? err.message)
        } finally {
          set({ isLoading: false })
        }
      },

      createFolder: async (payload) => {
        try {
          const { data } = await foldersApi.create(payload)
          const folder = normalize(unwrap(data))
          set((s) => ({ folders: [...s.folders, folder] }))
          return { ok: true, folder }
        } catch (err) {
          console.error('[folderStore] createFolder:', err.response?.data ?? err.message)
          return { ok: false, error: err.response?.data?.detail ?? err.message }
        }
      },

      updateFolder: async (folderId, payload) => {
        try {
          const { data } = await foldersApi.update(folderId, payload)
          const folder = normalize(unwrap(data))
          set((s) => ({ folders: s.folders.map((f) => (f.id === folderId ? folder : f)) }))
          return { ok: true, folder }
        } catch (err) {
          return { ok: false, error: err.response?.data?.detail ?? err.message }
        }
      },

      deleteFolder: async (folderId) => {
        try {
          await foldersApi.delete(folderId)
          set((s) => ({ folders: s.folders.filter((f) => f.id !== folderId) }))
          return { ok: true }
        } catch (err) {
          return { ok: false, error: err.response?.data?.detail ?? err.message }
        }
      },
    }),
    { name: 'folder-store' },
  ),
)
