import { useEffect, useState } from 'react'
import { NavLink, useLocation, useNavigate, useParams } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useChatStore } from '@/stores/chatStore'
import { useFolderStore } from '@/stores/folderStore'
import { useNoteStore } from '@/stores/noteStore'
import { useSettingsStore } from '@/stores/settingsStore'
import { useFeatureFlagStore } from '@/stores/featureFlagStore'
import noteliteIcon from '@/assets/notelite_icon.png'
import ProfileAvatar from '@/components/ProfileAvatar'

const icons = {
  notes: <path strokeLinecap="round" strokeLinejoin="round" d="M8 6h8M8 10h8M8 14h5m5 7H6a2 2 0 01-2-2V5a2 2 0 012-2h12a2 2 0 012 2v14a2 2 0 01-2 2z" />,
  chat: <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.4-4 8-9 8a10 10 0 01-4.3-.9L3 20l1.4-3.7A7 7 0 013 12c0-4.4 4-8 9-8s9 3.6 9 8z" />,
  folder: <path strokeLinecap="round" strokeLinejoin="round" d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />,
  file: <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.6a1 1 0 01.7.3l5.4 5.4a1 1 0 01.3.7V19a2 2 0 01-2 2z" />,
  chevron: <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />,
  plus: <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14m7-7H5" />,
  trash: <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.9 12.1a2 2 0 01-2 1.9H7.9a2 2 0 01-2-1.9L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />,
}

function Icon({ name, className = 'h-[18px] w-[18px]' }) {
  return <svg className={className} fill="none" stroke="currentColor" strokeWidth={1.7} viewBox="0 0 24 24">{icons[name]}</svg>
}

const navCls = ({ isActive }) => `workspace-nav-item ${isActive ? 'workspace-nav-active' : ''}`

