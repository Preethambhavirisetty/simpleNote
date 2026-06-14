import axios from 'axios'
import { useAuthStore } from '@/stores/authStore'

// In dev the Vite proxy rewrites /api/* → localhost:3001/api/* so baseURL stays relative.
// Keep support for the older VITE_BE_URL name while using the documented env variable.
const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_BE_URL ?? '',
  withCredentials: true, // session cookie
})

client.interceptors.request.use((config) => {
  const user = useAuthStore.getState().user
  if (user?.id) {
    config.headers['X-User-Id'] = user.id
  }
  return config
})

// Broadcast 401 so the auth store can react without circular imports
client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      window.dispatchEvent(new CustomEvent('auth:unauthorized'))
    }
    return Promise.reject(err)
  },
)

export default client
