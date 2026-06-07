import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { authApi } from '@/api/auth'
import { usersApi } from '@/api/users'
import { unwrap } from '@/lib/api'

export const useAuthStore = create(
  devtools(
    (set, get) => ({
      user: null,
      isLoading: false,
      isInitialized: false,

      // Called once on app mount to restore session from cookie.
      // Guard prevents React StrictMode's double-invoke from firing two requests.
      init: async () => {
        const { isInitialized, isLoading } = get()
        if (isInitialized || isLoading) return

        set({ isLoading: true })
        try {
          const { data } = await usersApi.getMe()
          set({ user: unwrap(data), isInitialized: true })
        } catch {
          set({ user: null, isInitialized: true })
        } finally {
          set({ isLoading: false })
        }
      },

      login: async (credentials) => {
        set({ isLoading: true })
        try {
          await authApi.login(credentials)
          const { data } = await usersApi.getMe()
          set({ user: unwrap(data) })
          return { ok: true }
        } catch (err) {
          return { ok: false, error: err.response?.data?.detail ?? 'Login failed' }
        } finally {
          set({ isLoading: false })
        }
      },

      register: async (payload) => {
        set({ isLoading: true })
        try {
          await authApi.register(payload)
          const { data } = await usersApi.getMe()
          set({ user: unwrap(data) })
          return { ok: true }
        } catch (err) {
          return { ok: false, error: err.response?.data?.detail ?? 'Registration failed' }
        } finally {
          set({ isLoading: false })
        }
      },

      logout: async () => {
        try {
          await authApi.logout()
        } finally {
          set({ user: null })
        }
      },

      updateProfile: async (payload) => {
        try {
          const { data } = await usersApi.updateMe(payload)
          set({ user: unwrap(data) })
          return { ok: true }
        } catch (err) {
          return { ok: false, error: err.response?.data?.detail ?? 'Update failed' }
        }
      },

      changePassword: async (payload) => {
        try {
          await authApi.changePassword(payload)
          return { ok: true }
        } catch (err) {
          return { ok: false, error: err.response?.data?.detail ?? 'Failed to change password' }
        }
      },
    }),
    { name: 'auth-store' },
  ),
)
