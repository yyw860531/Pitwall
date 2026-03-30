import { BarChart, Bar, XAxis, YAxis, Tooltip, Cell, ReferenceLine, ResponsiveContainer } from 'recharts'

const COLORS = {
  best:      '#f59e0b',
  reference: '#3b82f6',
  valid:     '#334155',
  invalid:   '#1e293b',
}

function fmtMs(ms) {
  if (!ms) return '—'
  const m = Math.floor(ms / 60000)
  const s = ((ms % 60000) / 1000).toFixed(3)
  return `${m}:${s.padStart(6, '0')}`
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div style={{
      background: '#1e293b', border: '1px solid #334155',
      borderRadius: '6px', padding: '8px 12px', fontSize: '12px',
    }}>
      <div style={{ color: '#94a3b8', marginBottom: 4 }}>Lap {d.lap_number}</div>
      <div style={{ color: '#f1f5f9', fontWeight: 700 }}>{fmtMs(d.lap_time_ms)}</div>
      {d.sectors.s1_ms && (
        <div style={{ color: '#64748b', marginTop: 4 }}>
          S1 {fmtMs(d.sectors.s1_ms)} · S2 {fmtMs(d.sectors.s2_ms)}
          {d.sectors.s3_ms ? ` · S3 ${fmtMs(d.sectors.s3_ms)}` : ''}
        </div>
      )}
      {!d.is_valid && <div style={{ color: '#ef4444', marginTop: 4 }}>INVALID</div>}
      {d.is_best && <div style={{ color: '#f59e0b', marginTop: 4 }}>BEST</div>}
      {d.is_reference && <div style={{ color: '#3b82f6', marginTop: 4 }}>REFERENCE</div>}
    </div>
  )
}

export default function LapTimeBarChart({ laps, session }) {
  const validTimes = laps.filter(l => l.is_valid).map(l => l.lap_time_ms)
  const fastestValid = validTimes.length ? Math.min(...validTimes) : null

  // Filter: show laps within 150% of fastest valid time (hides out laps / cooldowns)
  const cutoff = fastestValid ? fastestValid * 1.5 : Infinity
  const chartData = laps.filter(l => l.lap_time_ms > 5000 && l.lap_time_ms <= cutoff)

  // Tight Y-axis around valid laps only
  const shownValid = chartData.filter(l => l.is_valid).map(l => l.lap_time_ms)
  const yMin = shownValid.length ? Math.min(...shownValid) - 2000 : 0
  const yMax = shownValid.length ? Math.max(...shownValid) + 2000 : 100000

  return (
    <div>
      <div style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
        Session — Lap Times
      </div>
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="lap_number"
            tickLine={false}
            axisLine={false}
            tick={{ fill: '#475569', fontSize: 11 }}
            tickFormatter={v => `L${v}`}
          />
          <YAxis
            domain={[yMin, yMax]}
            tickLine={false}
            axisLine={false}
            tick={{ fill: '#475569', fontSize: 10 }}
            tickFormatter={fmtMs}
            width={52}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          {session.theoretical_best_ms && (
            <ReferenceLine
              y={session.theoretical_best_ms}
              stroke="#60a5fa"
              strokeDasharray="4 3"
              strokeWidth={1}
            />
          )}
          <Bar dataKey="lap_time_ms" radius={[2, 2, 0, 0]} maxBarSize={32}>
            {chartData.map((lap) => {
              let fill = COLORS.invalid
              if (!lap.is_valid)   fill = COLORS.invalid
              else if (lap.is_best) fill = COLORS.best
              else if (lap.is_reference) fill = COLORS.reference
              else fill = COLORS.valid
              return <Cell key={lap.lap_number} fill={fill} />
            })}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div style={{ display: 'flex', gap: 16, marginTop: 6 }}>
        {[
          { color: COLORS.best,      label: 'Best' },
          { color: COLORS.reference, label: 'Reference' },
          { color: COLORS.valid,     label: 'Valid' },
          { color: COLORS.invalid,   label: 'Invalid' },
          { color: '#60a5fa',        label: 'Theoretical best', dashed: true },
        ].map(({ color, label, dashed }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{
              width: dashed ? 16 : 8, height: dashed ? 2 : 8,
              background: color,
              borderRadius: dashed ? 0 : 2,
              borderTop: dashed ? `2px dashed ${color}` : 'none',
              opacity: 0.9,
            }} />
            <span style={{ fontSize: 10, color: '#475569' }}>{label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
