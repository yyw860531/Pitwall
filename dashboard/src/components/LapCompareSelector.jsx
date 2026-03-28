function fmtMs(ms) {
  if (!ms) return '—'
  const m = Math.floor(ms / 60000)
  const s = ((ms % 60000) / 1000).toFixed(3)
  return `${m}:${s.padStart(6, '0')}`
}

const styles = {
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    padding: '8px 16px',
    background: '#0f172a',
    borderBottom: '1px solid #1e293b',
    flexWrap: 'wrap',
  },
  label: { fontSize: '11px', color: '#475569', textTransform: 'uppercase', letterSpacing: '0.08em' },
  select: {
    background: '#1e293b',
    color: '#e2e8f0',
    border: '1px solid #334155',
    borderRadius: '4px',
    padding: '3px 8px',
    fontSize: '12px',
    fontFamily: 'monospace',
    cursor: 'pointer',
  },
  vs: { fontSize: '11px', color: '#334155' },
  badge: (color) => ({
    display: 'inline-block',
    width: 10, height: 10,
    borderRadius: '50%',
    background: color,
    marginRight: 4,
  }),
  hint: { fontSize: '10px', color: '#334155', marginLeft: 'auto' },
}

export default function LapCompareSelector({
  laps,
  allLapTraces,
  theoreticalBestTrace,
  targetLapNum,
  refLapNum,
  onTargetChange,
  onRefChange,
}) {
  if (!allLapTraces) return null

  const validLaps = laps.filter(l => l.is_valid && l.lap_time_ms)

  const specialOptions = [
    theoreticalBestTrace && {
      value: '__theoretical__',
      label: `Theoretical best — ${fmtMs(theoreticalBestTrace.lap_time_ms)} (S1 L${theoreticalBestTrace.best_s1_lap_number} + S2 L${theoreticalBestTrace.best_s2_lap_number})`,
    },
  ].filter(Boolean)

  const lapOptions = validLaps.map(l => ({
    value: String(l.lap_number),
    label: `Lap ${l.lap_number} — ${fmtMs(l.lap_time_ms)}${l.is_best ? ' ★ best' : ''}`,
  }))

  return (
    <div style={styles.row}>
      <span style={styles.label}>Comparing</span>

      <span style={styles.badge('#f59e0b')} />
      <select
        style={styles.select}
        value={targetLapNum}
        onChange={e => onTargetChange(e.target.value)}
      >
        {lapOptions.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>

      <span style={styles.vs}>vs</span>

      <span style={styles.badge('#60a5fa')} />
      <select
        style={styles.select}
        value={refLapNum}
        onChange={e => onRefChange(e.target.value)}
      >
        {specialOptions.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
        {lapOptions.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>

      <span style={styles.hint}>No AI needed — switch any two laps to compare</span>
    </div>
  )
}
