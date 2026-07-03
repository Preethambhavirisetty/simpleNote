import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { useSettingsStore } from '@/stores/settingsStore'
import { useAvatarStore } from '@/stores/avatarStore'
import ProfileAvatar from '@/components/ProfileAvatar'
import { CHARACTER_OPTIONS } from '@/lib/avatarOptions'

// ---------- Section wrapper ----------
function Section({ title, children }) {
  return (
    <div className="settings-section">
      {title && (
        <p className="mb-3 font-semibold tracking-wider uppercase text-label text-zinc-400 dark:text-zinc-500">
          {title}
        </p>
      )}
      {children}
    </div>
  )
}

// ---------- Coming-soon row ----------
function ComingSoon({ label }) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-xs text-zinc-400 dark:text-zinc-500">{label}</span>
      <span className="text-caption font-medium text-zinc-400 dark:text-zinc-600 bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5 rounded-full">
        Coming soon
      </span>
    </div>
  )
}

// ---------- Theme toggle ----------
function ThemeToggle() {
  const theme = useThemeStore((s) => s.theme)
  const setTheme = useThemeStore((s) => s.setTheme)

  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-sm text-zinc-700 dark:text-zinc-300">Theme</span>
      <div className="flex bg-zinc-100 dark:bg-zinc-800 rounded-lg p-0.5 gap-0.5">
        {[
          { value: 'light', icon: '☀️', label: 'Light' },
          { value: 'dark', icon: '🌙', label: 'Dark' },
        ].map(({ value, icon, label }) => (
          <button
            key={value}
            onClick={() => setTheme(value)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              theme === value
                ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-zinc-100 shadow-sm'
                : 'text-zinc-500 dark:text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200'
            }`}
          >
            <span>{icon}</span>
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}

function AvatarChooser() {
  const avatar = useAvatarStore((s) => s.avatar)
  const setCharacter = useAvatarStore((s) => s.setCharacter)
  const setImage = useAvatarStore((s) => s.setImage)
  const inputRef = useRef(null)
  const [error, setError] = useState('')

  const handleImage = (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    if (!file.type.startsWith('image/')) {
      setError('Choose an image file.')
      return
    }
    if (file.size > 2 * 1024 * 1024) {
      setError('Image must be smaller than 2 MB.')
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      setImage(reader.result)
      setError('')
    }
    reader.readAsDataURL(file)
  }

  return (
    <div>
      <div className="flex items-center gap-3">
        <ProfileAvatar size="lg" />
        <div>
          <p className="text-sm font-medium text-zinc-800 dark:text-zinc-200">Choose your character</p>
          <p className="mt-0.5 text-xs text-zinc-500">Synced across your workspace.</p>
        </div>
      </div>
      <div className="grid grid-cols-6 gap-2 mt-4">
        {CHARACTER_OPTIONS.map((value) => (
          <button
            key={value}
            onClick={() => setCharacter(value)}
            className={`avatar-choice ${avatar.type === 'character' && avatar.value === value ? 'avatar-choice-active' : ''}`}
            title={`Character ${value + 1}`}
          >
            <ProfileAvatar size="sm" previewValue={{ type: 'character', value }} />
          </button>
        ))}
      </div>
      <input ref={inputRef} onChange={handleImage} type="file" accept="image/*" className="hidden" />
      <button onClick={() => inputRef.current?.click()} className="w-full px-3 py-2 mt-3 text-xs font-medium border rounded-lg border-zinc-200 text-zinc-600 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800">
        Upload your own image
      </button>
      {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
    </div>
  )
}

// ---------- Change password mini-form ----------
function ChangePasswordForm({ onDone }) {
  const changePassword = useAuthStore((s) => s.changePassword)
  const [form, setForm] = useState({ current_password: '', new_password: '', confirm: '' })
  const [status, setStatus] = useState(null) // null | 'loading' | 'ok' | string(error)

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (form.new_password !== form.confirm) {
      setStatus('Passwords do not match')
      return
    }
    setStatus('loading')
    const result = await changePassword({
      current_password: form.current_password,
      new_password: form.new_password,
    })
    if (result.ok) {
      setStatus('ok')
      setTimeout(onDone, 1200)
    } else {
      setStatus(result.error ?? 'Failed')
    }
  }

  if (status === 'ok') {
    return <p className="py-2 text-sm text-emerald-500">Password changed ✓</p>
  }

  return (
    <form onSubmit={handleSubmit} className="mt-2 space-y-2">
      {[
        { key: 'current_password', placeholder: 'Current password' },
        { key: 'new_password', placeholder: 'New password' },
        { key: 'confirm', placeholder: 'Confirm new password' },
      ].map(({ key, placeholder }) => (
        <input
          key={key}
          type="password"
          required
          placeholder={placeholder}
          value={form[key]}
          onChange={set(key)}
          className="w-full px-3 py-2 text-sm transition-colors border rounded-lg bg-zinc-100 dark:bg-zinc-800 border-zinc-200 dark:border-zinc-700 text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 dark:placeholder-zinc-600 focus:outline-none focus:border-indigo-500"
        />
      ))}
      {status && status !== 'loading' && (
        <p className="text-xs text-red-400">{status}</p>
      )}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={status === 'loading'}
          className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-60 text-white rounded-lg py-1.5 text-xs font-medium transition-colors"
        >
          {status === 'loading' ? 'Saving…' : 'Update password'}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="px-3 py-1.5 text-xs text-zinc-500 dark:text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition-colors"
        >
          Cancel
        </button>
      </div>
    </form>
  )
}

// ---------- Main panel ----------
export default function SettingsPanel() {
  const isOpen = useSettingsStore((s) => s.isOpen)
  const close = useSettingsStore((s) => s.close)
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const navigate = useNavigate()
  const panelRef = useRef(null)
  const [showChangePassword, setShowChangePassword] = useState(false)

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return
    const handler = (e) => e.key === 'Escape' && close()
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [isOpen, close])

  // Close on backdrop click
  const handleBackdropClick = (e) => {
    if (panelRef.current && !panelRef.current.contains(e.target)) close()
  }

  const handleLogout = async () => {
    close()
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={handleBackdropClick}
        className={`fixed inset-0 z-40 bg-black/20 dark:bg-black/40 backdrop-blur-[2px] transition-opacity duration-200 ${
          isOpen ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
        }`}
      />

      {/* Panel */}
      <div
        ref={panelRef}
        className={`settings-panel fixed top-0 right-0 bottom-0 z-50 w-80 bg-white dark:bg-zinc-900 border-l border-zinc-200 dark:border-zinc-800 shadow-2xl flex flex-col transition-transform duration-200 ease-out ${
          isOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 settings-panel-header">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Settings</h2>
          <button
            onClick={close}
            className="flex items-center justify-center transition-colors rounded-md w-7 h-7 text-zinc-400 dark:text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {/* Profile */}
          <Section>
            <div className="flex items-center gap-3">
              <ProfileAvatar size="lg" />
              <div className="min-w-0">
                <p className="text-sm font-medium truncate text-zinc-900 dark:text-zinc-100">
                  {user?.name ?? 'Anonymous'}
                </p>
                <p className="text-xs truncate text-zinc-500 dark:text-zinc-500">{user?.email}</p>
              </div>
            </div>
          </Section>

          <Section title="Profile picture">
            <AvatarChooser />
          </Section>

          {/* Appearance */}
          <Section title="Appearance">
            <ThemeToggle />
          </Section>

          {/* Account */}
          <Section title="Account">
            {showChangePassword ? (
              <ChangePasswordForm onDone={() => setShowChangePassword(false)} />
            ) : (
              <button
                onClick={() => setShowChangePassword(true)}
                className="flex items-center justify-between w-full py-2 text-sm text-zinc-700 dark:text-zinc-300 hover:text-zinc-900 dark:hover:text-zinc-100 group"
              >
                Change password
                <svg className="w-4 h-4 transition-colors text-zinc-400 dark:text-zinc-600 group-hover:text-zinc-600 dark:group-hover:text-zinc-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
              </button>
            )}
          </Section>

          {/* Placeholders — will grow with Memory Management, Trash, etc. */}
          <Section title="Notes">
            <ComingSoon label="Memory management" />
            <ComingSoon label="Deleted notes" />
          </Section>
        </div>

        {/* Footer */}
        <div className="px-5 py-4 settings-panel-footer">
          <button
            onClick={handleLogout}
            className="flex items-center w-full gap-2 px-3 py-2 text-sm text-red-500 transition-colors rounded-lg dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            Sign out
          </button>
        </div>
      </div>
    </>
  )
}
