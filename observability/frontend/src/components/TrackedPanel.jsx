import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import { Empty, Sparkline } from './Primitives'
import { fmtValue } from '../utils/format'

function FieldRow({ field, onJump }) {
  const [expanded, setExpanded] = useState(false)
  const qc = useQueryClient()

  const pinMutation = useMutation({
    mutationFn: (pinned) => api.patchField(field.name, { pinned }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['fields'] })
      qc.invalidateQueries({ queryKey: ['runs'] })
    },
  })

  const numeric = field.kind === 'number'
  const series = numeric ? field.values.map((v) => v.value) : []
  const isObject = typeof field.value === 'object' && field.value !== null

  return (
    <div className="field-row">
      <div className="field-top">
        <button
          type="button"
          className="pin"
          aria-pressed={field.pinned ? 'true' : 'false'}
          title={field.pinned ? 'Unpin from runs list' : 'Pin as a column in the runs list'}
          onClick={() => pinMutation.mutate(!field.pinned)}
        >
          {field.pinned ? '★' : '☆'}
        </button>
        <span className="field-name">{field.name}</span>
        <span className="field-value">
          {isObject ? (
            <button className="btn sm" type="button" onClick={() => setExpanded(!expanded)}>
              {expanded ? 'hide' : 'view'} {Array.isArray(field.value) ? 'list' : 'object'}
            </button>
          ) : (
            // fmtValue already carries the unit -- don't render it twice
            fmtValue(field.value, field.unit)
          )}
        </span>
      </div>

      <div className="field-sub">
        <span>
          {field.count > 1
            ? `${field.aggregate} of ${field.count} values`
            : field.kind}
        </span>
        {series.length > 1 && <Sparkline values={series} />}
        {field.values.length > 0 && field.values[0].log_id && (
          <button
            type="button"
            className="btn sm"
            style={{ marginLeft: 'auto' }}
            onClick={() => onJump(field.values[0].log_id)}
            title="Scroll to the log line that emitted this"
          >
            ↗ line {field.values[0].seq}
          </button>
        )}
      </div>

      {expanded && (
        <pre className="json">{JSON.stringify(field.value, null, 2)}</pre>
      )}

      {field.count > 1 && numeric && (
        <div className="mono muted" style={{ fontSize: 10.5, marginTop: 3 }}>
          {field.values.map((v) => v.value).join(', ')}
        </div>
      )}
    </div>
  )
}

export default function TrackedPanel({ fields, onJump }) {
  const [query, setQuery] = useState('')
  if (!fields.length) return <Empty>This run tracked no fields.</Empty>

  const shown = query
    ? fields.filter((f) => f.name.toLowerCase().includes(query.toLowerCase()))
    : fields

  return (
    <div>
      <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--grid)' }}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={`Filter ${fields.length} tracked fields…`}
          style={{
            width: '100%', padding: '4px 8px',
            border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)',
            background: 'var(--surface-1)',
          }}
          aria-label="Filter tracked fields"
        />
      </div>
      {shown.map((f) => (
        <FieldRow key={f.name} field={f} onJump={onJump} />
      ))}
      {shown.length === 0 && <Empty>No field matches “{query}”.</Empty>}
    </div>
  )
}
