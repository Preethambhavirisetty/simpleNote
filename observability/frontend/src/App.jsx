import { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'

import RunsPage from './pages/RunsPage'
import RunDetailPage from './pages/RunDetailPage'
import ConversationPage from './pages/ConversationPage'
import StatsPage from './pages/StatsPage'


function ThemeToggle() {
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') ?? 'system')

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])

  const next = { system: 'light', light: 'dark', dark: 'system' }
  const icon = { system: '◐', light: '☀', dark: '☾' }

  return (
    <button
      className="btn sm"
      onClick={() => setTheme(next[theme])}
      title={`Theme: ${theme} — click for ${next[theme]}`}
    >
      <span aria-hidden="true">{icon[theme]}</span> {theme}
    </button>
  )
}

export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <h1>Agent Log Tracker</h1>
        <nav>
          <NavLink to="/" end>Runs</NavLink>
          <NavLink to="/stats">Stats</NavLink>
        </nav>
        <span className="spacer" />
        <ThemeToggle />
      </header>

      <Routes>
        <Route path="/" element={<RunsPage />} />
        <Route path="/runs/:runKey" element={<RunDetailPage />} />
        <Route path="/conversations/:conversationId" element={<ConversationPage />} />
        <Route path="/stats" element={<StatsPage />} />
      </Routes>
    </div>
  )
}
