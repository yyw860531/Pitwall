import ReactMarkdown from 'react-markdown'

function fmtMs(ms) {
  if (!ms) return '—'
  const m = Math.floor(ms / 60000)
  const s = ((ms % 60000) / 1000).toFixed(3)
  return `${m}:${s.padStart(6, '0')}`
}

const styles = {
  panel: { padding: '16px', height: '100%' },
  label: {
    fontSize: '11px', color: '#64748b',
    textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 12,
  },
  priorityCard: (rank) => ({
    background: rank === 1 ? 'rgba(127,29,29,0.3)' : 'rgba(113,63,18,0.25)',
    border: `1px solid ${rank === 1 ? '#7f1d1d' : '#713f12'}`,
    borderRadius: '6px',
    padding: '10px 12px',
    marginBottom: '10px',
  }),
  priorityLabel: (rank) => ({
    fontSize: '10px',
    color: rank === 1 ? '#fca5a5' : '#fde68a',
    textTransform: 'uppercase',
    letterSpacing: '0.1em',
    marginBottom: 4,
  }),
  headline: {
    fontSize: '13px',
    color: '#f1f5f9',
    fontWeight: 600,
    marginBottom: 4,
  },
  timeGain: {
    fontSize: '11px',
    color: '#4ade80',
  },
  divider: {
    border: 'none',
    borderTop: '1px solid #1e293b',
    margin: '14px 0',
  },
  markdown: {
    fontSize: '12px',
    lineHeight: '1.7',
    color: '#94a3b8',
  },
  summaryBar: {
    background: '#0f172a',
    border: '1px solid #1e293b',
    borderRadius: '6px',
    padding: '10px 12px',
    marginBottom: '14px',
    fontSize: '12px',
  },
  nextAction: {
    background: 'rgba(30,64,175,0.2)',
    border: '1px solid #1e3a8a',
    borderRadius: '6px',
    padding: '10px 12px',
    marginTop: '14px',
    fontSize: '12px',
    color: '#93c5fd',
  },
  nextLabel: {
    fontSize: '10px',
    color: '#3b82f6',
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    marginBottom: 4,
  },
}

export default function CoachingPanel({ report, session }) {
  return (
    <div style={styles.panel}>
      <div style={styles.label}>AI Race Engineer</div>

      {/* Session summary bar */}
      <div style={styles.summaryBar}>
        <div style={{ color: '#475569', fontSize: 10, marginBottom: 4 }}>SESSION SUMMARY</div>
        <div style={{ color: '#e2e8f0' }}>{report.session_summary}</div>
        {report.reference_note && (
          <div style={{ color: '#64748b', marginTop: 4, fontSize: 11 }}>
            ⚠ {report.reference_note}
          </div>
        )}
      </div>

      {/* Priority corners */}
      {report.priority_corners?.map(corner => (
        <div key={corner.corner_name} style={styles.priorityCard(corner.rank)}>
          <div style={styles.priorityLabel(corner.rank)}>
            Priority {corner.rank} · {corner.corner_name.replace(/_/g, ' ')}
          </div>
          <div style={styles.headline}>{corner.headline}</div>
          {corner.estimated_time_gain_ms > 0 && (
            <div style={styles.timeGain}>
              ↑ ~{corner.estimated_time_gain_ms}ms available
            </div>
          )}
        </div>
      ))}

      <hr style={styles.divider} />

      {/* Full coaching report */}
      <div style={styles.markdown}>
        <ReactMarkdown>{report.full_markdown}</ReactMarkdown>
      </div>

      {/* Next action */}
      {report.next_action && (
        <div style={styles.nextAction}>
          <div style={styles.nextLabel}>Next Session Focus</div>
          <div>{report.next_action}</div>
        </div>
      )}
    </div>
  )
}
