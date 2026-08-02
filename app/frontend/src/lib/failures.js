/**
 * Failure handling for the chat path.
 *
 * The server owns the wording. Every service in the chain (agent-runtime,
 * orchestrator, backend) now sends `{code, message, retryable}` from one
 * catalog in `app/shared/failures.py`, so this module does not keep a second
 * copy of the copy - it renders what it is given and switches behaviour on
 * `code`.
 *
 * The fallbacks below exist only for failures that never reach a server: the
 * fetch itself dying, or an old build still sending bare text. Previously this
 * file's job was done by substring-matching raw Python exception strings
 * (`message.includes('401')`, `includes('inference')`), which broke silently
 * whenever anything upstream reworded an error.
 */

// Codes the UI treats specially. Everything else just renders its message.
export const FAILURE_CODES = {
  AUTH_REQUIRED: 'AUTH_REQUIRED',
  RATE_LIMITED: 'RATE_LIMITED',
  APPROVAL_REQUIRED: 'APPROVAL_REQUIRED',
  ACTION_NOT_SUPPORTED: 'ACTION_NOT_SUPPORTED',
  NOTES_NOT_INDEXED: 'NOTES_NOT_INDEXED',
  CANCELLED: 'CANCELLED',
}

// Used only when the request never reached a service that could classify it.
const CLIENT_FALLBACKS = {
  OFFLINE: 'You appear to be offline. Check your connection and try again.',
  UNKNOWN: 'Something went wrong. Please try again.',
}

/**
 * Normalise anything thrown or streamed into `{code, message, retryable}`.
 *
 * Accepts a server failure payload, an Error carrying one, or a bare Error.
 */
export function toFailure(input) {
  const payload = input?.failure ?? input
  if (payload && typeof payload === 'object' && typeof payload.code === 'string') {
    return {
      code: payload.code,
      message: payload.message || CLIENT_FALLBACKS.UNKNOWN,
      retryable: payload.retryable ?? true,
    }
  }

  // No code: the failure happened in the browser, before any service saw it.
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    return { code: 'OFFLINE', message: CLIENT_FALLBACKS.OFFLINE, retryable: true }
  }
  const text = input?.message
  return {
    code: 'UNKNOWN',
    // A server-authored sentence is worth showing; a raw stack-ish string is
    // not, and there is no reliable way to tell them apart, so prefer the
    // generic line unless the text reads like a sentence meant for a person.
    message: looksUserFacing(text) ? text : CLIENT_FALLBACKS.UNKNOWN,
    retryable: true,
  }
}

function looksUserFacing(text) {
  if (typeof text !== 'string' || text.length < 12 || text.length > 200) return false
  if (/https?:\/\/|Error:|Traceback|\bat \w+\.\w+|\{|\}/.test(text)) return false
  return /[.!?]$/.test(text.trim())
}

export function isAuthFailure(failure) {
  return failure?.code === FAILURE_CODES.AUTH_REQUIRED
}

export function isRetryable(failure) {
  return failure?.retryable !== false
}
