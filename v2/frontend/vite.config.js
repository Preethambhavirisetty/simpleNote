import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      // All /api/* requests → BE (no CORS preflight, same origin from browser's POV)
      '/api': {
        target: 'http://localhost:3001',
        changeOrigin: true,
      },
      // /agent/* requests → Agent (rewrites path: /agent/api/chat → /api/chat)
      '/agent': {
        target: 'http://localhost:3002',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/agent/, ''),
      },
    },
  },
})
