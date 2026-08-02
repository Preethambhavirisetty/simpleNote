import { useQuery } from '@tanstack/react-query'
import { Link, useParams, useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import { Empty, ErrorBox, Spinner, StatusBadge } from '../components/Primitives'
import { fmtMs, fmtTime } from '../utils/format'

export default function ConversationPage() {
  const { conversationId } = useParams()
  const navigate = useNavigate()

  const q = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => api.conversationRuns(conversationId),
  })

  if (q.isLoading) return <div className="page"><Spinner what="Loading conversation" /></div>
  if (q.isError) return <div className="page"><ErrorBox error={q.error} /></div>

  const runs = q.data.items ?? []

  return (
    <div className="page">
      <div style={{ marginBottom: 10 }}>
        <Link to="/" className="secondary" style={{ fontSize: 13 }}>← All runs</Link>
      </div>

      <div className="card run-header">
        <h2 className="run-question">Conversation {conversationId}</h2>
        <div className="run-meta">
          <span>{runs.length} run{runs.length === 1 ? '' : 's'}</span>
          <span>{runs.reduce((sum, r) => sum + r.log_count, 0)} log lines</span>
        </div>
      </div>

      {runs.length === 0 ? (
        <Empty>No runs in this conversation.</Empty>
      ) : (
        <div style={{ display: 'grid', gap: 10 }}>
          {runs.map((run, i) => (
            <div
              key={run.run_key}
              className="card"
              style={{ padding: '12px 14px', cursor: 'pointer' }}
              onClick={() => navigate(`/runs/${run.run_key}`)}
            >
              <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
                <span className="muted mono" style={{ fontSize: 11 }}>turn {i + 1}</span>
                <strong style={{ fontSize: 14 }}>{run.question}</strong>
                <span style={{ marginLeft: 'auto' }}><StatusBadge status={run.status} /></span>
              </div>
              {run.final_answer && (
                <div className="answer" style={{ marginTop: 8 }}>{run.final_answer}</div>
              )}
              <div className="run-meta" style={{ marginTop: 8 }}>
                <span className="muted">{fmtTime(run.started_at)}</span>
                <span>{fmtMs(run.duration_ms)}</span>
                <span>{run.log_count} logs</span>
                {run.error_count > 0 && (
                  <span style={{ color: 'var(--status-critical)' }}>✕ {run.error_count} errors</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
