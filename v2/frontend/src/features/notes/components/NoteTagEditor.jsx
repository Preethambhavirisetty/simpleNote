import { useEffect, useMemo, useState } from 'react'
import { useTagStore } from '@/stores/tagStore'

export default function NoteTagEditor({ note, onAddTag, onRemoveTag }) {
  const tags = useTagStore((state) => state.tags)
  const fetchTags = useTagStore((state) => state.fetchTags)
  const createTag = useTagStore((state) => state.createTag)
  const [isOpen, setIsOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')

  const availableTags = useMemo(() => {
    const attachedIds = new Set((note.tags ?? []).map((tag) => tag.id))
    const normalizedQuery = query.trim().toLowerCase()
    return tags.filter((tag) => !attachedIds.has(tag.id) && tag.name.toLowerCase().includes(normalizedQuery))
  }, [note.tags, query, tags])

  useEffect(() => {
    if (isOpen) void fetchTags()
  }, [fetchTags, isOpen])

  const addTag = async (tag) => {
    const result = await onAddTag(note.id, tag)
    if (!result.ok) {
      setError(typeof result.error === 'string' ? result.error : 'Could not add tag.')
      return
    }
    setError('')
    setQuery('')
  }

  const createAndAddTag = async () => {
    const name = query.trim()
    if (!name) return
    const result = await createTag(name)
    if (!result.ok) {
      setError(typeof result.error === 'string' ? result.error : 'Could not create tag.')
      return
    }
    await addTag(result.tag)
  }

  return (
    <div className="note-tags-editor">
      <div className="flex flex-wrap items-center gap-2">
        {(note.tags ?? []).map((tag) => (
          <span key={tag.id} className="note-tag note-tag-removable">
            #{tag.name}
            <button
              onClick={async () => {
                const result = await onRemoveTag(note.id, tag.id)
                if (!result.ok) setError(typeof result.error === 'string' ? result.error : 'Could not remove tag.')
              }}
              aria-label={`Remove ${tag.name} tag`}
            >
              ×
            </button>
          </span>
        ))}
        <button onClick={() => setIsOpen((value) => !value)} className="note-add-tag" aria-expanded={isOpen}>+ Add tag</button>
      </div>
      {isOpen && (
        <div className="note-tag-picker">
          <input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find or create a tag" aria-label="Find or create a tag" />
          <div className="workspace-scroll max-h-32 overflow-y-auto">
            {availableTags.map((tag) => <button key={tag.id} onClick={() => addTag(tag)}>#{tag.name}</button>)}
            {query.trim() && !tags.some((tag) => tag.name.toLowerCase() === query.trim().toLowerCase()) && (
              <button onClick={createAndAddTag}>Create “{query.trim()}”</button>
            )}
            {!query.trim() && availableTags.length === 0 && <p>No tags available.</p>}
          </div>
          {error && <p className="note-save-error">{error}</p>}
        </div>
      )}
    </div>
  )
}
