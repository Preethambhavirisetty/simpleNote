import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import Placeholder from '@tiptap/extension-placeholder'
import { useNoteStore } from '@/stores/noteStore'
import { useFolderStore } from '@/stores/folderStore'
import { useTagStore } from '@/stores/tagStore'

const AUTOSAVE_MS = 1200

const icons = {
  search: <><circle cx="11" cy="11" r="6" /><path strokeLinecap="round" d="m16 16 4 4" /></>,
  plus: <path strokeLinecap="round" d="M12 5v14m7-7H5" />,
  pin: <path strokeLinecap="round" strokeLinejoin="round" d="M9 4h6l-1 6 3 3v1H7v-1l3-3-1-6zm3 10v6" />,
  trash: <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.9 12a2 2 0 01-2 2H7.9a2 2 0 01-2-2L5 7m5 4v6m4-6v6m1-10V4h-6v3M4 7h16" />,
  note: <path strokeLinecap="round" strokeLinejoin="round" d="M8 6h8M8 10h8M8 14h5m5 7H6a2 2 0 01-2-2V5a2 2 0 012-2h8l4 4v10a2 2 0 01-2 2z" />,
  back: <path strokeLinecap="round" strokeLinejoin="round" d="m15 18-6-6 6-6" />,
}

function Icon({ name, className = 'h-4 w-4' }) {
  return <svg className={className} fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">{icons[name]}</svg>
}

function parseContent(raw) {
  if (raw && typeof raw === 'object' && raw.type === 'doc') return raw
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw)
      if (parsed?.type === 'doc') return parsed
    } catch { /* plain text fallback */ }
    return { type: 'doc', content: raw.split('\n').map((line) => ({ type: 'paragraph', content: line ? [{ type: 'text', text: line }] : [] })) }
  }
  return { type: 'doc', content: [{ type: 'paragraph' }] }
}

function textFromContent(content) {
  if (typeof content === 'string') return content
  const parts = []
  const walk = (node) => {
    if (node?.text) parts.push(node.text)
    node?.content?.forEach(walk)
  }
  walk(content)
  return parts.join(' ')
}

