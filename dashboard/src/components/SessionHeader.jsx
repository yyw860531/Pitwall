const styles = {
  header: {
    background: '#0f172a',
    borderBottom: '1px solid #1e293b',
    padding: '10px 20px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    height: '56px',
  },
  left: { display: 'flex', alignItems: 'center', gap: '20px' },
  title: { fontSize: '16px', fontWeight: 700, color: '#f1f5f9', letterSpacing: '0.05em' },
  sep: { color: '#334155', fontSize: '14px' },
  meta: { fontSize: '12px', color: '#94a3b8' },
  right: { display: 'flex', gap: '24px', alignItems: 'center' },
  stat: { textAlign: 'right' },
  statLabel: { fontSize: '10px', color: '#475569', textTransform: 'uppercase', letterSpacing: '0.08em' },
  statValue: { fontSize: '15px', fontWeight: 700, color: '#f1f5f9', fontVariantNumeric: 'tabular-nums' },
  statSub: { fontSize: '11px', color: '#64748b' },
  badge: {
    background: '#14532d',
    color: '#4ade80',
    borderRadius: '4px',
    padding: '2px 8px',
    fontSize: '11px',
    fontWeight: 600,
  },
}

function fmtMs(ms) {
  if (!ms) return '—'
  const m = Math.floor(ms / 60000)
  const s = ((ms % 60000) / 1000).toFixed(3)
  return `${m}:${s.padStart(6, '0')}`
}

export default function SessionHeader({ session }) {
  return (
    <div style={styles.header}>
      <div style={styles.left}>
        <span style={styles.title}>PitWall</span>
        <span style={styles.sep}>|</span>
        <span style={styles.meta}>{session.car_display}</span>
        <span style={styles.sep}>·</span>
        <span style={styles.meta}>{session.track_display}</span>
        <span style={styles.sep}>·</span>
        <span style={styles.meta}>{session.date}</span>
      </div>
      <div style={styles.right}>
        <div style={styles.stat}>
          <div style={styles.statLabel}>Best Lap</div>
          <div style={styles.statValue}>{fmtMs(session.best_lap_time_ms)}</div>
          <div style={styles.statSub}>Lap {session.best_lap_number}</div>
        </div>
        <div style={styles.stat}>
          <div style={styles.statLabel}>Theoretical Best</div>
          <div style={{ ...styles.statValue, color: '#60a5fa' }}>
            {fmtMs(session.theoretical_best_ms)}
          </div>
          <div style={styles.statSub}>
            {session.theoretical_best_ms
              ? `${fmtMs(session.best_lap_time_ms - session.theoretical_best_ms)} gap`
              : '—'}
          </div>
        </div>
        <div style={styles.stat}>
          <div style={styles.statLabel}>Reference</div>
          <div style={styles.statValue}>Lap {session.reference_lap_number ?? '—'}</div>
          <div style={styles.statSub}>{session.reference_type}</div>
        </div>
        <span style={styles.badge}>{session.driver}</span>
      </div>
    </div>
  )
}
