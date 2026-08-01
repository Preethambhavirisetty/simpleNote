import { useMemo, useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import FieldFilters from '../components/FieldFilters'
import { Empty, ErrorBox, Spinner, StatusBadge, Tile } from '../components/Primitives'
import { fmtMs, fmtValue, relTime } from '../utils/format'

export default function RunsPage() {
  const navigate = useNavigate()
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [hasErrors, setHasErrors] = useState('')
  const [fieldFilters, setFieldFilters] = useState([])
  const [cursor, setCursor] = useState(null)
  const [stack, setStack] = useState([])

  const params = useMemo(
    () => ({
      status: status || undefined,
      q: search || undefined,
      has_errors: hasErrors || undefined,
      cursor: cursor || undefined,
      limit: 50,
    }),
    [status, search, hasErrors, cursor],
  )

  const runsQ = useQuery({
    queryKey: ['runs', params, fieldFilters],
    queryFn: () => api.runs(params, fieldFilters),
    placeholderData: keepPreviousData,
  })
  const fieldsQ = useQuery({ queryKey: ['fields'], queryFn: () => api.fields() })
  const statsQ = useQuery({ queryKey: ['overview'], queryFn: () => api.statsOverview() })

  const pinned = (fieldsQ.data?.items ?? []).filter((f) => f.pinned)
  const items = runsQ.data?.items ?? []
  const stats = statsQ.data

  function resetPaging(fn) {
    return (value) => {
      setCursor(null)
      setStack([])
      fn(value)
    }
  }

  return (
    <div className="page">
      {stats && (
        <div className="tiles" style={{ marginBottom: 14 }}>
          <Tile label="Runs" value={stats.runs.toLocaleString()} sub={`${stats.log_lines.toLocaleString()} log lines`} />
          <Tile label="Succeeded" value={stats.ok} sub={`${stats.running} still running`} color="var(--status-good)" />
          <Tile label="Failed" value={stats.failed} sub={`${stats.with_errors} runs logged an error`} color={stats.failed ? 'var(--status-critical)' : undefined} />
          <Tile label="p50 duration" value={fmtMs(stats.p50_duration_ms)} sub={`p95 ${fmtMs(stats.p95_duration_ms)}`} />
        </div>
      )}

      <div className="card filterbar" style={{ display: 'block' }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            className="grow"
            type="text"
            placeholder="Search question or answer…"
            value={search}
            onChange={(e) => resetPaging(setSearch)(e.target.value)}
            aria-label="Search runs"
          />
          <select value={status} onChange={(e) => resetPaging(setStatus)(e.target.value)} aria-label="Status">
            <option value="">Any status</option>
            <option value="ok">ok</option>
            <option value="error">error</option>
            <option value="running">running</option>
          </select>
          <select value={hasErrors} onChange={(e) => resetPaging(setHasErrors)(e.target.value)} aria-label="Error lines">
            <option value="">Any log level</option>
            <option value="true">Has ERROR lines</option>
            <option value="false">No ERROR lines</option>
          </select>
        </div>
        <div style={{ marginTop: 8, borderTop: '1px solid var(--grid)', paddingTop: 8 }}>
          <FieldFilters
            fields={fieldsQ.data?.items ?? []}
            value={fieldFilters}
            onChange={(v) => {
              setCursor(null)
              setStack([])
              setFieldFilters(v)
            }}
          />
        </div>
      </div>

      {runsQ.isError && <ErrorBox error={runsQ.error} />}
      {runsQ.isLoading && <Spinner what="Loading runs" />}

      {runsQ.data && (
        <div className="card table-wrap">
          {items.length === 0 ? (
            <Empty>No runs match these filters.</Empty>
          ) : (
            <table className="runs">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Question</th>
                  {pinned.map((f) => (
                    <th key={f.name}>{f.label}</th>
                  ))}
                  <th className="num">Logs</th>
                  <th className="num">Duration</th>
                  <th>Started</th>
                </tr>
              </thead>
              <tbody>
                {items.map((run) => (
                  <tr key={run.run_key} onClick={() => navigate(`/runs/${run.run_key}`)}>
                    <td><StatusBadge status={run.status} /></td>
                    <td style={{ maxWidth: 340 }}>
                      <div className="truncate" title={run.question}>{run.question}</div>
                      {run.error_count > 0 && (
                        <div style={{ fontSize: 11.5, color: 'var(--status-critical)' }}>
                          ✕ {run.error_count} error {run.error_count === 1 ? 'line' : 'lines'}
                        </div>
                      )}
                    </td>
                    {pinned.map((f) => (
                      <td key={f.name} className={f.kind === 'number' ? 'num' : undefined}>
                        <span className={f.kind === 'number' ? 'tnum' : 'truncate'}>
                          {run.fields?.[f.name] === undefined
                            ? <span className="muted">—</span>
                            : fmtValue(run.fields[f.name], f.unit)}
                        </span>
                      </td>
                    ))}
                    <td className="num">{run.log_count}</td>
                    <td className="num">{fmtMs(run.duration_ms)}</td>
                    <td className="nowrap secondary" title={run.started_at}>{relTime(run.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center' }}>
        <button
          className="btn"
          disabled={stack.length === 0}
          onClick={() => {
            const prev = [...stack]
            const back = prev.pop()
            setStack(prev)
            setCursor(back ?? null)
          }}
        >
          ← Previous
        </button>
        <button
          className="btn"
          disabled={!runsQ.data?.has_more}
          onClick={() => {
            setStack([...stack, cursor])
            setCursor(runsQ.data.next_cursor)
          }}
        >
          Next →
        </button>
        <span className="muted" style={{ fontSize: 12.5 }}>
          {items.length} run{items.length === 1 ? '' : 's'} shown
        </span>
      </div>
    </div>
  )
}
