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
      // The backend envelope is {success, message, error: {code}}; keep the
      // code so the UI can act on it instead of parsing the sentence.
      const detail = payload?.detail
      const failure = {
        code: payload?.error?.code ?? detail?.code ?? statusCode(response.status),
        message: payload?.message ?? detail?.message ?? 'Something went wrong. Please try again.',
        retryable: detail?.retryable ?? response.status >= 500,
      }
      const error = new Error(failure.message)
      error.failure = failure
      throw error
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
    else if (event === 'error') {
      // Carries {code, message, retryable} from the shared catalog; the Error
      // message stays human-readable for logs and for older handlers.
      const error = new Error(payload.message ?? 'Something went wrong. Please try again.')
      error.failure = payload
      handlers.onError?.(error)
    }
    else if (event === 'done') handlers.onDone?.(payload)
  } catch {
    // Ignore malformed SSE events and continue consuming the stream.
  }
}

function statusCode(status) {
  if (status === 401 || status === 403) return 'AUTH_REQUIRED'
  if (status === 429) return 'RATE_LIMITED'
  if (status >= 500) return 'AGENT_UNAVAILABLE'
  return 'UNKNOWN'
}

function isAbortError(error) {
  return error?.name === 'AbortError'
}
