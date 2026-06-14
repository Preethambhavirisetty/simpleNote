/**
 * Unwrap the BE's standard response envelope:
 *   { success: bool, message: string, error: any, data: <payload> }
 *
 * If the response doesn't match the envelope shape, returns it as-is
 * so the helper is safe to use even if the BE skips the wrapper.
 */
export function unwrap(response) {
  if (response && typeof response === 'object' && 'success' in response && 'data' in response) {
    return response.data
  }
  return response
}

/**
 * Unwrap a list endpoint response.
 * Handles:
 *   - envelope + plain array:      { success, data: [...] }
 *   - envelope + paginated object: { success, data: { items: [...], total: N } }
 *   - plain array (no envelope)
 */
export function unwrapList(response) {
  const inner = unwrap(response)
  if (Array.isArray(inner)) return inner
  return inner?.items ?? inner?.data ?? inner?.results ?? []
}
