import { lazy, Suspense, useEffect } from 'react'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { useFeatureFlagStore } from '@/stores/featureFlagStore'
import ProtectedRoute from '@/components/ProtectedRoute'
import FeatureGate from '@/components/FeatureGate'
import AppLayout from '@/pages/AppLayout'
import LoginPage from '@/pages/auth/LoginPage'
import RegisterPage from '@/pages/auth/RegisterPage'
import HomePage from '@/pages/HomePage'

const NotesPage = lazy(() => import('@/pages/NotesPage'))
const ChatPage = lazy(() => import('@/pages/ChatPage'))

function RouteLoader({ children }) {
  return <Suspense fallback={<div className="route-loader" role="status"><span className="note-spinner" /><span>Loading workspace…</span></div>}>{children}</Suspense>
}

const router = createBrowserRouter([
  { path: '/', element: <HomePage /> },
  { path: '/login', element: <LoginPage /> },
  { path: '/register', element: <RegisterPage /> },
  {
    element: (
      <ProtectedRoute>
        <AppLayout />
      </ProtectedRoute>
    ),
    children: [
      { path: '/notes', element: <RouteLoader><NotesPage /></RouteLoader> },
      { path: '/folders/:folderId', element: <RouteLoader><NotesPage /></RouteLoader> },
      { path: '/chat', element: <FeatureGate flag="chat"><RouteLoader><ChatPage /></RouteLoader></FeatureGate> },
      { path: '/chat/:conversationId', element: <FeatureGate flag="chat"><RouteLoader><ChatPage /></RouteLoader></FeatureGate> },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
])

export default function App() {
  const init = useAuthStore((s) => s.init)
  const initTheme = useThemeStore((s) => s.init)
  const fetchFlags = useFeatureFlagStore((s) => s.fetchFlags)

  useEffect(() => {
    initTheme()
    init()
    fetchFlags()
  }, [init, initTheme, fetchFlags])

  // Listen for 401s emitted by the axios interceptor
  useEffect(() => {
    const handler = () => useAuthStore.setState({ user: null })
    window.addEventListener('auth:unauthorized', handler)
    return () => window.removeEventListener('auth:unauthorized', handler)
  }, [])

  return <RouterProvider router={router} />
}
