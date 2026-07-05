/**
 * SSE streaming through the cookie-authenticated backend proxy.
 * Events: meta, delta, error, done.
 */
export async function streamChat({ body, signal, endpoint = '/api/chat/stream', onMeta, onDelta, onDone, onError }) {
  let reader
  let doneFired = false

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      body: JSON.stringify(body),
      signal,
    })

    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      throw new Error(payload?.message ?? payload?.detail ?? ('Chat request failed with ' + response.status))
    }

    if (!response.body) throw new Error('Chat response did not include a stream')
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
