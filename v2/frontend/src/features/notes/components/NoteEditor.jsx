import { useEffect, useRef, useState } from 'react'
import { EditorContent, useEditor } from '@tiptap/react'
import FontFamily from '@tiptap/extension-font-family'
import Highlight from '@tiptap/extension-highlight'
import Link from '@tiptap/extension-link'
import Placeholder from '@tiptap/extension-placeholder'
import StarterKit from '@tiptap/starter-kit'
import TextAlign from '@tiptap/extension-text-align'
import { FontSize, TextStyle } from '@tiptap/extension-text-style'
import Underline from '@tiptap/extension-underline'
import { parseNoteContent } from '@/lib/noteEditor'
import { AUTOSAVE_DELAY_MS, NOTE_DRAFT_STORAGE_PREFIX } from '../noteEditorConfig'
import { formatRelativeTime } from '../noteUtils'
import NoteEditorToolbar from './NoteEditorToolbar'
import NoteIcon from './NoteIcon'
import NoteTagEditor from './NoteTagEditor'
import { NoteEditorWelcome } from './NoteEditorStates'

export default function NoteEditor({ note, onSave, onBack, onDelete, onAddTag, onRemoveTag }) {
  const [title, setTitle] = useState('')
  const [saveState, setSaveState] = useState('saved')
  const [saveError, setSaveError] = useState('')
  const timerRef = useRef(null)
  const titleRef = useRef('')
  const noteRef = useRef(note)
  const onSaveRef = useRef(onSave)
  const pendingDraftRef = useRef(null)
  const saveQueueRef = useRef(Promise.resolve())

  useEffect(() => { noteRef.current = note }, [note])
  useEffect(() => { onSaveRef.current = onSave }, [onSave])

  const persistDraft = (draft) => {
    pendingDraftRef.current = draft
    localStorage.setItem(`${NOTE_DRAFT_STORAGE_PREFIX}${draft.noteId}`, JSON.stringify(draft))
    setSaveState('unsaved')
    setSaveError('')
  }

  const flushPendingDraft = () => {
    clearTimeout(timerRef.current)
    const draft = pendingDraftRef.current
    if (!draft) return saveQueueRef.current
    pendingDraftRef.current = null
    setSaveState('saving')
    saveQueueRef.current = saveQueueRef.current.then(async () => {
      const result = await onSaveRef.current(draft.noteId, { title: draft.title, content: draft.content })
      if (result?.ok) {
        const nextDraft = pendingDraftRef.current
        if (!nextDraft || nextDraft.noteId !== draft.noteId) {
          localStorage.removeItem(`${NOTE_DRAFT_STORAGE_PREFIX}${draft.noteId}`)
          setSaveState(nextDraft ? 'unsaved' : 'saved')
        }
      } else {
        pendingDraftRef.current = pendingDraftRef.current ?? draft
        setSaveState('error')
        setSaveError(typeof result?.error === 'string' ? result.error : 'Could not save this note.')
      }
      return result
    })
    return saveQueueRef.current
  }

  const scheduleSave = (content, nextTitle = titleRef.current) => {
    if (!noteRef.current?.id) return
    persistDraft({ noteId: noteRef.current.id, title: nextTitle, content, savedAt: Date.now() })
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(flushPendingDraft, AUTOSAVE_DELAY_MS)
  }

  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [1, 2, 3] }, link: false }),
      Underline,
      TextStyle,
      FontFamily,
      FontSize,
      Link.configure({ openOnClick: false, autolink: true, defaultProtocol: 'https' }),
      Highlight.configure({ multicolor: true }),
      TextAlign.configure({ types: ['heading', 'paragraph'] }),
      Placeholder.configure({ placeholder: 'Start writing your idea...' }),
    ],
    content: { type: 'doc', content: [{ type: 'paragraph' }] },
    immediatelyRender: false,
    editorProps: { attributes: { class: 'tiptap-note note-writing-canvas focus:outline-none' } },
    onUpdate: ({ editor: currentEditor }) => scheduleSave(currentEditor.getJSON()),
  })

  useEffect(() => {
    const selectedNote = noteRef.current
    if (!selectedNote || !editor || editor.isDestroyed) return
    void flushPendingDraft()
    const nextTitle = selectedNote.title ?? ''
    let nextContent = parseNoteContent(selectedNote.content)
    try {
      const recovered = JSON.parse(localStorage.getItem(`${NOTE_DRAFT_STORAGE_PREFIX}${selectedNote.id}`))
      if (recovered?.noteId === selectedNote.id) {
        nextContent = recovered.content
        titleRef.current = recovered.title
        pendingDraftRef.current = recovered
        setTitle(recovered.title)
        setSaveState('unsaved')
        setSaveError('Recovered an unsaved local draft.')
        editor.commands.setContent(nextContent, false)
        return
      }
    } catch {
      localStorage.removeItem(`${NOTE_DRAFT_STORAGE_PREFIX}${selectedNote.id}`)
    }
    titleRef.current = nextTitle
    editor.commands.setContent(nextContent, false)
    queueMicrotask(() => {
      setTitle(nextTitle)
      setSaveState('saved')
      setSaveError('')
    })
  }, [editor, note?.id])

  useEffect(() => {
    const handlePageHide = () => { void flushPendingDraft() }
    window.addEventListener('pagehide', handlePageHide)
    return () => {
      window.removeEventListener('pagehide', handlePageHide)
      clearTimeout(timerRef.current)
      void flushPendingDraft()
    }
  }, [])

  if (!note) return <NoteEditorWelcome />

  const handleTitleChange = (event) => {
    const value = event.target.value
    setTitle(value)
    titleRef.current = value
    scheduleSave(editor?.getJSON(), value)
  }

  return (
    <section className="note-editor-panel">
      <div className="note-editor-topbar">
        <button onClick={onBack} className="note-mobile-back" aria-label="Back to notes"><NoteIcon name="back" /></button>
        <span className={`save-status ${saveState === 'error' ? 'save-status-error' : ''}`} role="status" aria-live="polite">
          <span className={`save-dot ${saveState === 'saving' || saveState === 'unsaved' ? 'save-dot-working' : ''}`} />
          {saveState === 'saving' ? 'Saving' : saveState === 'unsaved' ? 'Unsaved' : saveState === 'error' ? 'Save failed' : 'Saved'}
        </span>
        {saveState === 'error' && <button onClick={flushPendingDraft} className="save-retry">Retry</button>}
        <input value={title} onChange={handleTitleChange} placeholder="Untitled note" className="note-topbar-title" aria-label="Note title" />
        <div className="ml-auto flex items-center gap-2">
          <button onClick={onDelete} className="editor-icon-button hover:text-red-500" aria-label="Delete note"><NoteIcon name="trash" /></button>
        </div>
      </div>
      <NoteEditorToolbar editor={editor} />
      <div className="workspace-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="note-page">
          <NoteTagEditor note={note} onAddTag={onAddTag} onRemoveTag={onRemoveTag} />
          <div className="workspace-faint mb-5 mt-2 flex items-center gap-2 text-caption">
            <span>Last edited {formatRelativeTime(note.updated_at)}</span>
            <span>•</span>
            <span>{saveState === 'saved' ? 'Autosaved' : 'Local draft protected'}</span>
          </div>
          {saveError && <p className={saveState === 'error' ? 'note-save-error' : 'note-draft-message'}>{saveError}</p>}
          <EditorContent editor={editor} />
        </div>
      </div>
    </section>
  )
}
