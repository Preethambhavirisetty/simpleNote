import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { BarChart, Empty, ErrorBox, Spinner, Tile } from '../components/Primitives'
import { fmtMs, fmtNum, fmtValue, phaseColor } from '../utils/format'

const AGGS = ['avg', 'sum', 'min', 'max', 'count']

export default function StatsPage() {
  const [field, setField] = useState('llm_latency_ms')
  const [agg, setAgg] = useState('avg')
  const [groupBy, setGroupBy] = useState('playbook')

  const fieldsQ = useQuery({ queryKey: ['fields'], queryFn: () => api.fields() })
  const overviewQ = useQuery({ queryKey: ['overview'], queryFn: () => api.statsOverview() })
  const phasesQ = useQuery({ queryKey: ['statsPhases'], queryFn: () => api.statsPhases() })

  const all = fieldsQ.data?.items ?? []
  const numeric = all.filter((f) => f.kind === 'number' || f.kind === 'bool')
  const textual = all.filter((f) => f.kind === 'text')

  const explorerQ = useQuery({
    queryKey: ['fieldStats', field, agg, groupBy],
    queryFn: () => api.statsField(field, { agg, group_by: groupBy || undefined }),
    enabled: Boolean(field),
  })

  const selected = all.find((f) => f.name === field)
  const stats = overviewQ.data
  const maxPhase = Math.max(...(phasesQ.data?.items ?? []).map((p) => p.log_count), 1)

  return (
    <div className="page">
      {stats && (
        <div className="tiles" style={{ marginBottom: 16 }}>
          <Tile label="Runs" value={stats.runs.toLocaleString()} />
          <Tile label="Log lines" value={stats.log_lines.toLocaleString()} />
          <Tile label="Error rate" value={`${(stats.error_rate * 100).toFixed(1)}%`}
            sub={`${stats.with_errors} of ${stats.runs} runs`}
            color={stats.error_rate > 0.2 ? 'var(--status-critical)' : undefined} />
          <Tile label="p50 duration" value={fmtMs(stats.p50_duration_ms)} />
          <Tile label="p95 duration" value={fmtMs(stats.p95_duration_ms)} />
          <Tile label="Tracked fields" value={all.length} sub={`${all.filter((f) => f.pinned).length} pinned`} />
        </div>
      )}

      <div className="card">
        <div className="panel-head">
          <span className="panel-title">Field explorer</span>
          <span className="muted" style={{ fontSize: 12 }}>
            any tracked field, aggregated and grouped
          </span>
        </div>

        <div className="filterbar" style={{ marginBottom: 0 }}>
          <label style={{ fontSize: 12.5 }} className="muted">show</label>
          <select value={agg} onChange={(e) => setAgg(e.target.value)} aria-label="Aggregate">
            {AGGS.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <select value={field} onChange={(e) => setField(e.target.value)} aria-label="Field">
            {numeric.map((f) => (
              <option key={f.name} value={f.name}>{f.name}{f.unit ? ` (${f.unit})` : ''}</option>
            ))}
          </select>
          <label style={{ fontSize: 12.5 }} className="muted">grouped by</label>
          <select value={groupBy} onChange={(e) => setGroupBy(e.target.value)} aria-label="Group by">
            <option value="">— nothing (total) —</option>
            {textual.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
          </select>
        </div>

        <div style={{ padding: '14px 16px' }}>
          {explorerQ.isLoading && <Spinner what="Aggregating" />}
          {explorerQ.isError && <ErrorBox error={explorerQ.error} />}
          {explorerQ.data && (
            <>
              <div className="muted" style={{ fontSize: 12.5, marginBottom: 10 }}>
                {agg} of <strong>{field}</strong>
                {selected?.unit ? ` (${selected.unit})` : ''}
                {groupBy ? ` by ${groupBy}` : ' across all runs'}
              </div>
              <BarChart
                items={explorerQ.data.items}
                unit={selected?.unit}
                formatter={(v, u) => fmtValue(v, u)}
              />
            </>
          )}
        </div>
      </div>

      <div className="section-title">Log volume by phase</div>
      <div className="card" style={{ padding: '14px 16px' }}>
        {phasesQ.isLoading && <Spinner what="Loading phases" />}
        {(phasesQ.data?.items?.length ?? 0) === 0 && !phasesQ.isLoading && (
          <Empty>No phases recorded yet.</Empty>
        )}
        <div style={{ display: 'grid', gap: 6 }}>
          {(phasesQ.data?.items ?? []).map((p) => (
            <div
              key={p.phase}
              style={{ display: 'grid', gridTemplateColumns: '160px minmax(0,1fr) 128px', gap: 10, alignItems: 'center' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5 }}>
                <span className="swatch" aria-hidden="true"
                  style={{ width: 9, height: 9, borderRadius: 2, background: phaseColor(p.phase), flex: 'none' }} />
                <span className="truncate secondary">{p.phase}</span>
              </div>
              <div style={{ background: 'var(--surface-sunken)', borderRadius: 4, height: 14 }}>
                <div style={{
                  width: `${Math.max(1.5, (p.log_count / maxPhase) * 100)}%`, height: '100%',
                  background: phaseColor(p.phase), borderTopRightRadius: 4, borderBottomRightRadius: 4,
                }} />
              </div>
              <div className="tnum" style={{ textAlign: 'right', fontSize: 12.5 }}>
                <strong>{fmtNum(p.log_count)}</strong>
                {p.error_count > 0 && (
                  <span style={{ color: 'var(--status-critical)', marginLeft: 6 }}>
                    ✕{p.error_count}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
