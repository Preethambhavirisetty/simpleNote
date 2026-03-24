import { useEffect } from 'react'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import ProtectedRoute from '@/components/ProtectedRoute'
import AppLayout from '@/pages/AppLayout'
import LoginPage from '@/pages/auth/LoginPage'
import RegisterPage from '@/pages/auth/RegisterPage'
import NotesPage from '@/pages/NotesPage'
import ChatPage from '@/pages/ChatPage'

const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/register', element: <RegisterPage /> },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <AppLayout />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <Navigate to="/notes" replace /> },
      { path: 'notes', element: <NotesPage /> },
      { path: 'folders/:folderId', element: <NotesPage /> },
      { path: 'chat', element: <ChatPage /> },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
])

export default function App() {
  const init = useAuthStore((s) => s.init)

  // Restore session from cookie on first render
  useEffect(() => {
    init()
  }, [init])

  // Listen for 401s emitted by the axios interceptor
  useEffect(() => {
    const handler = () => useAuthStore.setState({ user: null })
    window.addEventListener('auth:unauthorized', handler)
    return () => window.removeEventListener('auth:unauthorized', handler)
  }, [])

  return <RouterProvider router={router} />
}
