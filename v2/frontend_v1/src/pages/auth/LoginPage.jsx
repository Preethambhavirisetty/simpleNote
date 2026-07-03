import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'

export default function LoginPage() {
  const [form, setForm] = useState({ email: '', password: '' })
  const [error, setError] = useState(null)
  const login = useAuthStore((s) => s.login)
  const isLoading = useAuthStore((s) => s.isLoading)
  const navigate = useNavigate()

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)
    const result = await login(form)
    if (result.ok) {
      navigate('/notes', { replace: true })
    } else {
      setError(result.error)
    }
  }

  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-semibold text-zinc-100 mb-1">Sign in</h1>
        <p className="text-sm text-zinc-500 mb-8">Welcome back to notelite</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <Field label="Email">
            <input
              type="email"
              required
              autoFocus
              value={form.email}
              onChange={set('email')}
              placeholder="you@example.com"
              className={inputCls}
            />
          </Field>

          <Field label="Password">
            <input
              type="password"
              required
              value={form.password}
              onChange={set('password')}
              placeholder="••••••••"
              className={inputCls}
            />
          </Field>

          {error && <ErrorBanner>{error}</ErrorBanner>}

          <button type="submit" disabled={isLoading} className={btnCls}>
            {isLoading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="mt-6 text-sm text-zinc-500 text-center">
          No account?{' '}
          <Link to="/register" className="text-indigo-400 hover:text-indigo-300">
            Register
          </Link>
        </p>
      </div>
    </div>
  )
}

// ---- shared sub-components (auth pages only) ----
function Field({ label, children }) {
  return (
    <div>
      <label className="block text-sm text-zinc-400 mb-1">{label}</label>
      {children}
    </div>
  )
}

function ErrorBanner({ children }) {
  return (
    <p className="text-sm text-red-400 bg-red-950/40 border border-red-900/40 rounded-lg px-3 py-2">
      {children}
    </p>
  )
}

const inputCls =
  'w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-indigo-500 transition-colors'

const btnCls =
  'w-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-60 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors'
