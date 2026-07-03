import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import noteliteIcon from '@/assets/notelite_icon.png'
import { useAuthStore } from '@/stores/authStore'

export default function LoginPage() {
  const [form, setForm] = useState({ email: '', password: '' })
  const [error, setError] = useState(null)
  const [showPassword, setShowPassword] = useState(false)
  const login = useAuthStore((s) => s.login)
  const isLoading = useAuthStore((s) => s.isLoading)
  const navigate = useNavigate()

  const set = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }))

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError(null)
    const result = await login(form)
    if (result.ok) {
      navigate('/notes', { replace: true })
    } else {
      setError(result.error)
    }
  }

  return (
    <main className="auth-page">
      <div className="auth-glow auth-glow-top" />
      <div className="auth-glow auth-glow-bottom" />

      <header className="auth-header">
        <Link to="/" className="auth-brand" aria-label="NoteLite home">
          <img src={noteliteIcon} alt="" />
          <span>NoteLite</span>
        </Link>

        <Link to="/" className="auth-home-link">
          Back to home
          <ArrowUpRightIcon />
        </Link>
      </header>

      <section className="auth-stage">
        <NoteIllustration />

        <div className="auth-card-wrap">
          <div className="auth-card-accent" />
          <div className="auth-card">
            <div className="auth-card-heading">
              <span className="auth-eyebrow">
                <span />
                Your workspace is ready
              </span>
              <h1>Welcome back.</h1>
              <p>Sign in to keep thinking, writing, and connecting your ideas.</p>
            </div>

            <form onSubmit={handleSubmit} className="auth-form">
              <label className="auth-field">
                <span className="sr-only">Email address</span>
                <MailIcon />
                <input
                  type="email"
                  required
                  autoFocus
                  autoComplete="email"
                  value={form.email}
                  onChange={set('email')}
                  placeholder="Email address"
                />
              </label>

              <label className="auth-field">
                <span className="sr-only">Password</span>
                <LockIcon />
                <input
                  type={showPassword ? 'text' : 'password'}
                  required
                  autoComplete="current-password"
                  value={form.password}
                  onChange={set('password')}
                  placeholder="Password"
                />
                <button
                  type="button"
                  className="auth-password-toggle"
                  onClick={() => setShowPassword((visible) => !visible)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOffIcon /> : <EyeIcon />}
                </button>
              </label>

              {error && (
                <p className="auth-error" role="alert">
                  {error}
                </p>
              )}

              <button type="submit" disabled={isLoading} className="auth-submit">
                <span>{isLoading ? 'Opening workspace...' : 'Open your workspace'}</span>
                {!isLoading && <ArrowRightIcon />}
              </button>
            </form>

            <p className="auth-register">
              New to NoteLite? <Link to="/register">Create an account</Link>
            </p>
          </div>
        </div>

        <IdeasIllustration />
      </section>

      <footer className="auth-footer">
        <span>Private by design</span>
        <span className="auth-footer-dot" />
        <span>Built for focused thinking</span>
      </footer>
    </main>
  )
}

function NoteIllustration() {
  return (
    <div className="auth-illustration auth-notes" aria-hidden="true">
      <div className="auth-mini-note auth-mini-note-back">
        <span />
        <span />
        <span />
      </div>
      <div className="auth-mini-note auth-mini-note-front">
        <div className="auth-note-header">
          <span />
          <i />
        </div>
        <strong>Ideas worth keeping</strong>
        <span />
        <span />
        <span className="short" />
      </div>
      <div className="auth-pencil" />
    </div>
  )
}

function IdeasIllustration() {
  return (
    <div className="auth-illustration auth-ideas" aria-hidden="true">
      <div className="auth-idea-orbit orbit-one" />
      <div className="auth-idea-orbit orbit-two" />
      <div className="auth-idea-core">✦</div>
      <span className="auth-spark spark-one">✦</span>
      <span className="auth-spark spark-two">+</span>
      <span className="auth-spark spark-three">✦</span>
      <div className="auth-idea-base">
        <span />
        <span />
        <span />
      </div>
    </div>
  )
}

function MailIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6.75h16v10.5H4zM4.5 7.5l7.5 6 7.5-6" /></svg>
}

function LockIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="10" rx="3" /><path d="M8.5 10V7.5a3.5 3.5 0 0 1 7 0V10M12 14v2.5" /></svg>
}

function EyeIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12s3.25-5 9-5 9 5 9 5-3.25 5-9 5-9-5-9-5Z" /><circle cx="12" cy="12" r="2.25" /></svg>
}

function EyeOffIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 4 16 16M10.4 7.15A8.8 8.8 0 0 1 12 7c5.75 0 9 5 9 5a13.7 13.7 0 0 1-2.2 2.65M14.1 16.75A8.8 8.8 0 0 1 12 17c-5.75 0-9-5-9-5a13.8 13.8 0 0 1 2.35-2.8" /></svg>
}

function ArrowRightIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5" /></svg>
}

function ArrowUpRightIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17 17 7M8 7h9v9" /></svg>
}
