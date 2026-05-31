import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useParams, useSearchParams } from 'react-router-dom'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import Placeholder from '@tiptap/extension-placeholder'
import { useNoteStore } from '@/stores/noteStore'

// ---------- helpers ----------

function parseContent(raw) {
  if (raw && typeof raw === 'object' && raw.type === 'doc') return raw
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw)
      if (parsed?.type === 'doc') return parsed
    } catch { /* fall through */ }
    // Plain-text fallback (old notes saved before TipTap)
    return {
      type: 'doc',
      content: raw.split('\n').map((line) => ({
        type: 'paragraph',
        content: line ? [{ type: 'text', text: line }] : [],
      })),
    }
  }
  return { type: 'doc', content: [{ type: 'paragraph' }] }
}

// ---------- Icons ----------

function ThreeDotsIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
      <circle cx="4" cy="10" r="1.5" />
      <circle cx="10" cy="10" r="1.5" />
      <circle cx="16" cy="10" r="1.5" />
    </svg>
  )
}

// ---------- Floating selection toolbar ----------

function useSelectionRect(editor) {
  const [rect, setRect] = useState(null)

  useEffect(() => {
    if (!editor) return

    const update = () => {
      // Wait one frame so the DOM selection is up to date
      requestAnimationFrame(() => {
        const { from, to } = editor.state.selection
        if (from === to) { setRect(null); return }

        const sel = window.getSelection()
        if (!sel || sel.rangeCount === 0 || sel.isCollapsed) { setRect(null); return }

        const r = sel.getRangeAt(0).getBoundingClientRect()
        setRect(r.width > 0 ? r : null)
      })
    }

    editor.on('selectionUpdate', update)
    editor.on('focus', update)
    editor.on('blur', () => setRect(null))

    return () => {
      editor.off('selectionUpdate', update)
      editor.off('focus', update)
      editor.off('blur', () => setRect(null))
    }
  }, [editor])

  return rect
}

function BubbleBtn({ onClick, isActive, title, children }) {
  return (
    <button
      // preventDefault keeps editor focus when clicking the button
      onMouseDown={(e) => { e.preventDefault(); onClick() }}
      title={title}
      className={`px-2.5 py-1.5 text-xs font-medium transition-colors ${
        isActive
          ? 'bg-zinc-200 dark:bg-zinc-700 text-indigo-600 dark:text-indigo-400'
          : 'text-zinc-600 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 hover:text-zinc-900 dark:hover:text-zinc-100'
      }`}
    >
      {children}
    </button>
  )
}

function BubbleDivider() {
  return <span className="w-px h-5 bg-zinc-300 dark:bg-zinc-700 shrink-0" />
}

function FloatingToolbar({ editor }) {
  const rect = useSelectionRect(editor)

  if (!rect || !editor) return null

  return createPortal(
    <div
      style={{
        position: 'fixed',
        top: rect.top - 8,
        left: rect.left + rect.width / 2,
        transform: 'translateX(-50%) translateY(-100%)',
        zIndex: 9999,
      }}
    >
      <div className="flex items-center bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg shadow-2xl overflow-hidden">
        <BubbleBtn onClick={() => editor.chain().focus().toggleBold().run()} isActive={editor.isActive('bold')} title="Bold (⌘B)">
          <strong>B</strong>
        </BubbleBtn>
        <BubbleBtn onClick={() => editor.chain().focus().toggleItalic().run()} isActive={editor.isActive('italic')} title="Italic (⌘I)">
          <em>I</em>
        </BubbleBtn>
        <BubbleBtn onClick={() => editor.chain().focus().toggleUnderline().run()} isActive={editor.isActive('underline')} title="Underline (⌘U)">
          <span className="underline">U</span>
        </BubbleBtn>
        <BubbleBtn onClick={() => editor.chain().focus().toggleStrike().run()} isActive={editor.isActive('strike')} title="Strikethrough">
          <span className="line-through">S</span>
        </BubbleBtn>
        <BubbleBtn onClick={() => editor.chain().focus().toggleCode().run()} isActive={editor.isActive('code')} title="Inline code">
          {'</>'}
        </BubbleBtn>

        <BubbleDivider />

        <BubbleBtn onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()} isActive={editor.isActive('heading', { level: 1 })} title="Heading 1">
          H1
        </BubbleBtn>
        <BubbleBtn onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} isActive={editor.isActive('heading', { level: 2 })} title="Heading 2">
          H2
        </BubbleBtn>
        <BubbleBtn onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()} isActive={editor.isActive('heading', { level: 3 })} title="Heading 3">
          H3
        </BubbleBtn>

        <BubbleDivider />

        <BubbleBtn onClick={() => editor.chain().focus().toggleBulletList().run()} isActive={editor.isActive('bulletList')} title="Bullet list">
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </BubbleBtn>
        <BubbleBtn onClick={() => editor.chain().focus().toggleOrderedList().run()} isActive={editor.isActive('orderedList')} title="Numbered list">
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
          </svg>
        </BubbleBtn>
      </div>
    </div>,
    document.body,
  )
}