function relativeTime(date) {
  if (!date) return 'Just now'
  const seconds = Math.floor((Date.now() - new Date(date).getTime()) / 1000)
  if (seconds < 60) return 'Just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr`
  if (seconds < 604800) return `${Math.floor(seconds / 86400)} day`
  return new Date(date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export default function NotesPage() {
  const { folderId } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const noteId = searchParams.get('note')

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
  const addTag = useNoteStore((s) => s.addTag)
  const removeTag = useNoteStore((s) => s.removeTag)
  const folders = useFolderStore((s) => (Array.isArray(s.folders) ? s.folders : []))
  const createFolder = useFolderStore((s) => s.createFolder)
  const tags = useTagStore((s) => s.tags)
  const createTag = useTagStore((s) => s.createTag)

  const [search, setSearch] = useState('')
  const currentFolder = folders.find((folder) => String(folder.id) === String(folderId))

  useEffect(() => { fetchNotes() }, [fetchNotes])
  useEffect(() => {
    if (noteId) openNote(noteId)
    else clearActiveNote()
  }, [noteId, openNote, clearActiveNote])

  const visibleNotes = useMemo(() => {
    const query = search.trim().toLowerCase()
    return notes
      .filter((note) => !folderId || String(note.folder_id) === String(folderId))
      .filter((note) => !query || `${note.title} ${note.description ?? ''} ${note.content_text ?? textFromContent(note.content)}`.toLowerCase().includes(query))
      .sort((a, b) => Number(Boolean(b.is_pinned)) - Number(Boolean(a.is_pinned)) || new Date(b.updated_at) - new Date(a.updated_at))
  }, [folderId, notes, search])

  const openFromList = (id) => navigate(`${folderId ? `/folders/${folderId}` : '/notes'}?note=${id}`)

  const handleNew = async () => {
    let targetFolderId = folderId ?? folders[0]?.id
    if (!targetFolderId) {
      const result = await createFolder({ name: 'General' })
      targetFolderId = result?.folder?.id
    }
    if (!targetFolderId) return
    const result = await createNote({ folder_id: targetFolderId, title: 'Untitled note' })
    if (result?.ok) navigate(`/folders/${targetFolderId}?note=${result.note.id}`)
  }

  const handleDelete = async (id) => {
    await deleteNote(id)
    if (String(id) === String(noteId)) navigate(folderId ? `/folders/${folderId}` : '/notes')
  }

  return (
    <div className="notes-desk h-full">
      <NoteBrowser
        title={currentFolder?.name || 'All notes'}
        notes={visibleNotes}
        activeId={noteId}
        search={search}
        setSearch={setSearch}
        isLoading={isLoading}
        onSelect={openFromList}
        onNew={handleNew}
        onDelete={handleDelete}
        onPin={(note) => updateNote(note.id, { is_pinned: !note.is_pinned })}
      />
      <NoteEditor
        note={activeNote}
        isSaving={isSaving}
        onSave={(id, payload) => updateNote(id, payload)}
        tags={tags}
        onCreateTag={createTag}
        onAddTag={(tag) => activeNote?.id && addTag(activeNote.id, tag)}
        onRemoveTag={(tag) => activeNote?.id && removeTag(activeNote.id, tag)}
        onBack={() => navigate(folderId ? `/folders/${folderId}` : '/notes')}
        onDelete={() => activeNote?.id && handleDelete(activeNote.id)}
      />
    </div>
  )
}

function NoteBrowser({ title, notes, activeId, search, setSearch, isLoading, onSelect, onNew, onDelete, onPin }) {
  return (
    <section className={`notes-browser ${activeId ? 'notes-browser-has-selection' : ''}`}>
      <div className="notes-browser-header">
        <div>
          <p className="workspace-faint text-[10px] font-semibold uppercase tracking-[0.16em]">Workspace</p>
          <h1 className="workspace-primary mt-1 text-2xl font-semibold tracking-[-0.04em]">{title}</h1>
        </div>
        <button onClick={onNew} className="note-new-button" title="Create note"><Icon name="plus" /></button>
      </div>

      <label className="notes-search">
        <Icon name="search" className="h-4 w-4 shrink-0" />
        <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search notes..." />
        {search && <button onClick={() => setSearch('')} className="workspace-faint text-xs">Clear</button>}
      </label>

      <div className="workspace-scroll flex-1 overflow-y-auto px-4 pb-5">
        {isLoading && notes.length === 0 && <div className="flex justify-center py-12"><span className="note-spinner" /></div>}
        {!isLoading && notes.length === 0 && (
          <button onClick={onNew} className="notes-empty-card">
            <span className="notes-empty-icon"><Icon name="note" className="h-5 w-5" /></span>
            <span className="workspace-primary text-sm font-medium">Start a fresh note</span>
            <span className="workspace-faint mt-1 text-xs">Your ideas will appear here.</span>
          </button>
        )}
        <div className="space-y-3">
          {notes.map((note, index) => (
            <NoteCard key={note.id} note={note} index={index} active={String(activeId) === String(note.id)} onSelect={onSelect} onDelete={onDelete} onPin={onPin} />
          ))}
        </div>
      </div>
    </section>
  )
}

function NoteCard({ note, index, active, onSelect, onDelete, onPin }) {
  const preview = note.description || note.content_text || textFromContent(note.content) || 'Start writing to bring this note to life.'
  return (
    <article onClick={() => onSelect(note.id)} className={`note-card group ${active ? 'note-card-active' : ''}`} style={{ animationDelay: `${Math.min(index, 8) * 35}ms` }}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="workspace-primary truncate text-sm font-semibold">{note.title || 'Untitled note'}</h2>
          <p className="workspace-muted mt-2 line-clamp-2 text-xs leading-5">{preview}</p>
        </div>
        <span className={`note-card-dot ${note.is_pinned ? 'note-card-dot-pinned' : ''}`} />
      </div>
      {note.tags?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {note.tags.slice(0, 3).map((tag) => <span key={tag.id} className="note-tag">#{tag.name}</span>)}
        </div>
      )}
      <div className="mt-4 flex items-center justify-between">
        <span className="workspace-faint text-[10px]">{relativeTime(note.updated_at ?? note.created_at)}</span>
        <div className="note-card-actions">
          <button onClick={(event) => { event.stopPropagation(); onPin(note) }} className={note.is_pinned ? 'text-[var(--accent)]' : ''} title={note.is_pinned ? 'Unpin note' : 'Pin note'}><Icon name="pin" className="h-3.5 w-3.5" /></button>
          <button onClick={(event) => { event.stopPropagation(); onDelete(note.id) }} className="hover:text-red-500" title="Delete note"><Icon name="trash" className="h-3.5 w-3.5" /></button>
        </div>
      </div>
    </article>
  )
}

function NoteEditor({ note, onSave, isSaving, onBack, onDelete, tags, onCreateTag, onAddTag, onRemoveTag }) {
  const [title, setTitle] = useState('')
  const [dirty, setDirty] = useState(false)
  const timerRef = useRef(null)
  const noteIdRef = useRef(note?.id)
  const titleRef = useRef('')
  const noteSnapshotRef = useRef(note)
  const onSaveRef = useRef(onSave)
  useEffect(() => { noteSnapshotRef.current = note; noteIdRef.current = note?.id }, [note])
  useEffect(() => { onSaveRef.current = onSave }, [onSave])

  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
      Underline,
      Placeholder.configure({ placeholder: 'Start writing your idea...' }),
    ],
    content: { type: 'doc', content: [{ type: 'paragraph' }] },
    immediatelyRender: false,
    editorProps: { attributes: { class: 'tiptap-note note-writing-canvas focus:outline-none' } },
    onUpdate: ({ editor: instance }) => {
      setDirty(true)
      clearTimeout(timerRef.current)
      const content = instance.getJSON()
      timerRef.current = setTimeout(() => {
        timerRef.current = null
        onSaveRef.current(noteIdRef.current, { title: titleRef.current, content })
        setDirty(false)
      }, AUTOSAVE_MS)
    },
  })

  useEffect(() => {
    const selectedNote = noteSnapshotRef.current
    if (!selectedNote || !editor || editor.isDestroyed) return
    clearTimeout(timerRef.current)
    const nextTitle = selectedNote.title ?? ''
    titleRef.current = nextTitle
    editor.commands.setContent(parseContent(selectedNote.content), false)
    queueMicrotask(() => {
      setTitle(nextTitle)
      setDirty(false)
    })
  }, [note?.id, editor])

  useEffect(() => () => {
    if (!timerRef.current || !note?.id || !editor || editor.isDestroyed) return
    clearTimeout(timerRef.current)
    timerRef.current = null
    onSaveRef.current(note.id, { title: titleRef.current, content: editor.getJSON() })
  }, [editor, note?.id])

  const handleTitle = (event) => {
    const value = event.target.value
    setTitle(value)
    titleRef.current = value
    setDirty(true)
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      timerRef.current = null
      onSaveRef.current(noteIdRef.current, { title: value, content: editor?.getJSON() })
      setDirty(false)
    }, AUTOSAVE_MS)
  }

  if (!note) return <EditorWelcome />

  return (
    <section className="note-editor-panel">
      <div className="note-editor-topbar">
        <button onClick={onBack} className="note-mobile-back" title="Back to notes"><Icon name="back" /></button>
        <span className="save-status"><span className={`save-dot ${dirty || isSaving ? 'save-dot-working' : ''}`} />{isSaving ? 'Saving' : dirty ? 'Unsaved' : 'Saved'}</span>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={onDelete} className="editor-icon-button hover:text-red-500" title="Delete note"><Icon name="trash" /></button>
          <button className="editor-icon-button" title="More options">•••</button>
        </div>
      </div>

      <EditorToolbar editor={editor} />

      <div className="workspace-scroll min-h-0 flex-1 overflow-y-auto">
        <div className="note-page">
          <TagEditor note={note} tags={tags} onCreate={onCreateTag} onAdd={onAddTag} onRemove={onRemoveTag} />
          <input value={title} onChange={handleTitle} placeholder="Untitled note" className="note-title-input" />
          <div className="workspace-faint mb-9 mt-3 flex items-center gap-2 text-[10px]">
            <span>Last edited {relativeTime(note.updated_at)}</span><span>•</span><span>Autosaved</span>
          </div>
          <EditorContent editor={editor} />
        </div>
      </div>
    </section>
  )
}

