import { useNavigate } from 'react-router-dom'
import { FolderIcon, NoteIcon } from './ChatIcons'

export default function ChatMessageReferences({ references }) {
  const navigate = useNavigate()
  if (!references?.length) return null

  const openNote = (reference) => navigate(reference.folder_id ? `/folders/${reference.folder_id}?note=${reference.note_id}` : `/notes?note=${reference.note_id}`)

  return (
    <aside className="chat-references">
      <p className="chat-references-title">References</p>
      <div className="flex flex-wrap gap-1.5">
        {references.map((reference) => (
          <button key={reference.note_id} type="button" onClick={() => openNote(reference)} className="chat-reference" title={reference.folder ? `${reference.folder} / ${reference.title}` : reference.title}>
            <NoteIcon />
            <span className="max-w-[140px] truncate">{reference.title}</span>
            {reference.folder && <><FolderIcon /><span className="chat-reference-folder">{reference.folder}</span></>}
          </button>
        ))}
      </div>
    </aside>
  )
}
