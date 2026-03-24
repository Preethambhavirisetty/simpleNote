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
 * OpenAI-compatible streaming: POST /v1/chat/completions
 * Uses native fetch for SSE — axios doesn't support streaming cleanly.
 */
export async function streamChatCompletions({ messages, model = 'llama3.1', onChunk, onDone, onError }) {
  // In dev use the Vite proxy path; in prod use the full agent URL
  const url = AGENT_BASE_URL
    ? `${AGENT_BASE_URL}/v1/chat/completions`
    : `${AGENT_PATH_PREFIX}/v1/chat/completions`

  let reader

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': AGENT_API_KEY,
      },
      body: JSON.stringify({ model, messages, stream: true }),
    })

    if (!response.ok) {
      throw new Error(`Agent responded with ${response.status}`)
    }

    reader = response.body.getReader()
    const decoder = new TextDecoder()

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const text = decoder.decode(value, { stream: true })
      const lines = text.split('\n').filter((l) => l.startsWith('data: '))

      for (const line of lines) {
        const payload = line.slice(6).trim()
        if (payload === '[DONE]') {
          onDone?.()
          return
        }
        try {
          const parsed = JSON.parse(payload)
          const delta = parsed.choices?.[0]?.delta?.content ?? ''
          if (delta) onChunk(delta)
        } catch {
          // skip malformed chunk
        }
      }
    }

    onDone?.()
  } catch (err) {
    onError?.(err)
  } finally {
    reader?.cancel().catch(() => {})
  }
}