function TagEditor({ note, tags, onCreate, onAdd, onRemove }) {
  const [name, setName] = useState('')
  const attachedIds = new Set(note.tags?.map((tag) => tag.id) ?? [])
  const available = tags.filter((tag) => !attachedIds.has(tag.id))

  const handleCreate = async (event) => {
    event.preventDefault()
    const value = name.trim()
    if (!value) return
    const result = await onCreate(value)
    if (result?.ok) {
      await onAdd(result.tag)
      setName('')
    }
  }

  return (
    <div className="tag-editor">
      <div className="flex flex-wrap gap-2">
        {note.tags?.map((tag) => (
          <button key={tag.id} onClick={() => onRemove(tag)} className="note-tag tag-remove" title={`Remove ${tag.name}`}>#{tag.name} <span>×</span></button>
        ))}
        {available.length > 0 && (
          <select defaultValue="" onChange={(event) => { const tag = tags.find((item) => item.id === event.target.value); if (tag) onAdd(tag); event.target.value = "" }} className="tag-select">
            <option value="" disabled>Add tag</option>
            {available.map((tag) => <option key={tag.id} value={tag.id}>{tag.name}</option>)}
          </select>
        )}
      </div>
      <form onSubmit={handleCreate} className="tag-create">
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Create a tag" maxLength={100} />
        <button type="submit" disabled={!name.trim()}>Add</button>
      </form>
    </div>
  )
}

