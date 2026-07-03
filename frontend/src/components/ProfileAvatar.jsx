import { useAvatarStore } from '@/stores/avatarStore'

const palettes = [
  { bg: '#dff7c4', skin: '#9c6247', hair: '#2a201c', shirt: '#ff9f68' },
  { bg: '#d9edff', skin: '#f0b58d', hair: '#49352d', shirt: '#6d8dff' },
  { bg: '#ffe4b8', skin: '#c77b55', hair: '#211a18', shirt: '#55b89b' },
  { bg: '#eadfff', skin: '#8e5944', hair: '#34241f', shirt: '#b274df' },
  { bg: '#ffdce8', skin: '#e4a47d', hair: '#6a4533', shirt: '#e66f83' },
  { bg: '#d8f1ed', skin: '#6e4436', hair: '#171311', shirt: '#f0bb48' },
]

export default function ProfileAvatar({ size = 'md', previewValue }) {
  const selected = useAvatarStore((s) => s.avatar)
  const avatar = previewValue ?? selected
  const sizeClass = size === 'lg' ? 'character-avatar-lg' : size === 'sm' ? 'character-avatar-sm' : ''

  if (avatar.type === 'image') {
    return (
      <span className={`character-avatar ${sizeClass}`}>
        <img src={avatar.value} alt="Profile" />
      </span>
    )
  }

  const value = Number(avatar.value) || 0
  const palette = palettes[value % palettes.length]
  const hasGlasses = value % 2 === 0
  const hairStyle = value % 3

  return (
    <span className={`character-avatar ${sizeClass}`} style={{ background: palette.bg }} aria-hidden="true">
      <svg viewBox="0 0 48 48">
        <path d="M9 48c1.2-10.2 6.6-15.3 15-15.3S37.8 37.8 39 48" fill={palette.shirt} />
        <ellipse cx="24" cy="23" rx="11.2" ry="13" fill={palette.skin} />
        {hairStyle === 0 && <path d="M12.8 22.5c-.8-9.8 4.6-15 11.5-15 7.2 0 11.4 5 10.8 12.6-3.5-1.6-5.1-5.2-5.1-5.2-3.3 4.2-8.5 5.5-17.2 7.6Z" fill={palette.hair} />}
        {hairStyle === 1 && <path d="M12.6 22.2C11.9 12.8 17 7.4 24.3 7.4c7.5 0 11.8 5.7 10.8 14.4-2.1-4.5-5.4-6.7-10.1-6.7-4.9 0-9 2.4-12.4 7.1Z" fill={palette.hair} />}
        {hairStyle === 2 && <path d="M12.6 23.2c-1-10.3 3.5-15.7 11.8-15.7 7.8 0 11.5 5.7 10.7 14.6l-3.4-6.6-3.3 2.3-3.5-3.2-4 3-3.8-2.2-4.5 7.8Z" fill={palette.hair} />}
        <circle cx="19.6" cy="23.2" r="1.1" fill="#201b19" />
        <circle cx="28.4" cy="23.2" r="1.1" fill="#201b19" />
        {hasGlasses && <path d="M15.6 21.6h7.2v4.3h-7.2zm9.6 0h7.2v4.3h-7.2m-2.4-2.1h2.4" fill="none" stroke="#3f4545" strokeWidth="1" />}
        <path d="M20.5 28.8c2.2 1.7 4.8 1.7 7 0" fill="none" stroke="#6e4037" strokeLinecap="round" strokeWidth="1.2" />
      </svg>
    </span>
  )
}
