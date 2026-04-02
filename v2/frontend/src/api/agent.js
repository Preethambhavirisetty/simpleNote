import agentClient, { AGENT_BASE_URL, AGENT_PATH_PREFIX, AGENT_API_KEY } from './agentClient'

// In dev:   AGENT_PATH_PREFIX = '/agent' → Vite proxy rewrites /agent/api/* → localhost:3002/api/*
// In prod:  AGENT_PATH_PREFIX = ''       → AGENT_BASE_URL is set to real host, paths are /api/*
const p = (path) => `${AGENT_PATH_PREFIX}${path}`

export const agentApi = {
  getStatus: (taskId) => agentClient.get(p(`/api/status/${taskId}`)),
  ingest: (data) => agentClient.post(p('/api/ingest'), data),
  getContext: (data) => agentClient.post(p('/api/get-context'), data),
  chat: (data) => agentClient.post(p('/api/chat'), data),
}

/**
 * SSE streaming via the agent's /api/chat/stream endpoint.
 * Events: meta, delta, error, done.
 */
export async function streamChat({ body, onMeta, onDelta, onDone, onError }) {
  const url = AGENT_BASE_URL
    ? `${AGENT_BASE_URL}/api/chat/stream`
    : `${AGENT_PATH_PREFIX}/api/chat/stream`

  let reader
  let doneFired = false

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': AGENT_API_KEY,
      },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      throw new Error(`Agent responded with ${response.status}`)
    }

    reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop()

      for (const part of parts) {
        const lines = part.split('\n')
        let event = ''
        let data = ''

        for (const line of lines) {
          if (line.startsWith('event: ')) event = line.slice(7).trim()
          else if (line.startsWith('data: ')) data = line.slice(6).trim()
        }
        if (!event || !data) continue

        try {
          const parsed = JSON.parse(data)
          if (event === 'meta') onMeta?.(parsed)
          else if (event === 'delta') onDelta?.(parsed.content ?? '')
          else if (event === 'error') onError?.(new Error(parsed.message))
          else if (event === 'done' && !doneFired) {
            doneFired = true
            onDone?.(parsed)
          }
        } catch {
          // skip malformed
        }
      }
    }

    if (!doneFired) onDone?.({})
  } catch (err) {
    onError?.(err)
  } finally {
    reader?.cancel().catch(() => {})
  }
}
