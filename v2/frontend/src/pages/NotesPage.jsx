import { useDeferredValue, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import DeleteNoteDialog from '@/features/notes/components/DeleteNoteDialog'
import NoteBrowser from '@/features/notes/components/NoteBrowser'
import NoteEditor from '@/features/notes/components/NoteEditor'
import { NoteEditorLoading } from '@/features/notes/components/NoteEditorStates'
import { nextFolderName } from '@/features/notes/noteUtils'
import { textFromNoteContent } from '@/lib/noteEditor'
import { useFolderStore } from '@/stores/folderStore'
import { useNoteStore } from '@/stores/noteStore'

function filterAndSortNotes(notes, folderId, search) {
  const query = search.trim().toLowerCase()
  return notes
    .filter((note) => !folderId || String(note.folder_id) === String(folderId))
    .filter((note) => !query || `${note.title} ${note.description ?? ''} ${note.content_text ?? textFromNoteContent(note.content)}`.toLowerCase().includes(query))
    .sort((first, second) => Number(Boolean(second.is_pinned)) - Number(Boolean(first.is_pinned)) || new Date(second.updated_at) - new Date(first.updated_at))
}

export default function NotesPage() {
  const { folderId } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const noteId = searchParams.get('note')

  const notes = useNoteStore((state) => state.notes)
  const activeNote = useNoteStore((state) => state.activeNote)
  const isLoading = useNoteStore((state) => state.isLoading)
  const listError = useNoteStore((state) => state.listError)
  const openError = useNoteStore((state) => state.openError)
  const fetchNotes = useNoteStore((state) => state.fetchNotes)
  const openStoredNote = useNoteStore((state) => state.openNote)
  const createStoredNote = useNoteStore((state) => state.createNote)
  const updateNote = useNoteStore((state) => state.updateNote)
  const deleteStoredNote = useNoteStore((state) => state.deleteNote)
  const addTag = useNoteStore((state) => state.addTag)
  const removeTag = useNoteStore((state) => state.removeTag)
  const clearActiveNote = useNoteStore((state) => state.clearActiveNote)
  const folders = useFolderStore((state) => (Array.isArray(state.folders) ? state.folders : []))
  const createFolder = useFolderStore((state) => state.createFolder)
  const [search, setSearch] = useState('')
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [operationError, setOperationError] = useState('')
  const deferredSearch = useDeferredValue(search)
  const currentFolder = folders.find((folder) => String(folder.id) === String(folderId))
  const visibleNotes = useMemo(
    () => filterAndSortNotes(notes, folderId, deferredSearch),
    [deferredSearch, folderId, notes],
  )

  useEffect(() => { fetchNotes({ limit: 200 }) }, [fetchNotes])
  useEffect(() => {
    if (noteId) openStoredNote(noteId)
    else clearActiveNote()
  }, [clearActiveNote, noteId, openStoredNote])

  const notesPath = folderId ? `/folders/${folderId}` : '/notes'
  const openNote = (id) => navigate(`${notesPath}?note=${id}`)

  const createNote = async () => {
    setOperationError('')
    let targetFolderId = folderId ?? folders[0]?.id
    if (!targetFolderId) {
      const folderResult = await createFolder({ name: 'General' })
      targetFolderId = folderResult?.folder?.id
    }
    if (!targetFolderId) {
      setOperationError('Could not create a folder for this note.')
      return
    }
    const result = await createStoredNote({ folder_id: targetFolderId, title: 'Untitled note' })
    if (result?.ok) navigate(`/folders/${targetFolderId}?note=${result.note.id}`)
    else setOperationError(typeof result?.error === 'string' ? result.error : 'Could not create the note.')
  }

  const createNewFolder = async () => {
    setOperationError('')
    const result = await createFolder({ name: nextFolderName(folders) })
    if (result?.ok) navigate(`/folders/${result.folder.id}`)
    else setOperationError(typeof result?.error === 'string' ? result.error : 'Could not create the folder.')
  }

  const deleteNote = async (id) => {
    const result = await deleteStoredNote(id)
    if (result.ok && String(id) === String(noteId)) navigate(notesPath)
    return result
  }

  return (
    <div className="notes-desk h-full">
      <NoteBrowser
        title={currentFolder?.name || 'All notes'}
        notes={visibleNotes}
        activeId={noteId}
        search={search}
        onSearchChange={setSearch}
        isLoading={isLoading}
        error={listError || operationError}
        onRetry={() => fetchNotes()}
        onSelect={openNote}
        onNewNote={createNote}
        onNewFolder={createNewFolder}
        onDelete={(id) => setDeleteTarget(notes.find((note) => note.id === id) ?? { id })}
        onPin={(note) => updateNote(note.id, { is_pinned: !note.is_pinned })}
      />
      {noteId && !activeNote ? (
        <NoteEditorLoading error={openError} onRetry={() => openStoredNote(noteId)} />
      ) : (
        <NoteEditor
          note={activeNote}
          onSave={(id, payload) => updateNote(id, payload)}
          onBack={() => navigate(notesPath)}
          onDelete={() => activeNote && setDeleteTarget(activeNote)}
          onAddTag={addTag}
          onRemoveTag={removeTag}
        />
      )}
      <DeleteNoteDialog
        note={deleteTarget}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={async () => {
          const result = await deleteNote(deleteTarget.id)
          if (result.ok) setDeleteTarget(null)
          return result
        }}
      />
    </div>
  )
}
