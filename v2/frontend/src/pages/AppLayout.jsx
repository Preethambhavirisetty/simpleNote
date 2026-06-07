import { Outlet } from 'react-router-dom'
import { useEffect } from 'react'
import Sidebar from '@/components/Sidebar'
import SettingsPanel from '@/components/SettingsPanel'
import { useFolderStore } from '@/stores/folderStore'
import { useTagStore } from '@/stores/tagStore'

export default function AppLayout() {
  const fetchFolders = useFolderStore((s) => s.fetchFolders)
  const fetchTags = useTagStore((s) => s.fetchTags)

  useEffect(() => {
    fetchFolders()
    fetchTags()
  }, [fetchFolders, fetchTags])

  return (
    <div className="flex h-screen bg-white dark:bg-zinc-950 overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-hidden">
        <Outlet />
      </main>
      <SettingsPanel />
    </div>
  )
}
