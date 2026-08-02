import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { api } from '../api/client'
import LogStream from '../components/LogStream'
import TrackedPanel from '../components/TrackedPanel'
import { ErrorBox, PhaseChip, Spinner, StatusBadge, Tile } from '../components/Primitives'
import { LEVELS, LEVEL_ICON, fmtMs, fmtTime, fmtValue } from '../utils/format'

export default function RunDetailPage() {
  const { runKey } = useParams()
  const [level, setLevel] = useState('DEBUG')
  const [phase, setPhase] = useState(null)
  const [search, setSearch] = useState('')
  const [highlight, setHighlight] = useState(null)

  const runQ = useQuery({
    queryKey: ['run', runKey],
    queryFn: () => api.run(runKey),
    // a still-running run keeps updating; poll it, leave finished ones alone
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 2000 : false),
  })
  const isLive = runQ.data?.status === 'running'

  const logParams = useMemo(
    () => ({ level, phase: phase ?? undefined, q: search || undefined, limit: 2000 }),
    [level, phase, search],
  )
  const logsQ = useQuery({
    queryKey: ['logs', runKey, logParams],
    queryFn: () => api.runLogs(runKey, logParams),
    refetchInterval: isLive ? 2000 : false,
  })
  const phasesQ = useQuery({
    queryKey: ['phases', runKey],
    queryFn: () => api.runPhases(runKey),
    refetchInterval: isLive ? 4000 : false,
  })

  if (runQ.isLoading) return <div className="page"><Spinner what="Loading run" /></div>
  if (runQ.isError) return <div className="page"><ErrorBox error={runQ.error} /></div>

  const run = runQ.data
  const lines = logsQ.data?.items ?? []
  const fields = run.fields ?? []
  const pinned = fields.filter((f) => f.pinned)

  function jumpToLine(logId) {
    setLevel('DEBUG')
    setPhase(null)
    setSearch('')
    setHighlight(logId)
    requestAnimationFrame(() => {
      document.getElementById(`log-${logId}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    })
  }

  return (
    <div className="page">
      <div style={{ marginBottom: 10 }}>
        <Link to="/" className="secondary" style={{ fontSize: 13 }}>← All runs</Link>
      </div>

      <div className="card run-header">
        <h2 className="run-question">{run.question ?? <span className="muted">no question recorded</span>}</h2>
        <div className="run-meta">
          <StatusBadge status={run.status} />
          <span>{fmtMs(run.duration_ms)}</span>
          <span>{run.log_count} log lines</span>
          {run.error_count > 0 && (
            <span style={{ color: 'var(--status-critical)' }}>
              ✕ {run.error_count} error {run.error_count === 1 ? 'line' : 'lines'}
            </span>
          )}
          <span className="muted">{fmtTime(run.started_at)}</span>
          {run.conversation_id && (
            <Link to={`/conversations/${run.conversation_id}`} className="secondary" style={{ textDecoration: 'underline' }}>
              {run.conversation_id}
            </Link>
          )}
          <span className="mono muted" style={{ fontSize: 11 }}>{run.run_key.slice(0, 12)}</span>
        </div>

        {pinned.length > 0 && (
          <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 10, fontSize: 12.5 }}>
            {pinned.map((f) => (
              <span key={f.name}>
                <span className="muted">{f.name}</span>{' '}
                <strong className="tnum">{fmtValue(f.value, f.unit)}</strong>
              </span>
            ))}
          </div>
        )}

        {run.final_answer && <div className="answer">{run.final_answer}</div>}
        {run.error_message && <div className="answer error">✕ {run.error_message}</div>}
      </div>

      <div className="split">
        <div className="card">
          <div className="panel-head">
            <span className="panel-title">Log stream</span>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search messages…"
              style={{
                marginLeft: 'auto', padding: '3px 8px', width: 180,
                border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)',
                background: 'var(--surface-1)',
              }}
              aria-label="Search log messages"
            />
          </div>

          <div className="panel-head" style={{ paddingTop: 8, paddingBottom: 8 }}>
            <span className="muted" style={{ fontSize: 11.5 }}>min level</span>
            {LEVELS.map((lv) => (
              <button
                key={lv}
                type="button"
                className="chip"
                aria-pressed={level === lv ? 'true' : 'false'}
                onClick={() => setLevel(lv)}
              >
                <span className={`level level-${lv}`} aria-hidden="true">{LEVEL_ICON[lv]}</span>
                {lv}
              </button>
            ))}
          </div>

          {(phasesQ.data?.items?.length ?? 0) > 0 && (
            <div className="panel-head" style={{ paddingTop: 8, paddingBottom: 8 }}>
              <PhaseChip phase="all" count={run.log_count} active={phase === null} onClick={() => setPhase(null)} />
              {phasesQ.data.items.map((p) => (
                <PhaseChip
                  key={p.phase ?? 'none'}
                  phase={p.phase}
                  count={p.log_count}
                  active={phase === p.phase}
                  onClick={() => setPhase(phase === p.phase ? null : p.phase)}
                />
              ))}
            </div>
          )}

          <div className="panel-body">
            {logsQ.isLoading ? <Spinner what="Loading logs" /> : (
              <LogStream lines={lines} highlightId={highlight} />
            )}
          </div>

          {logsQ.data?.has_more && (
            <div className="muted" style={{ padding: '8px 12px', fontSize: 12 }}>
              Showing the first {lines.length} lines — narrow the filters to see the rest.
            </div>
          )}
        </div>

        <div className="card">
          <div className="panel-head">
            <span className="panel-title">Tracked fields</span>
            <span className="muted" style={{ fontSize: 12, marginLeft: 'auto' }}>
              {fields.length} tracked · ★ pins to the runs list
            </span>
          </div>
          <div className="panel-body">
            <TrackedPanel fields={fields} onJump={jumpToLine} />
          </div>
        </div>
      </div>

      <div className="tiles" style={{ marginTop: 12 }}>
        <Tile label="Duration" value={fmtMs(run.duration_ms)} />
        <Tile label="Log lines" value={run.log_count} sub={`max seq ${run.max_seq}`} />
        <Tile
          label="Error lines"
          value={run.error_count}
          color={run.error_count ? 'var(--status-critical)' : undefined}
        />
        <Tile label="Tracked fields" value={fields.length} />
      </div>
    </div>
  )
}
