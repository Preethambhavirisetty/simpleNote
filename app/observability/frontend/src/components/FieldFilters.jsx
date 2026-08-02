import { useState } from 'react'

const OPS = [
  ['eq', 'is'],
  ['ne', 'is not'],
  ['contains', 'contains'],
  ['gt', '>'],
  ['gte', '≥'],
  ['lt', '<'],
  ['lte', '≤'],
  ['exists', 'exists'],
]

const opLabel = (op) => OPS.find(([v]) => v === op)?.[1] ?? op

/** Builds `?f.<name>.<op>=<value>` filters over whatever fields exist.
 *  The field list comes from the registry, so a field tracked for the first
 *  time five minutes ago is filterable here with no code change. */
export default function FieldFilters({ fields, value, onChange }) {
  const [name, setName] = useState('')
  const [op, setOp] = useState('eq')
  const [val, setVal] = useState('')

  const selected = fields.find((f) => f.name === name)
  const numeric = selected?.kind === 'number'

  function add(e) {
    e.preventDefault()
    if (!name) return
    if (op !== 'exists' && val === '') return
    onChange([...value, { name, op, value: op === 'exists' ? '1' : val }])
    setVal('')
  }

  return (
    <div>
      <form onSubmit={add} style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <select
          value={name}
          onChange={(e) => {
            setName(e.target.value)
            const f = fields.find((x) => x.name === e.target.value)
            setOp(f?.kind === 'number' ? 'gte' : 'eq')
          }}
          aria-label="Tracked field"
        >
          <option value="">＋ filter by tracked field…</option>
          {fields.map((f) => (
            <option key={f.name} value={f.name}>
              {f.name}
              {f.unit ? ` (${f.unit})` : ''}
            </option>
          ))}
        </select>

        {name && (
          <>
            <select value={op} onChange={(e) => setOp(e.target.value)} aria-label="Operator">
              {OPS.filter(([v]) =>
                numeric ? v !== 'contains' : !['gt', 'gte', 'lt', 'lte'].includes(v),
              ).map(([v, label]) => (
                <option key={v} value={v}>{label}</option>
              ))}
            </select>
            {op !== 'exists' && (
              <input
                type="text"
                value={val}
                onChange={(e) => setVal(e.target.value)}
                placeholder={numeric ? '0' : 'value'}
                style={{ width: 130 }}
                aria-label="Value"
              />
            )}
            <button className="btn sm" type="submit">Add</button>
          </>
        )}
      </form>

      {value.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
          {value.map((f, i) => (
            <span key={`${f.name}-${f.op}-${i}`} className="chip" style={{ cursor: 'default' }}>
              <span className="mono" style={{ fontSize: 11.5 }}>
                {f.name} {opLabel(f.op)} {f.op !== 'exists' && f.value}
              </span>
              <button
                type="button"
                className="pin"
                aria-label={`Remove filter ${f.name}`}
                onClick={() => onChange(value.filter((_, j) => j !== i))}
              >
                ✕
              </button>
            </span>
          ))}
          <button className="btn sm" type="button" onClick={() => onChange([])}>
            Clear all
          </button>
        </div>
      )}
    </div>
  )
}
