import axios from 'axios'

// In dev the Vite proxy rewrites /agent/* → localhost:3002/* (strips /agent prefix).
// In prod set VITE_AGENT_URL to the agent's origin; paths will be /agent/api/... → rewritten.
export const AGENT_BASE_URL = import.meta.env.VITE_AGENT_URL ?? ''
export const AGENT_PATH_PREFIX = import.meta.env.VITE_AGENT_URL ? '' : '/agent'
export const AGENT_API_KEY = import.meta.env.VITE_AGENT_API_KEY ?? ''

const agentClient = axios.create({
  baseURL: AGENT_BASE_URL,
  headers: {
    'X-API-Key': AGENT_API_KEY,
  },
})

export default agentClient
