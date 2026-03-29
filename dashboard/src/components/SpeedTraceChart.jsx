import {
  ComposedChart, Line, XAxis, YAxis, Tooltip,
  ReferenceArea, ResponsiveContainer, Legend,
} from 'recharts'

const CORNER_COLORS = [
  'rgba(245,158,11,0.07)',
  'rgba(59,130,246,0.07)',
  'rgba(168,85,247,0.07)',
  'rgba(34,197,94,0.07)',
  'rgba(239,68,68,0.07)',
]

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  const best = payload.find(p => p.dataKey === 'best_speed_kph')
  const ref  = payload.find(p => p.dataKey === 'ref_speed_kph')
  const delta = best && ref ? best.value - ref.value : null
  return (
    <div style={{
      background: '#1e293b', border: '1px solid #334155',
      borderRadius: '6px', padding: '8px 12px', fontSize: '12px', minWidth: 140,
    }}>
      <div style={{ color: '#64748b', marginBottom: 4 }}>{Math.round(label)}m</div>
      {best && <div style={{ color: '#f59e0b' }}>Best  {best.value.toFixed(1)} kph</div>}
      {ref  && <div style={{ color: '#60a5fa' }}>Ref   {ref.value.toFixed(1)} kph</div>}
      {delta !== null && (
        <div style={{ color: delta >= 0 ? '#4ade80' : '#ef4444', marginTop: 4, fontWeight: 700 }}>
          Δ {delta >= 0 ? '+' : ''}{delta.toFixed(1)} kph
        </div>
      )}
    </div>
  )
}

export default function SpeedTraceChart({ speedTrace, cornerSummary, trackLength }) {
  if (!speedTrace?.samples?.length) return null
  const { samples, best_lap_number, reference_lap_number } = speedTrace
  const effectiveTrackLength = trackLength || samples[samples.length - 1]?.distance_m || 1000

  return (
    <div>
      <div style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
        Speed Trace — Lap {best_lap_number} vs Lap {reference_lap_number}
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={samples} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="distance_m"
            type="number"
            domain={[0, effectiveTrackLength]}
            tickLine={false}
            axisLine={{ stroke: '#1e293b' }}
            tick={{ fill: '#475569', fontSize: 10 }}
            tickFormatter={v => `${Math.round(v)}m`}
            tickCount={8}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            tick={{ fill: '#475569', fontSize: 10 }}
            tickFormatter={v => `${v}`}
            width={36}
            domain={['auto', 'auto']}
          />
          <Tooltip content={<CustomTooltip />} />

          {/* Corner zone shading */}
          {cornerSummary.map((corner, i) => (
            <ReferenceArea
              key={corner.corner_name}
              x1={corner.start_m}
              x2={corner.end_m}
              fill={CORNER_COLORS[i % CORNER_COLORS.length]}
              label={{
                value: corner.corner_name.split('_')[0],
                position: 'insideTop',
                fill: '#334155',
                fontSize: 9,
              }}
            />
          ))}

          <Line
            type="monotone"
            dataKey="best_speed_kph"
            stroke="#f59e0b"
            strokeWidth={1.5}
            dot={false}
            name={`Lap ${best_lap_number} (best)`}
          />
          <Line
            type="monotone"
            dataKey="ref_speed_kph"
            stroke="#60a5fa"
            strokeWidth={1.5}
            strokeDasharray="4 3"
            dot={false}
            name={`Lap ${reference_lap_number} (ref)`}
          />
          <Legend
            wrapperStyle={{ fontSize: 10, color: '#64748b' }}
            iconType="line"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
