import agentClient, { AGENT_BASE_URL, AGENT_PATH_PREFIX, AGENT_API_KEY } from './agentClient'

// In dev: AGENT_PATH_PREFIX = '/agent' and Vite proxies to the local agent.
// In prod: AGENT_BASE_URL is the agent origin and paths begin with /api.
const p = (path) => `${AGENT_PATH_PREFIX}${path}`

export const agentApi = {
  getStatus: (taskId) => agentClient.get(p(`/api/ingest/status/${taskId}`)),
  ingest: (data) => agentClient.post(p('/api/ingest'), data),
  getContext: (data) => agentClient.post(p('/api/chat/stream'), data),
  chat: (data) => agentClient.post(p('/api/chat/completions'), data),
}

/** Stream SSE chat events until completion or until the caller aborts the request. */
export async function streamChat({ body, signal, onMeta, onDelta, onDone, onError }) {
  const url = AGENT_BASE_URL ? `${AGENT_BASE_URL}/api/chat/stream` : `${AGENT_PATH_PREFIX}/api/chat/stream`
  let reader
  let doneFired = false

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': AGENT_API_KEY },
      body: JSON.stringify(body),
      signal,
    })
    if (!response.ok) throw new Error(`Agent responded with ${response.status}`)
    if (!response.body) throw new Error('Agent response did not include a stream')

    reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop()
      parts.forEach((part) => handleEvent(part, { onMeta, onDelta, onDone: (payload) => {
        if (doneFired) return
        doneFired = true
        onDone?.(payload)
      }, onError }))
    }

    if (!doneFired && !signal?.aborted) onDone?.({})
  } catch (error) {
    if (!isAbortError(error)) onError?.(error)
  } finally {
    reader?.cancel().catch(() => {})
  }
}

function handleEvent(part, handlers) {
  let event = ''
  let data = ''
  part.split('\n').forEach((line) => {
    if (line.startsWith('event: ')) event = line.slice(7).trim()
    else if (line.startsWith('data: ')) data += line.slice(6).trim()
  })
  if (!event || !data) return

  try {
    const payload = JSON.parse(data)
    if (event === 'meta') handlers.onMeta?.(payload)
    else if (event === 'delta') handlers.onDelta?.(payload.content ?? '')
    else if (event === 'error') handlers.onError?.(new Error(payload.message))
    else if (event === 'done') handlers.onDone?.(payload)
  } catch {
    // Ignore malformed SSE events and continue consuming the stream.
  }
}

function isAbortError(error) {
  return error?.name === 'AbortError'
}
