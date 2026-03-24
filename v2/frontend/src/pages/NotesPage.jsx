import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { useNoteStore, textToTipTap, tipTapToText } from '@/stores/noteStore'

// ---------- NoteList ----------

function NoteList({ notes, activeId, isLoading, onSelect, onNew }) {
  return (
    <div className="w-64 flex flex-col border-r border-zinc-800 bg-zinc-900 shrink-0">
      <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
        <h2 className="text-sm font-medium text-zinc-300">Notes</h2>
        <button
          onClick={onNew}
          title="New note"
          className="text-zinc-500 hover:text-zinc-200 w-6 h-6 flex items-center justify-center rounded transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {isLoading && (
          <div className="flex justify-center mt-8">
            <span className="w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
          </div>
        )}

        {!isLoading && notes.length === 0 && (
          <p className="text-xs text-zinc-600 text-center mt-10 px-4">
            No notes yet — click + to create one
          </p>
        )}

        {notes.map((note) => (
          <button
            key={note.id}
            onClick={() => note.id && onSelect(note.id)}
            className={`w-full text-left px-4 py-3 border-b border-zinc-800/50 transition-colors ${
              activeId === note.id ? 'bg-zinc-800' : 'hover:bg-zinc-800/40'
            }`}
          >
            <p className="text-sm text-zinc-200 font-medium truncate">{note.title || 'Untitled'}</p>
            {note.description && (
              <p className="text-xs text-zinc-500 mt-0.5 truncate">{note.description}</p>
            )}
            <p className="text-[11px] text-zinc-600 mt-1">
              {new Date(note.updated_at ?? note.created_at).toLocaleDateString()}
            </p>
          </button>
        ))}
      </div>
    </div>
  )
}

// ---------- NoteEditor ----------

const AUTOSAVE_MS = 1200

function NoteEditor({ note, onSave, isSaving }) {
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [dirty, setDirty] = useState(false)
  const timerRef = useRef(null)
  const latestRef = useRef({ title, content })

  // Sync editor fields whenever the active note changes
  useEffect(() => {
    if (!note) return
    // BE field is "content" (TipTap JSON), not "content_json"
    const text = tipTapToText(note.content ?? note.content_json)
    setTitle(note.title ?? '')
    setContent(text)
    setDirty(false)
    clearTimeout(timerRef.current)
  }, [note?.id])

  // Keep ref current so the debounce closure always reads latest values
  useEffect(() => {
    latestRef.current = { title, content }
  }, [title, content])

  const scheduleAutoSave = useCallback(() => {
    setDirty(true)
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      const { title: t, content: c } = latestRef.current
      // Send "content" — that's the field name the BE uses
      onSave({ title: t, content: textToTipTap(c) })
      setDirty(false)
    }, AUTOSAVE_MS)
  }, [onSave])

  // Flush on unmount so nothing is lost if user navigates away
  useEffect(() => () => clearTimeout(timerRef.current), [])

  if (!note) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-sm text-zinc-600">Select a note or create a new one</p>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <div className="px-6 py-3 border-b border-zinc-800 flex items-center gap-3">
        <input
          value={title}
          onChange={(e) => { setTitle(e.target.value); scheduleAutoSave() }}
          placeholder="Untitled"
          className="flex-1 bg-transparent text-lg font-semibold text-zinc-100 placeholder-zinc-600 focus:outline-none"
        />
        <span className="text-[11px] text-zinc-600 shrink-0">
          {isSaving ? 'Saving…' : dirty ? 'Unsaved' : 'Saved'}
        </span>
      </div>

      <textarea
        value={content}
        onChange={(e) => { setContent(e.target.value); scheduleAutoSave() }}
        placeholder="Start writing…"
        className="flex-1 bg-transparent text-sm text-zinc-200 px-6 py-4 resize-none focus:outline-none placeholder-zinc-600 leading-relaxed"
      />
    </div>
  )
}

// ---------- Page ----------

export default function NotesPage() {
  const { folderId: folderParam } = useParams()
  const [searchParams] = useSearchParams()
  // Guard against the literal string "undefined" from a malformed route
  const raw = folderParam ?? searchParams.get('folder')
  const folderId = raw && raw !== 'undefined' ? raw : null

  const notes = useNoteStore((s) => s.notes)
  const activeNote = useNoteStore((s) => s.activeNote)
  const isLoading = useNoteStore((s) => s.isLoading)
  const isSaving = useNoteStore((s) => s.isSaving)
  const fetchNotes = useNoteStore((s) => s.fetchNotes)
  const openNote = useNoteStore((s) => s.openNote)
  const createNote = useNoteStore((s) => s.createNote)
  const updateNote = useNoteStore((s) => s.updateNote)

  useEffect(() => {
    fetchNotes(folderId ? { folder_id: folderId } : {})
  }, [folderId, fetchNotes])

  const handleNew = useCallback(async () => {
    await createNote({ folder_id: folderId })
  }, [folderId, createNote])

  const handleSave = useCallback(
    (payload) => {
      if (activeNote?.id) updateNote(activeNote.id, payload)
    },
    [activeNote, updateNote],
  )

  return (
    <div className="flex h-full">
      <NoteList
        notes={notes}
        activeId={activeNote?.id}
        isLoading={isLoading}
        onSelect={openNote}
        onNew={handleNew}
      />
      <NoteEditor note={activeNote} onSave={handleSave} isSaving={isSaving} />
    </div>
  )
}