// ---------- NoteList ----------

function NoteList({ notes, activeId, isLoading, onSelect, onNew, onDelete }) {
  const [openMenuId, setOpenMenuId] = useState(null)

  useEffect(() => {
    if (!openMenuId) return
    const handler = (e) => {
      if (!e.target.closest('[data-note-menu]')) setOpenMenuId(null)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [openMenuId])

  return (
    <div className="w-64 flex flex-col border-r border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 shrink-0">
      <div className="px-4 py-3 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
        <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Notes</h2>
        <button
          onClick={onNew}
          title="New note"
          className="text-zinc-400 dark:text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-200 w-6 h-6 flex items-center justify-center rounded transition-colors"
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
          <p className="text-xs text-zinc-500 dark:text-zinc-600 text-center mt-10 px-4">
            No notes yet — click + to create one
          </p>
        )}

        {notes.map((note) => (
          <div key={note.id} className="relative group border-b border-zinc-200/60 dark:border-zinc-800/50">
            <button
              onClick={() => note.id && onSelect(note.id)}
              className={`w-full text-left px-4 py-3 pr-8 transition-colors ${
                activeId === note.id
                  ? 'bg-zinc-100 dark:bg-zinc-800'
                  : 'hover:bg-zinc-100/70 dark:hover:bg-zinc-800/40'
              }`}
            >
              <p className="text-sm text-zinc-800 dark:text-zinc-200 font-medium truncate">{note.title || 'Untitled'}</p>
              {note.description && (
                <p className="text-xs text-zinc-500 mt-0.5 truncate">{note.description}</p>
              )}
              <p className="text-label text-zinc-400 dark:text-zinc-600 mt-1">
                {new Date(note.updated_at ?? note.created_at).toLocaleDateString()}
              </p>
            </button>

            <button
              data-note-menu
              onClick={(e) => { e.stopPropagation(); setOpenMenuId(openMenuId === note.id ? null : note.id) }}
              className={`absolute right-2 top-3 w-5 h-5 flex items-center justify-center rounded hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors ${
                openMenuId === note.id ? 'opacity-100 text-zinc-600 dark:text-zinc-300' : 'opacity-0 group-hover:opacity-100 text-zinc-400 dark:text-zinc-500'
              }`}
            >
              <ThreeDotsIcon />
            </button>

            {openMenuId === note.id && (
              <div
                data-note-menu
                className="absolute right-2 top-8 z-50 mt-0.5 w-28 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg shadow-xl overflow-hidden"
              >
                <button
                  onClick={(e) => { e.stopPropagation(); setOpenMenuId(null); onDelete(note.id) }}
                  className="w-full text-left px-3 py-2 text-xs text-red-500 dark:text-red-400 hover:bg-zinc-100 dark:hover:bg-zinc-700 transition-colors"
                >
                  Delete
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------- NoteEditor ----------

const AUTOSAVE_MS = 1200

function NoteEditor({ note, onSave, isSaving }) {
  const [title, setTitle] = useState('')
  const [dirty, setDirty] = useState(false)
  const timerRef = useRef(null)
  const titleRef = useRef('')
  const onSaveRef = useRef(onSave)
  useEffect(() => { onSaveRef.current = onSave }, [onSave])

  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
      Underline,
      Placeholder.configure({ placeholder: 'Start writing…' }),
    ],
    content: { type: 'doc', content: [{ type: 'paragraph' }] },
    immediatelyRender: false,
    editorProps: {
      attributes: { class: 'tiptap-note focus:outline-none' },
    },
    onUpdate: ({ editor }) => {
      setDirty(true)
      clearTimeout(timerRef.current)
      const json = editor.getJSON()
      // console.log("SAMPLE JSON", json);
      timerRef.current = setTimeout(() => {
        onSaveRef.current({ title: titleRef.current, content: json })
        setDirty(false)
      }, AUTOSAVE_MS)
    },
  })

  // Load content when switching notes
  useEffect(() => {
    if (!note || !editor || editor.isDestroyed) return
    clearTimeout(timerRef.current)
    setDirty(false)
    const t = note.title ?? ''
    setTitle(t)
    titleRef.current = t
    editor.commands.setContent(parseContent(note.content ?? note.content_json), false)
  }, [note?.id, editor])

  useEffect(() => { titleRef.current = title }, [title])
  useEffect(() => () => clearTimeout(timerRef.current), [])

  const handleTitleChange = (e) => {
    const val = e.target.value
    setTitle(val)
    titleRef.current = val
    setDirty(true)
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      onSaveRef.current({ title: titleRef.current, content: editor?.getJSON() })
      setDirty(false)
    }, AUTOSAVE_MS)
  }

  if (!note) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-sm text-zinc-400 dark:text-zinc-600">Select a note or create a new one</p>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col min-w-0">
      {/* Title bar */}
      <div className="px-6 py-3 border-b border-zinc-200 dark:border-zinc-800 flex items-center gap-3 shrink-0">
        <input
          value={title}
          onChange={handleTitleChange}
          placeholder="Untitled"
          className="flex-1 bg-transparent text-lg font-semibold text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 dark:placeholder-zinc-600 focus:outline-none"
        />
        <span className="text-label text-zinc-400 dark:text-zinc-600 shrink-0">
          {isSaving ? 'Saving…' : dirty ? 'Unsaved' : 'Saved'}
        </span>
      </div>

      <FloatingToolbar editor={editor} />

      {/* Editor content */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}

// ---------- Page ----------

export default function NotesPage() {
  const { folderId: folderParam } = useParams()
  const [searchParams] = useSearchParams()
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
  const deleteNote = useNoteStore((s) => s.deleteNote)
  const clearActiveNote = useNoteStore((s) => s.clearActiveNote)

  const noteParam = searchParams.get('note')

  useEffect(() => {
    clearActiveNote()
    fetchNotes(folderId ? { folder_id: folderId } : {})
  }, [folderId, fetchNotes, clearActiveNote])

  useEffect(() => {
    if (noteParam && notes.length > 0 && !isLoading) {
      openNote(noteParam)
    }
  }, [noteParam, notes.length, isLoading, openNote])

  const handleNew = useCallback(async () => {
    await createNote({ folder_id: folderId })
  }, [folderId, createNote])

  const handleSave = useCallback(
    (payload) => { if (activeNote?.id) updateNote(activeNote.id, payload) },
    [activeNote, updateNote],
  )

  const handleDelete = useCallback(
    async (noteId) => { await deleteNote(noteId) },
    [deleteNote],
  )

  return (
    <div className="flex h-full">
      <NoteList
        notes={notes}
        activeId={activeNote?.id}
        isLoading={isLoading}
        onSelect={openNote}
        onNew={handleNew}
        onDelete={handleDelete}
      />
      <NoteEditor note={activeNote} onSave={handleSave} isSaving={isSaving} />
    </div>
  )
}
