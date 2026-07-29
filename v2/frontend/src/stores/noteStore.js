import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { notesApi } from '@/api/notes'
import { unwrap, unwrapList } from '@/lib/api'

const pendingNoteLoads = new Map()
const noteSaveQueues = new Map()
let requestedNoteId = null
let activeSaveCount = 0

// ---------- TipTap helpers ----------
// BE field is "content" (TipTap JSON). These helpers convert to/from plain text
// for the baseline textarea editor. Swap out when adding a rich editor.

export function textToTipTap(text = '') {
  return {
    type: 'doc',
    content: text.split('\n').map((line) => ({
      type: 'paragraph',
      content: line ? [{ type: 'text', text: line }] : [],
    })),
  }
}

export function tipTapToText(doc) {
  if (!doc?.content) return ''
  return doc.content
    .map((node) =>
      (node.content ?? [])
        .map((child) => child.text ?? '')
        .join(''),
    )
    .join('\n')
}

function normalizeNote(n) {
  if (!n) return n
  return { ...n, id: n.id ?? n.note_id }
}

// ---------- Store ----------

export const useNoteStore = create(
  devtools(
    (set, get) => ({
      notes: [],
      activeNote: null,
      isLoading: false,
      isSaving: false,
      listError: '',
      openError: '',

      fetchNotes: async (params = {}) => {
        if (get().isLoading) return
        set({ isLoading: true, listError: '' })
        try {
          const { data } = await notesApi.list(params)
          set({ notes: unwrapList(data).map(normalizeNote) })
        } catch (err) {
          console.error('[noteStore] fetchNotes:', err.response?.data ?? err.message)
          set({ listError: err.response?.data?.message ?? 'Could not load notes. Check your connection and try again.' })
        } finally {
          set({ isLoading: false })
        }
      },

      openNote: async (noteId) => {
        if (!noteId) return null

        requestedNoteId = noteId
        if (get().activeNote?.id !== noteId) set({ activeNote: null, openError: '' })

        // URL synchronization and click handlers can request the same note in
        // the same render cycle. Share that request instead of issuing two GETs.
        const pending = pendingNoteLoads.get(noteId)
        if (pending) return pending

        const request = notesApi.get(noteId)
          .then(({ data }) => {
            const note = normalizeNote(unwrap(data))
            if (requestedNoteId === noteId) set({ activeNote: note })
            return note
          })
          .catch((err) => {
            console.error('[noteStore] openNote:', err.response?.data ?? err.message)
            if (requestedNoteId === noteId) {
              set({ openError: err.response?.data?.message ?? 'Could not open this note.' })
            }
            return null
          })
          .finally(() => pendingNoteLoads.delete(noteId))

        pendingNoteLoads.set(noteId, request)
        return request
      },

      createNote: async (payload) => {
        try {
          const body = {
            title: payload.title || 'Untitled',
            // BE field is "content", not "content_json"
            content: payload.content ?? textToTipTap(''),
            ...(payload.folder_id != null && { folder_id: payload.folder_id }),
            ...(payload.description != null && { description: payload.description }),
          }
          const { data } = await notesApi.create(body)
          const note = normalizeNote(unwrap(data))
          requestedNoteId = note.id
          set((s) => ({ notes: [note, ...s.notes], activeNote: note }))
          return { ok: true, note }
        } catch (err) {
          console.error('[noteStore] createNote:', err.response?.data ?? err.message)
          return { ok: false, error: err.response?.data?.detail ?? err.message }
        }
      },

      updateNote: async (noteId, payload) => {
        const previous = noteSaveQueues.get(noteId) ?? Promise.resolve()
        const request = previous.catch(() => {}).then(async () => {
          activeSaveCount += 1
          set({ isSaving: true })
          try {
            const { data } = await notesApi.update(noteId, payload)
            const note = normalizeNote(unwrap(data))
            set((s) => ({
              notes: s.notes.map((n) => (n.id === noteId ? note : n)),
              activeNote: s.activeNote?.id === noteId ? note : s.activeNote,
            }))
            return { ok: true, note }
          } catch (err) {
            console.error('[noteStore] updateNote:', err.response?.data ?? err.message)
            return { ok: false, error: err.response?.data?.message ?? err.response?.data?.detail ?? err.message }
          } finally {
            activeSaveCount -= 1
            set({ isSaving: activeSaveCount > 0 })
          }
        })
        noteSaveQueues.set(noteId, request)
        request.finally(() => {
          if (noteSaveQueues.get(noteId) === request) noteSaveQueues.delete(noteId)
        })
        return request
      },

      addTag: async (noteId, tag) => {
        try {
          await notesApi.addTag(noteId, tag.id)
          set((s) => {
            const add = (note) => note?.id === noteId && !note.tags?.some((item) => item.id === tag.id)
              ? { ...note, tags: [...(note.tags ?? []), tag] }
              : note
            return { notes: s.notes.map(add), activeNote: add(s.activeNote) }
          })
          return { ok: true }
        } catch (err) {
          return { ok: false, error: err.response?.data?.message ?? err.response?.data?.detail ?? err.message }
        }
      },

      removeTag: async (noteId, tagId) => {
        try {
          await notesApi.removeTag(noteId, tagId)
          set((s) => {
            const remove = (note) => note?.id === noteId
              ? { ...note, tags: (note.tags ?? []).filter((tag) => tag.id !== tagId) }
              : note
            return { notes: s.notes.map(remove), activeNote: remove(s.activeNote) }
          })
          return { ok: true }
        } catch (err) {
          return { ok: false, error: err.response?.data?.message ?? err.response?.data?.detail ?? err.message }
        }
      },

      deleteNote: async (noteId) => {
        try {
          await notesApi.delete(noteId)
          if (requestedNoteId === noteId) requestedNoteId = null
          set((s) => ({
            notes: s.notes.filter((n) => n.id !== noteId),
            activeNote: s.activeNote?.id === noteId ? null : s.activeNote,
          }))
          return { ok: true }
        } catch (err) {
          return { ok: false, error: err.response?.data?.detail ?? err.message }
        }
      },

      moveNote: async (noteId, folderId) => {
        try {
          const { data } = await notesApi.move(noteId, { folder_id: folderId })
          const note = normalizeNote(unwrap(data))
          set((s) => ({ notes: s.notes.map((n) => (n.id === noteId ? note : n)) }))
          return { ok: true }
        } catch (err) {
          return { ok: false, error: err.response?.data?.detail ?? err.message }
        }
      },

      clearActiveNote: () => {
        requestedNoteId = null
        set({ activeNote: null, openError: '' })
      },
    }),
    { name: 'note-store' },
  ),
)
