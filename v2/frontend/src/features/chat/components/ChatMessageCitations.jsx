import { useNavigate } from 'react-router-dom'
import { FolderIcon, NoteIcon } from './ChatIcons'

export default function ChatMessageCitations({ citations }) {
  const navigate = useNavigate()
  if (!citations?.length) return null

  const openNote = (citation) => navigate(citation.folder_id ? `/folders/${citation.folder_id}?note=${citation.note_id}` : `/notes?note=${citation.note_id}`)

  return (
    <aside className="chat-citations">
      <p className="chat-citations-title">Sources</p>
      <div className="flex flex-wrap gap-1.5">
        {citations.map((citation) => (
          <button key={citation.note_id} type="button" onClick={() => openNote(citation)} className="chat-citation" title={citation.folder ? `${citation.folder} / ${citation.title}` : citation.title}>
            <NoteIcon />
            <span className="max-w-[140px] truncate">{citation.title}</span>
            {citation.folder && <><FolderIcon /><span className="chat-citation-folder">{citation.folder}</span></>}
          </button>
        ))}
      </div>
    </aside>
  )
}
