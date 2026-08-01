import { useState } from 'react'

import { Empty } from './Primitives'
import { LEVEL_ICON, fmtClock, fmtMs, fmtValue, phaseColor } from '../utils/format'

function JsonBlock({ value }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>
}

function LogRow({ line, open, onToggle, maxDuration, highlight }) {
  const isError = line.level === 'ERROR'
  const bar = line.duration_ms && maxDuration
    ? Math.max(2, (line.duration_ms / maxDuration) * 56)
    : 0

  return (
    <>
      <div
        className={`log-row${isError ? ' is-error' : ''}${open ? ' is-open' : ''}`}
        onClick={onToggle}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onToggle()
          }
        }}
        id={`log-${line.id}`}
        style={highlight ? { outline: '2px solid var(--cat-1)', outlineOffset: -2 } : undefined}
      >
        <span className="log-seq">{line.seq}</span>
        {/* level: icon + word + colour, never colour alone */}
        <span className={`level level-${line.level}`} title={line.level}>
          <span aria-hidden="true">{LEVEL_ICON[line.level]}</span> {line.level}
        </span>
        <span className="truncate" style={{ fontSize: 11.5 }}>
          {line.phase ? (
            <>
              <span
                className="swatch"
                aria-hidden="true"
                style={{
                  display: 'inline-block', width: 7, height: 7, borderRadius: 2,
                  background: phaseColor(line.phase), marginRight: 5,
                }}
              />
              <span className="secondary">{line.phase}</span>
            </>
          ) : (
            <span className="muted">—</span>
          )}
        </span>
        <span className="log-msg">
          {line.message}
          {line.tracked.length > 0 && (
            <span className="tracked-inline">
              {line.tracked.slice(0, 4).map((t) => (
                <span className="tag" key={t.name} title={`${t.name} = ${fmtValue(t.value, t.unit)}`}>
                  {t.name} {fmtValue(t.value, t.unit)}
                </span>
              ))}
              {line.tracked.length > 4 && (
                <span className="tag">+{line.tracked.length - 4}</span>
              )}
            </span>
          )}
        </span>
        <span className="log-dur">
          {line.duration_ms != null && (
            <>
              {bar > 0 && (
                <span
                  aria-hidden="true"
                  style={{
                    display: 'inline-block', width: bar, height: 5,
                    background: 'var(--seq-250)', borderRadius: 3, marginRight: 6,
                    verticalAlign: 'middle',
                  }}
                />
              )}
              {fmtMs(line.duration_ms)}
            </>
          )}
        </span>
      </div>

      {open && (
        <div className="log-detail">
          <dl>
            <dt>time</dt>
            <dd className="mono">{fmtClock(line.ts)}</dd>
            <dt>source</dt>
            <dd className="mono">{line.source ?? '—'}</dd>
            {line.duration_ms != null && (
              <>
                <dt>duration</dt>
                <dd className="mono">{line.duration_ms} ms</dd>
              </>
            )}
            {line.tracked.length > 0 && (
              <>
                <dt>tracked</dt>
                <dd>
                  {line.tracked.map((t) => (
                    <div key={t.name} className="mono" style={{ fontSize: 11.5 }}>
                      {t.name} = {typeof t.value === 'object'
                        ? <JsonBlock value={t.value} />
                        : fmtValue(t.value, t.unit)}
                    </div>
                  ))}
                </dd>
              </>
            )}
            {line.data && (
              <>
                <dt>data</dt>
                <dd><JsonBlock value={line.data} /></dd>
              </>
            )}
          </dl>
        </div>
      )}
    </>
  )
}

export default function LogStream({ lines, highlightId }) {
  const [openId, setOpenId] = useState(null)
  if (!lines.length) return <Empty>No log lines match these filters.</Empty>

  const maxDuration = Math.max(...lines.map((l) => l.duration_ms ?? 0), 0)

  return (
    <div>
      {lines.map((line) => (
        <LogRow
          key={line.id}
          line={line}
          open={openId === line.id}
          highlight={highlightId === line.id}
          maxDuration={maxDuration}
          onToggle={() => setOpenId(openId === line.id ? null : line.id)}
        />
      ))}
    </div>
  )
}
