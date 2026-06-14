import { useEffect } from 'react'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { useFeatureFlagStore } from '@/stores/featureFlagStore'
import ProtectedRoute from '@/components/ProtectedRoute'
import FeatureGate from '@/components/FeatureGate'
import AppLayout from '@/pages/AppLayout'
import LoginPage from '@/pages/auth/LoginPage'
import RegisterPage from '@/pages/auth/RegisterPage'
import NotesPage from '@/pages/NotesPage'
import ChatPage from '@/pages/ChatPage'
import HomePage from '@/pages/HomePage'

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
      { path: '/notes', element: <NotesPage /> },
      { path: '/folders/:folderId', element: <NotesPage /> },
      { path: '/chat', element: <FeatureGate flag="chat"><ChatPage /></FeatureGate> },
      { path: '/chat/:conversationId', element: <FeatureGate flag="chat"><ChatPage /></FeatureGate> },
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
