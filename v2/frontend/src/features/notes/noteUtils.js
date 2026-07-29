export function formatRelativeTime(date) {
  if (!date) return 'Just now'
  const seconds = Math.floor((Date.now() - new Date(date).getTime()) / 1000)
  if (seconds < 60) return 'Just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr`
  if (seconds < 604800) return `${Math.floor(seconds / 86400)} day`
  return new Date(date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function nextFolderName(folders) {
  const names = new Set(folders.map((folder) => folder.name.toLowerCase()))
  let name = 'New folder'
  let suffix = 2
  while (names.has(name.toLowerCase())) {
    name = `New folder ${suffix}`
    suffix += 1
  }
  return name
}
