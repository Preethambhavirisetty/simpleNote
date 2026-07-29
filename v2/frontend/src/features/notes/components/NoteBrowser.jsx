import { textFromNoteContent } from '@/lib/noteEditor'
import { formatRelativeTime } from '../noteUtils'
import NoteIcon from './NoteIcon'

function NoteCard({ note, index, active, onSelect, onDelete, onPin }) {
  const preview = note.description || note.content_text || textFromNoteContent(note.content) || 'Start writing to bring this note to life.'

  return (
    <article
      onClick={() => onSelect(note.id)}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onSelect(note.id)
        }
      }}
      role="button"
      tabIndex={0}
      aria-current={active ? 'true' : undefined}
      aria-label={`Open ${note.title || 'Untitled note'}`}
      className={`note-card group ${active ? 'note-card-active' : ''}`}
      style={{ animationDelay: `${Math.min(index, 8) * 35}ms` }}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <span className="text-sm font-semibold leading-7">{note.title || 'Untitled note'}</span>
          <p className="workspace-muted mt-1.5 line-clamp-2 text-xs leading-5">{preview}</p>
        </div>
        <span className={`note-card-dot ${note.is_pinned ? 'note-card-dot-pinned' : ''}`} />
      </div>
      {note.tags?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {note.tags.slice(0, 3).map((tag) => <span key={tag.id} className="note-tag">#{tag.name}</span>)}
        </div>
      )}
      <div className="mt-4 flex items-center justify-between">
        <span className="workspace-faint text-sm">{formatRelativeTime(note.updated_at ?? note.created_at)}</span>
        <div className="note-card-actions">
          <button onClick={(event) => { event.stopPropagation(); onPin(note) }} className={note.is_pinned ? 'text-[var(--accent)]' : ''} aria-label={note.is_pinned ? 'Unpin note' : 'Pin note'}><NoteIcon name="pin" className="h-3.5 w-3.5" /></button>
          <button onClick={(event) => { event.stopPropagation(); onDelete(note.id) }} className="hover:text-red-500" aria-label={`Delete ${note.title || 'Untitled note'}`}><NoteIcon name="trash" className="h-3.5 w-3.5" /></button>
        </div>
      </div>
    </article>
  )
}

export default function NoteBrowser({ title, notes, activeId, search, onSearchChange, isLoading, error, onRetry, onSelect, onNewNote, onNewFolder, onDelete, onPin }) {
  return (
    <section className={`notes-browser ${activeId ? 'notes-browser-has-selection' : ''}`}>
      <div className="notes-browser-header">
        <div>
          <p className="workspace-faint text-caption font-semibold uppercase tracking-[0.16em]">Workspace</p>
          <h1 className="workspace-primary mt-1 text-sm font-semibold tracking-[-0.04em]">{title}</h1>
        </div>
        <button onClick={onNewFolder} className="note-new-button" title="Create folder" aria-label="Create folder"><NoteIcon name="plus" /></button>
      </div>
      <label className="notes-search">
        <NoteIcon name="search" className="h-4 w-4 shrink-0" />
        <input value={search} onChange={(event) => onSearchChange(event.target.value)} placeholder="Search notes..." />
        {search && <button onClick={() => onSearchChange('')} className="workspace-faint text-xs">Clear</button>}
      </label>
      <div className="workspace-scroll min-h-0 flex-1 overflow-y-auto px-4 pb-5">
        {error && <div className="notes-error" role="alert"><span>{error}</span><button onClick={onRetry}>Retry</button></div>}
        {isLoading && notes.length === 0 && <div className="flex justify-center py-12"><span className="note-spinner" /></div>}
        {!isLoading && notes.length === 0 && (
          <button onClick={onNewNote} className="notes-empty-card">
            <span className="notes-empty-icon"><NoteIcon name="note" className="h-5 w-5" /></span>
            <span className="workspace-secondary text-sm font-medium">Start a fresh note</span>
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
