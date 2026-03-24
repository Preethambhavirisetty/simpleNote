import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useFolderStore } from '@/stores/folderStore'

const navCls = ({ isActive }) =>
  `flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
    isActive
      ? 'bg-indigo-600/20 text-indigo-300'
      : 'text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800'
  }`

export default function Sidebar() {
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const folders = useFolderStore((s) => (Array.isArray(s.folders) ? s.folders : []))
  const createFolder = useFolderStore((s) => s.createFolder)
  const navigate = useNavigate()

  const [newFolderName, setNewFolderName] = useState('')
  const [showNewFolder, setShowNewFolder] = useState(false)

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  const handleCreateFolder = async (e) => {
    e.preventDefault()
    const name = newFolderName.trim()
    if (!name) return
    await createFolder({ name })
    setNewFolderName('')
    setShowNewFolder(false)
  }

  const initials = user?.name?.[0]?.toUpperCase() ?? user?.email?.[0]?.toUpperCase() ?? '?'

  return (
    <aside className="w-56 flex flex-col bg-zinc-900 border-r border-zinc-800 h-full select-none shrink-0">
      {/* Brand */}
      <div className="px-4 py-4 border-b border-zinc-800">
        <span className="text-zinc-100 font-semibold tracking-tight">notelite</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-0.5">
        <NavLink to="/notes" className={navCls} end>
          <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          All Notes
        </NavLink>

        <NavLink to="/chat" className={navCls}>
          <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
          </svg>
          Chat
        </NavLink>

        {/* Folders */}
        <div className="pt-3">
          <div className="flex items-center justify-between px-3 py-1 mb-0.5">
            <span className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">Folders</span>
            <button
              onClick={() => setShowNewFolder((v) => !v)}
              className="text-zinc-500 hover:text-zinc-200 w-5 h-5 flex items-center justify-center rounded transition-colors"
              title="New folder"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
            </button>
          </div>

          {showNewFolder && (
            <form onSubmit={handleCreateFolder} className="px-2 mb-1">
              <input
                autoFocus
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                onKeyDown={(e) => e.key === 'Escape' && setShowNewFolder(false)}
                placeholder="Folder name"
                className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-indigo-500"
              />
            </form>
          )}

          {folders.map((folder) => (
            <NavLink key={folder.id} to={`/folders/${folder.id}`} className={navCls}>
              <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
              </svg>
              <span className="truncate">{folder.name}</span>
              {folder.is_pinned && (
                <span className="ml-auto text-[10px] text-indigo-400">●</span>
              )}
            </NavLink>
          ))}
        </div>
      </nav>

      {/* User */}
      <div className="px-2 py-3 border-t border-zinc-800">
        <div className="flex items-center gap-2 px-2 py-1 mb-1">
          <div className="w-6 h-6 rounded-full bg-indigo-700 flex items-center justify-center text-[11px] text-white font-semibold shrink-0">
            {initials}
          </div>
          <span className="text-xs text-zinc-400 truncate">{user?.name ?? user?.email}</span>
        </div>
        <button
          onClick={handleLogout}
          className="w-full text-left px-3 py-1.5 text-xs text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 rounded-lg transition-colors"
        >
          Sign out
        </button>
      </div>
    </aside>
  )
}
