import axios from 'axios'

// In dev the Vite proxy rewrites /api/* → localhost:3001/api/* so baseURL stays relative.
// In prod set VITE_BE_URL to your backend origin (e.g. https://api.yourapp.com).
const client = axios.create({
  baseURL: import.meta.env.VITE_BE_URL ?? '',
  withCredentials: true, // session cookie
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
