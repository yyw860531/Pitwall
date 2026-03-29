import ReactMarkdown from 'react-markdown'

function fmtMs(ms) {
  if (!ms) return '—'
  const m = Math.floor(ms / 60000)
  const s = ((ms % 60000) / 1000).toFixed(3)
  return `${m}:${s.padStart(6, '0')}`
}

const styles = {
  panel: { padding: '20px' },
  label: {
    fontSize: '11px', color: '#64748b',
    textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 16,
  },
  // Priority cards row — display side by side when space allows
  priorityRow: {
    display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: '16px',
  },
  priorityCard: (rank) => ({
    flex: '1 1 220px',
    background: rank === 1 ? 'rgba(127,29,29,0.3)' : rank === 2 ? 'rgba(113,63,18,0.25)' : 'rgba(30,41,59,0.6)',
    border: `1px solid ${rank === 1 ? '#7f1d1d' : rank === 2 ? '#713f12' : '#1e293b'}`,
    borderRadius: '6px',
    padding: '12px 14px',
  }),
  priorityLabel: (rank) => ({
    fontSize: '10px',
    color: rank === 1 ? '#fca5a5' : rank === 2 ? '#fde68a' : '#64748b',
    textTransform: 'uppercase',
    letterSpacing: '0.1em',
    marginBottom: 6,
  }),
  headline: {
    fontSize: '14px',
    color: '#f1f5f9',
    fontWeight: 600,
    marginBottom: 6,
    lineHeight: 1.4,
  },
  timeGain: {
    fontSize: '12px',
    color: '#4ade80',
    fontWeight: 600,
  },
  divider: {
    border: 'none',
    borderTop: '1px solid #1e293b',
    margin: '20px 0',
  },
  reportGrid: {},
  markdown: {
    fontSize: '13px',
    lineHeight: '1.8',
    color: '#94a3b8',
  },
  summaryBar: {
    background: '#060b14',
    border: '1px solid #1e293b',
    borderRadius: '6px',
    padding: '12px 16px',
    marginBottom: '20px',
    fontSize: '13px',
  },
  nextAction: {
    background: 'rgba(30,64,175,0.2)',
    border: '1px solid #1e3a8a',
    borderRadius: '6px',
    padding: '12px 16px',
    marginTop: '20px',
    fontSize: '13px',
    color: '#93c5fd',
  },
  nextLabel: {
    fontSize: '10px',
    color: '#3b82f6',
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    marginBottom: 6,
  },
}

export default function CoachingPanel({ report, session }) {
  return (
    <div style={styles.panel}>
      <div style={styles.label}>AI Race Engineer</div>

      {/* Session summary */}
      <div style={styles.summaryBar}>
        <div style={{ color: '#475569', fontSize: 10, marginBottom: 6 }}>SESSION SUMMARY</div>
        <div style={{ color: '#e2e8f0', fontSize: 14 }}>{report.session_summary}</div>
        {report.reference_note && (
          <div style={{ color: '#64748b', marginTop: 6, fontSize: 12 }}>
            {report.reference_note}
          </div>
        )}
      </div>

      {/* Priority corner cards */}
      <div style={styles.priorityRow}>
        {report.priority_corners?.map(corner => (
          <div key={corner.corner_name} style={styles.priorityCard(corner.rank)}>
            <div style={styles.priorityLabel(corner.rank)}>
              P{corner.rank} · {corner.corner_name.replace(/_/g, ' ')}
            </div>
            <div style={styles.headline}>{corner.headline}</div>
            {corner.estimated_time_gain_ms > 0 && (
              <div style={styles.timeGain}>↑ ~{corner.estimated_time_gain_ms}ms</div>
            )}
          </div>
        ))}
      </div>

      <hr style={styles.divider} />

      {/* Full coaching report */}
      <div style={styles.markdown}>
        <ReactMarkdown skipHtml>{report.full_markdown}</ReactMarkdown>
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
