import { useEffect, useRef } from 'react'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { useFeatureFlagStore } from '@/stores/featureFlagStore'
import { resetUserState } from '@/stores/resetUserState'
import ProtectedRoute from '@/components/ProtectedRoute'
import FeatureGate from '@/components/FeatureGate'
import RouteErrorPage from '@/components/RouteErrorPage'
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
    errorElement: <RouteErrorPage />,
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
  const initializationStarted = useRef(false)
  const init = useAuthStore((s) => s.init)
  const initTheme = useThemeStore((s) => s.init)
  const fetchFlags = useFeatureFlagStore((s) => s.fetchFlags)

  useEffect(() => {
    if (initializationStarted.current) return
    initializationStarted.current = true
    initTheme()
    const initialize = async () => {
      await init()
      await fetchFlags()
    }
    void initialize()
  }, [init, initTheme, fetchFlags])

  // Listen for 401s emitted by the axios interceptor
  useEffect(() => {
    const handler = () => {
      resetUserState()
      useAuthStore.setState({ user: null })
    }
    window.addEventListener('auth:unauthorized', handler)
    return () => window.removeEventListener('auth:unauthorized', handler)
  }, [])

  return <RouterProvider router={router} />
}
