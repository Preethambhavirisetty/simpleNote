import { STATUS_STYLE, fmtNum, phaseColor } from '../utils/format'

/** Status is colour + icon + word -- never colour alone. */
export function StatusBadge({ status }) {
  const s = STATUS_STYLE[status] ?? { color: 'var(--text-muted)', icon: '?', label: status }
  return (
    <span className="badge" style={{ color: s.color, borderColor: 'currentColor' }}>
      <span aria-hidden="true">{s.icon}</span>
      {s.label}
    </span>
  )
}

export function PhaseChip({ phase, count, active, onClick }) {
  const label = phase ?? 'no phase'
  return (
    <button
      type="button"
      className="chip"
      aria-pressed={active ? 'true' : 'false'}
      onClick={onClick}
      style={active ? { color: phaseColor(phase) } : undefined}
    >
      <span className="swatch" style={{ background: phaseColor(phase) }} aria-hidden="true" />
      <span>{label}</span>
      {count !== undefined && <span className="count">{count}</span>}
    </button>
  )
}

export function Tile({ label, value, sub, color }) {
  return (
    <div className="card tile">
      <div className="label">{label}</div>
      <div className="value" style={color ? { color } : undefined}>{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

export function Spinner({ what = 'Loading' }) {
  return <div className="spinner">{what}…</div>
}

export function ErrorBox({ error }) {
  return (
    <div className="err-box">
      <strong>✕ Request failed</strong>
      <div style={{ marginTop: 4, fontSize: 13 }}>{String(error?.message ?? error)}</div>
    </div>
  )
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>
}

/** Single-series magnitude: one sequential hue, no legend (the title names it). */
export function Sparkline({ values, width = 82, height = 18 }) {
  const nums = (values ?? []).filter((v) => typeof v === 'number')
  if (nums.length < 2) return null
  const max = Math.max(...nums)
  const min = Math.min(...nums)
  const span = max - min || 1
  const step = width / (nums.length - 1)
  const points = nums
    .map((v, i) => `${(i * step).toFixed(1)},${(height - ((v - min) / span) * (height - 3) - 1.5).toFixed(1)}`)
    .join(' ')
  return (
    <svg
      width={width} height={height} viewBox={`0 0 ${width} ${height}`}
      role="img" aria-label={`${nums.length} values, ${fmtNum(min)} to ${fmtNum(max)}`}
      style={{ display: 'block', overflow: 'visible' }}
    >
      <polyline points={points} fill="none" stroke="var(--seq-450)" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** Horizontal bars. One measure, one hue; every bar directly labelled. */
export function BarChart({ items, unit, formatter = fmtNum, maxRows = 14 }) {
  const rows = (items ?? []).slice(0, maxRows)
  if (!rows.length) return <Empty>No data in this window.</Empty>
  const max = Math.max(...rows.map((r) => Math.abs(r.value ?? 0)), 1)

  return (
    <div style={{ display: 'grid', gap: 6 }}>
      {rows.map((r) => (
        <div
          key={r.bucket ?? 'total'}
          style={{ display: 'grid', gridTemplateColumns: '150px minmax(0,1fr) 92px', gap: 10, alignItems: 'center' }}
        >
          <div className="truncate secondary" style={{ fontSize: 12.5 }} title={r.bucket ?? 'all'}>
            {r.bucket ?? 'all'}
          </div>
          <div style={{ background: 'var(--surface-sunken)', borderRadius: 4, height: 14 }}>
            <div
              style={{
                width: `${Math.max(1.5, (Math.abs(r.value ?? 0) / max) * 100)}%`,
                height: '100%', background: 'var(--seq-450)',
                borderTopRightRadius: 4, borderBottomRightRadius: 4,
              }}
            />
          </div>
          <div className="tnum" style={{ textAlign: 'right', fontSize: 12.5, fontWeight: 600 }}>
            {formatter(r.value, unit)}
            <span className="muted" style={{ fontWeight: 500 }}> ·{r.n}</span>
          </div>
        </div>
      ))}
    </div>
  )
}
