const BASE = '/api/v1'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json()
}

/** Build a query string, dropping empty values and expanding `fieldFilters`. */
export function qs(params = {}, fieldFilters = []) {
  const sp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    sp.set(key, value)
  }
  for (const f of fieldFilters) {
    if (!f.name || f.value === '') continue
    sp.append(f.op && f.op !== 'eq' ? `f.${f.name}.${f.op}` : `f.${f.name}`, f.value)
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

export const api = {
  runs: (params, fieldFilters) => request(`/runs${qs(params, fieldFilters)}`),
  run: (key) => request(`/runs/${encodeURIComponent(key)}`),
  runLogs: (key, params) => request(`/runs/${encodeURIComponent(key)}/logs${qs(params)}`),
  runPhases: (key) => request(`/runs/${encodeURIComponent(key)}/phases`),
  conversationRuns: (id) => request(`/conversations/${encodeURIComponent(id)}/runs`),
  fields: (params) => request(`/fields${qs(params)}`),
  patchField: (name, body) =>
    request(`/fields/${encodeURIComponent(name)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  statsOverview: (params) => request(`/stats/overview${qs(params)}`),
  statsField: (name, params) =>
    request(`/stats/fields/${encodeURIComponent(name)}${qs(params)}`),
  statsTimeseries: (params) => request(`/stats/timeseries${qs(params)}`),
  statsPhases: (params) => request(`/stats/phases${qs(params)}`),
}