function EditorToolbar({ editor }) {
  if (!editor) return null
  const controls = [
    ['B', 'Bold', () => editor.chain().focus().toggleBold().run(), editor.isActive('bold')],
    ['I', 'Italic', () => editor.chain().focus().toggleItalic().run(), editor.isActive('italic')],
    ['U', 'Underline', () => editor.chain().focus().toggleUnderline().run(), editor.isActive('underline')],
    ['H1', 'Heading 1', () => editor.chain().focus().toggleHeading({ level: 1 }).run(), editor.isActive('heading', { level: 1 })],
    ['H2', 'Heading 2', () => editor.chain().focus().toggleHeading({ level: 2 }).run(), editor.isActive('heading', { level: 2 })],
    ['• List', 'Bullet list', () => editor.chain().focus().toggleBulletList().run(), editor.isActive('bulletList')],
    ['1. List', 'Numbered list', () => editor.chain().focus().toggleOrderedList().run(), editor.isActive('orderedList')],
    ['</>', 'Code', () => editor.chain().focus().toggleCodeBlock().run(), editor.isActive('codeBlock')],
  ]
  return (
    <div className="editor-toolbar workspace-scroll">
      {controls.map(([label, title, action, active]) => <button key={title} onClick={action} title={title} className={active ? 'editor-tool-active' : ''}>{label}</button>)}
    </div>
  )
}

function EditorWelcome() {
  return (
    <section className="note-editor-panel items-center justify-center text-center">
      <div className="editor-welcome-icon">✦</div>
      <p className="workspace-faint mt-6 text-[10px] font-semibold uppercase tracking-[0.18em]">A quiet place to think</p>
      <h2 className="workspace-primary mt-3 text-3xl font-semibold tracking-[-0.04em]">Pick a note and start writing.</h2>
      <p className="workspace-muted mt-3 max-w-sm text-sm leading-6">Select a card from the left or create a new note. Changes save automatically as you write.</p>
    </section>
  )
}
