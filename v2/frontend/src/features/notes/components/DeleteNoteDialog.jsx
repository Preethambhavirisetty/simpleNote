import { useEffect, useRef, useState } from 'react'

export default function DeleteNoteDialog({ note, onCancel, onConfirm }) {
  const [isDeleting, setIsDeleting] = useState(false)
  const [error, setError] = useState('')
  const cancelRef = useRef(null)

  useEffect(() => {
    if (!note) return
    const handleKeyDown = (event) => event.key === 'Escape' && onCancel()
    document.addEventListener('keydown', handleKeyDown)
    queueMicrotask(() => cancelRef.current?.focus())
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [note, onCancel])

  if (!note) return null

  const confirm = async () => {
    setIsDeleting(true)
    setError('')
    const result = await onConfirm()
    if (!result.ok) {
      setError(typeof result.error === 'string' ? result.error : 'Could not delete the note.')
      setIsDeleting(false)
    }
  }

  return (
    <div className="note-dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onCancel()}>
      <div className="note-dialog" role="alertdialog" aria-modal="true" aria-labelledby="delete-note-title" aria-describedby="delete-note-description">
        <h2 id="delete-note-title">Delete this note?</h2>
        <p id="delete-note-description">“{note.title || 'Untitled note'}” will be permanently deleted. This cannot be undone.</p>
        {error && <p className="note-save-error">{error}</p>}
        <div className="note-dialog-actions">
          <button ref={cancelRef} onClick={onCancel} disabled={isDeleting}>Cancel</button>
          <button onClick={confirm} disabled={isDeleting} className="note-dialog-delete">{isDeleting ? 'Deleting…' : 'Delete note'}</button>
        </div>
      </div>
    </div>
  )
}
