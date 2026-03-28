import {
  ComposedChart, Area, XAxis, YAxis, Tooltip,
  ReferenceArea, ResponsiveContainer,
} from 'recharts'

const CORNER_COLORS = [
  'rgba(245,158,11,0.06)',
  'rgba(59,130,246,0.06)',
  'rgba(168,85,247,0.06)',
  'rgba(34,197,94,0.06)',
  'rgba(239,68,68,0.06)',
]

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  const get = key => payload.find(p => p.dataKey === key)?.value ?? null
  return (
    <div style={{
      background: '#1e293b', border: '1px solid #334155',
      borderRadius: '6px', padding: '8px 12px', fontSize: '12px', minWidth: 160,
    }}>
      <div style={{ color: '#64748b', marginBottom: 6 }}>{Math.round(label)}m</div>
      <div style={{ display: 'flex', gap: 16 }}>
        <div>
          <div style={{ color: '#475569', fontSize: 10, marginBottom: 2 }}>BEST</div>
          <div style={{ color: '#4ade80' }}>Thr {(get('best_throttle_pct') ?? 0).toFixed(0)}%</div>
          <div style={{ color: '#ef4444' }}>Brk {(get('best_brake_pct') ?? 0).toFixed(0)}%</div>
        </div>
        <div>
          <div style={{ color: '#475569', fontSize: 10, marginBottom: 2 }}>REF</div>
          <div style={{ color: '#4ade8088' }}>Thr {(get('ref_throttle_pct') ?? 0).toFixed(0)}%</div>
          <div style={{ color: '#ef444488' }}>Brk {(get('ref_brake_pct') ?? 0).toFixed(0)}%</div>
        </div>
      </div>
    </div>
  )
}

export default function InputTraceChart({ inputTrace, cornerSummary }) {
  const { samples, best_lap_number, reference_lap_number } = inputTrace

  return (
    <div>
      <div style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
        Throttle / Brake — Lap {best_lap_number} (solid) vs Lap {reference_lap_number} (faint)
      </div>
      <ResponsiveContainer width="100%" height={160}>
        <ComposedChart data={samples} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="distance_m"
            type="number"
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
            tickFormatter={v => `${v}%`}
            width={36}
            domain={[0, 100]}
          />
          <Tooltip content={<CustomTooltip />} />

          {cornerSummary.map((corner, i) => (
            <ReferenceArea
              key={corner.corner_name}
              x1={corner.start_m}
              x2={corner.end_m}
              fill={CORNER_COLORS[i % CORNER_COLORS.length]}
            />
          ))}

          {/* Reference lap (faint, behind) */}
          <Area type="monotone" dataKey="ref_throttle_pct"
            fill="#4ade8018" stroke="#4ade8040" strokeWidth={1} dot={false} />
          <Area type="monotone" dataKey="ref_brake_pct"
            fill="#ef444418" stroke="#ef444440" strokeWidth={1} dot={false} />

          {/* Best lap (solid, on top) */}
          <Area type="monotone" dataKey="best_throttle_pct"
            fill="#4ade8030" stroke="#4ade80" strokeWidth={1.5} dot={false} />
          <Area type="monotone" dataKey="best_brake_pct"
            fill="#ef444430" stroke="#ef4444" strokeWidth={1.5} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <div style={{ display: 'flex', gap: 16, marginTop: 6 }}>
        {[
          { color: '#4ade80', label: 'Throttle (best)' },
          { color: '#ef4444', label: 'Brake (best)' },
          { color: '#4ade8040', label: 'Throttle (ref)', faint: true },
          { color: '#ef444440', label: 'Brake (ref)', faint: true },
        ].map(({ color, label }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 16, height: 2, background: color, borderRadius: 1 }} />
            <span style={{ fontSize: 10, color: '#475569' }}>{label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