export default function Sidebar() {
  const user = useAuthStore((s) => s.user)
  const folders = useFolderStore((s) => (Array.isArray(s.folders) ? s.folders : []))
  const deleteFolder = useFolderStore((s) => s.deleteFolder)
  const notes = useNoteStore((s) => s.notes)
  const fetchNotes = useNoteStore((s) => s.fetchNotes)
  const createNote = useNoteStore((s) => s.createNote)
  const deleteNote = useNoteStore((s) => s.deleteNote)
  const openSettings = useSettingsStore((s) => s.open)
  const isChatEnabled = useFeatureFlagStore((s) => s.isEnabled)('chat')
  const conversations = useChatStore((s) => s.conversations)
  const fetchConversations = useChatStore((s) => s.fetchConversations)
  const deleteConversation = useChatStore((s) => s.deleteConversation)

  const { folderId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [expandedFolders, setExpandedFolders] = useState({})
  const [isCollapsed, setIsCollapsed] = useState(false)

  const isChatPage = location.pathname.startsWith('/chat')
  const activeConversationId = isChatPage ? location.pathname.split('/')[2] : null
  const activeNoteId = new URLSearchParams(location.search).get('note')

  useEffect(() => {
    if (isChatPage) fetchConversations()
    else fetchNotes()
  }, [fetchConversations, fetchNotes, isChatPage])

  const handleNewNote = async (event, folder) => {
    event.stopPropagation()
    const result = await createNote({ folder_id: folder.id })
    if (!result?.ok) return
    setExpandedFolders((current) => ({ ...current, [folder.id]: true }))
    navigate(`/folders/${folder.id}?note=${result.note.id}`)
  }

  const handleDeleteConversation = async (event, id) => {
    event.stopPropagation()
    await deleteConversation(id)
    if (activeConversationId === String(id)) navigate('/chat')
  }

  return (
    <aside className={`workspace-sidebar ${isCollapsed ? 'workspace-sidebar-collapsed' : ''}`}>
      <div className={`flex items-center pb-5 pt-4 ${isCollapsed ? 'flex-col gap-3 px-2' : 'justify-between px-4'}`}>
        <div className="flex items-center gap-2.5">
          <img src={noteliteIcon} alt="" className="h-9 w-9 rounded-xl" />
          {!isCollapsed && <span className="workspace-primary text-[15px] font-semibold tracking-tight">NoteLite</span>}
        </div>
        <button
          onClick={() => setIsCollapsed((value) => !value)}
          className="workspace-icon-button"
          aria-label={isCollapsed ? 'Expand menu' : 'Collapse menu'}
          title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
            <path strokeLinecap="round" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      </div>

      <nav className={`space-y-1 ${isCollapsed ? 'px-2' : 'px-3'}`}>
        <NavLink to="/notes" className={navCls} title="All notes"><Icon name="notes" />{!isCollapsed && 'All notes'}</NavLink>
        {isChatEnabled && <NavLink to="/chat" className={navCls} title="Ask NoteLite"><Icon name="chat" />{!isCollapsed && 'Ask NoteLite'}</NavLink>}
      </nav>

      <div className={`workspace-sidebar-body flex min-h-0 flex-1 flex-col ${isCollapsed ? 'mt-4' : 'mt-6'}`}>
        {isChatPage ? (
          <>
            {!isCollapsed && <SectionHeader label="Recent conversations" />}
            <div className={`workspace-scroll flex-1 overflow-y-auto ${isCollapsed ? 'px-2' : 'px-2'}`}>
              {!isCollapsed && conversations.length === 0 && <p className="workspace-faint px-3 py-3 text-xs">Your conversations will appear here.</p>}
              {conversations.map((conversation) => (
                <button
                  key={conversation.id}
                  onClick={() => navigate(`/chat/${conversation.id}`)}
                  title={conversation.title || 'Untitled conversation'}
                  className={`conversation-row group ${isCollapsed ? 'conversation-row-collapsed' : ''} ${String(conversation.id) === activeConversationId ? 'conversation-row-active' : ''}`}
                >
                  <Icon name="chat" className="h-4 w-4 shrink-0" />
                  {!isCollapsed && (
                    <>
                      <span className="truncate flex-1">{conversation.title || 'Untitled conversation'}</span>
                      <span role="button" tabIndex={0} onClick={(event) => handleDeleteConversation(event, conversation.id)} className="opacity-0 group-hover:opacity-100 hover:text-red-400">
                        <Icon name="trash" className="h-3.5 w-3.5" />
                      </span>
                    </>
                  )}
                </button>
              ))}
            </div>
          </>
        ) : (
          <>
            {!isCollapsed && <SectionHeader label="Workspace" />}
            <div className={`workspace-folder-scroll workspace-scroll min-h-0 flex-1 overflow-y-auto pb-3 ${isCollapsed ? 'px-2' : 'px-3'}`}>
              {folders.map((folder) => {
                const folderNotes = notes.filter((note) => String(note.folder_id) === String(folder.id))
                const isActiveFolder = String(folder.id) === String(folderId)
                const isExpanded = expandedFolders[folder.id] ?? isActiveFolder
                return (
                  <div key={folder.id} className="mb-0.5">
                    <div className={`folder-tree-row group ${isCollapsed ? 'folder-tree-row-collapsed' : ''} ${isActiveFolder ? 'workspace-nav-active' : ''}`}>
                      <button
                        onClick={() => {
                          if (isCollapsed) {
                            navigate(`/folders/${folder.id}`)
                            return
                          }
                          setExpandedFolders((current) => ({ ...current, [folder.id]: !(current[folder.id] ?? isActiveFolder) }))
                          navigate(`/folders/${folder.id}`)
                        }}
                        title={folder.name}
                        className="flex min-w-0 flex-1 items-center gap-2 text-left"
                      >
                        {!isCollapsed && <Icon name="chevron" className={`h-3 w-3 shrink-0 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />}
                        <Icon name="folder" className="h-4 w-4 shrink-0" />
                        {!isCollapsed && <span className="truncate">{folder.name}</span>}
                      </button>
                      {!isCollapsed && <button onClick={(event) => handleNewNote(event, folder)} className="folder-tree-action" title="New note"><Icon name="plus" className="h-3.5 w-3.5" /></button>}
                      {!isCollapsed && <button onClick={() => deleteFolder(folder.id).then(() => String(folder.id) === String(folderId) && navigate('/notes'))} className="folder-tree-action hover:text-red-400" title="Delete folder"><Icon name="trash" className="h-3.5 w-3.5" /></button>}
                    </div>
                    {!isCollapsed && isExpanded && (
                      <div className="folder-note-list workspace-tree-border border-l">
                        {folderNotes.map((note) => (
                          <div key={note.id} className={`folder-note-row group ${String(note.id) === String(activeNoteId) ? 'folder-note-active' : ''}`}>
                            <button onClick={() => navigate(`/folders/${folder.id}?note=${note.id}`)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
                              <Icon name="file" className="h-3.5 w-3.5 shrink-0" />
                              <span className="truncate">{note.title || 'Untitled'}</span>
                            </button>
                            <button
                              onClick={async (event) => {
                                event.stopPropagation()
                                await deleteNote(note.id)
                                if (String(note.id) === String(activeNoteId)) navigate(`/folders/${folder.id}`)
                              }}
                              className="folder-note-delete"
                              title={`Delete ${note.title || 'Untitled'}`}
                            >
                              <Icon name="trash" className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ))}
                        {folderNotes.length === 0 && <p className="workspace-faint px-2 py-1.5 text-[10px]">Empty folder</p>}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </>
        )}
      </div>

      <button
        onClick={openSettings}
        className={`workspace-profile flex items-center rounded-2xl text-left ${isCollapsed ? 'mx-auto mb-3 h-10 w-10 justify-center p-1' : 'm-3 gap-3 p-2.5'}`}
        title="Profile and settings"
      >
        <ProfileAvatar />
        {!isCollapsed && (
          <>
            <span className="min-w-0 flex-1">
              <span className="workspace-primary block truncate text-xs font-medium">{user?.name || 'Your profile'}</span>
              <span className="workspace-faint block truncate text-[10px]">{user?.email}</span>
            </span>
            <span className="workspace-faint">•••</span>
          </>
        )}
      </button>
    </aside>
  )
}

function SectionHeader({ label, action }) {
  return (
    <div className="mb-2 flex items-center justify-between px-5">
      <span className="workspace-faint text-[10px] font-semibold uppercase tracking-[0.16em]">{label}</span>
      {action && <button onClick={action} className="workspace-faint hover:text-[#7aa83a]"><Icon name="plus" className="h-3.5 w-3.5" /></button>}
    </div>
  )
}
