/** Fixed phase -> categorical slot map.
 *  Colour follows the entity, never its rank: a phase keeps its hue no matter
 *  what else is on screen or which filters are active. Past slot 8 phases fold
 *  into a neutral "other" rather than cycling the ramp. */
const PHASE_SLOTS = [
  'intake',
  'resolve_playbook',
  'resolve_resource',
  'resolve_operation',
  'llm',
  'tool',
  'memory',
  'respond',
]

export function phaseColor(phase) {
  const i = PHASE_SLOTS.indexOf(phase)
  return i === -1 ? 'var(--cat-other)' : `var(--cat-${i + 1})`
}

export const LEVELS = ['DEBUG', 'INFO', 'WARN', 'ERROR']

/** Level is icon + word + colour, so it survives greyscale and CVD. */
export const LEVEL_ICON = { DEBUG: '·', INFO: '○', WARN: '▲', ERROR: '✕' }

export function fmtMs(ms) {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)}s`
  const m = Math.floor(ms / 60000)
  return `${m}m ${Math.round((ms % 60000) / 1000)}s`
}

export function fmtNum(n) {
  if (n === null || n === undefined) return '—'
  if (typeof n !== 'number') return String(n)
  if (Number.isInteger(n)) {
    if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
    if (Math.abs(n) >= 10_000) return `${(n / 1000).toFixed(1)}k`
    return n.toLocaleString()
  }
  if (Math.abs(n) < 0.01 && n !== 0) return n.toExponential(2)
  return Number(n.toFixed(4)).toLocaleString()
}

export function fmtValue(value, unit) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return Array.isArray(value) ? `[${value.length}]` : '{…}'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'number') {
    if (unit === 'ms') return fmtMs(value)
    if (unit === 'usd') return `$${value < 0.01 ? value.toFixed(5) : value.toFixed(3)}`
    return fmtNum(value) + (unit ? ` ${unit}` : '')
  }
  return String(value)
}

export function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`)
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

export function fmtClock(iso) {
  if (!iso) return ''
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`)
  return d.toLocaleTimeString(undefined, {
    hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

export function relTime(iso) {
  if (!iso) return '—'
  const then = new Date(iso.endsWith('Z') ? iso : `${iso}Z`).getTime()
  const secs = Math.round((Date.now() - then) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`
  return `${Math.round(secs / 86400)}d ago`
}

export const STATUS_STYLE = {
  ok: { color: 'var(--status-good)', icon: '✓', label: 'ok' },
  error: { color: 'var(--status-critical)', icon: '✕', label: 'error' },
  running: { color: 'var(--cat-1)', icon: '◐', label: 'running' },
}
