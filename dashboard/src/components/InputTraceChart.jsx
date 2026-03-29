import { useState } from 'react'
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

// ---------------------------------------------------------------------------
// Toggle controls
// ---------------------------------------------------------------------------

function RadioGroup({ options, value, onChange }) {
  return (
    <div style={{ display: 'flex', gap: 2 }}>
      {options.map(opt => {
        const active = value === opt.value
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            style={{
              padding: '2px 9px',
              fontSize: 10,
              border: '1px solid',
              borderRadius: 3,
              cursor: 'pointer',
              fontFamily: 'monospace',
              transition: 'all 0.1s',
              borderColor: active ? '#3b82f6' : '#334155',
              background:  active ? '#1e3a5f' : 'transparent',
              color:       active ? '#93c5fd' : '#475569',
            }}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}

function ToggleChip({ label, active, color, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '2px 9px',
        fontSize: 10,
        border: '1px solid',
        borderRadius: 3,
        cursor: 'pointer',
        fontFamily: 'monospace',
        transition: 'all 0.1s',
        borderColor: active ? color : '#334155',
        background:  active ? `${color}22` : 'transparent',
        color:       active ? color : '#475569',
        textDecoration: active ? 'none' : 'line-through',
      }}
    >
      {label}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

function CustomTooltip({ active, payload, label, showThrottle, showBrake, showBest, showRef }) {
  if (!active || !payload?.length) return null
  const get = key => payload.find(p => p.dataKey === key)?.value ?? null
  return (
    <div style={{
      background: '#1e293b', border: '1px solid #334155',
      borderRadius: '6px', padding: '8px 12px', fontSize: '12px', minWidth: 150,
    }}>
      <div style={{ color: '#64748b', marginBottom: 6 }}>{Math.round(label)}m</div>
      <div style={{ display: 'flex', gap: 16 }}>
        {showBest && (
          <div>
            <div style={{ color: '#475569', fontSize: 10, marginBottom: 2 }}>BEST</div>
            {showThrottle && <div style={{ color: '#4ade80' }}>Thr {(get('best_throttle_pct') ?? 0).toFixed(0)}%</div>}
            {showBrake    && <div style={{ color: '#ef4444' }}>Brk {(get('best_brake_pct')    ?? 0).toFixed(0)}%</div>}
          </div>
        )}
        {showRef && (
          <div>
            <div style={{ color: '#475569', fontSize: 10, marginBottom: 2 }}>REF</div>
            {showThrottle && <div style={{ color: '#4ade80cc' }}>Thr {(get('ref_throttle_pct') ?? 0).toFixed(0)}%</div>}
            {showBrake    && <div style={{ color: '#ef4444cc' }}>Brk {(get('ref_brake_pct')    ?? 0).toFixed(0)}%</div>}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Dashed legend swatch
// ---------------------------------------------------------------------------

function LegendSwatch({ color, dashed }) {
  if (dashed) {
    return (
      <svg width={18} height={4} style={{ flexShrink: 0 }}>
        <line x1={0} y1={2} x2={18} y2={2}
          stroke={color} strokeWidth={1.5} strokeDasharray="4 3" />
      </svg>
    )
  }
  return <div style={{ width: 16, height: 2, background: color, borderRadius: 1, flexShrink: 0 }} />
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function InputTraceChart({ inputTrace, cornerSummary }) {
  if (!inputTrace?.samples?.length) return null
  const { samples, best_lap_number, reference_lap_number } = inputTrace

  // Channel filter: 'both' | 'throttle' | 'brake'
  const [channel,  setChannel]  = useState('both')
  // Lap visibility toggles
  const [showBest, setShowBest] = useState(true)
  const [showRef,  setShowRef]  = useState(true)

  const showThrottle = channel !== 'brake'
  const showBrake    = channel !== 'throttle'

  return (
    <div>
      {/* Header row: title + controls */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 10, flexWrap: 'wrap', gap: 8,
      }}>
        <div style={{
          fontSize: '11px', color: '#64748b',
          textTransform: 'uppercase', letterSpacing: '0.08em',
        }}>
          Throttle / Brake
        </div>

        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          {/* Channel radio */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ fontSize: 10, color: '#475569' }}>Show</span>
            <RadioGroup
              options={[
                { value: 'both',     label: 'Both'     },
                { value: 'throttle', label: 'Throttle' },
                { value: 'brake',    label: 'Brake'    },
              ]}
              value={channel}
              onChange={setChannel}
            />
          </div>

          {/* Divider */}
          <div style={{ width: 1, height: 14, background: '#1e293b' }} />

          {/* Lap toggles */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ fontSize: 10, color: '#475569' }}>Lap</span>
            <ToggleChip
              label={`L${best_lap_number} best`}
              active={showBest}
              color="#60a5fa"
              onClick={() => setShowBest(v => !v)}
            />
            <ToggleChip
              label={`L${reference_lap_number} ref`}
              active={showRef}
              color="#94a3b8"
              onClick={() => setShowRef(v => !v)}
            />
          </div>
        </div>
      </div>

      {/* Chart */}
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
          <Tooltip content={
            <CustomTooltip
              showThrottle={showThrottle}
              showBrake={showBrake}
              showBest={showBest}
              showRef={showRef}
            />
          } />

          {cornerSummary.map((corner, i) => (
            <ReferenceArea
              key={corner.corner_name}
              x1={corner.start_m}
              x2={corner.end_m}
              fill={CORNER_COLORS[i % CORNER_COLORS.length]}
            />
          ))}

          {/* Reference lap — dashed, drawn first so best lap sits on top */}
          {showRef && showThrottle && (
            <Area type="monotone" dataKey="ref_throttle_pct"
              fill="#4ade8010" stroke="#4ade8099" strokeWidth={1.5}
              strokeDasharray="5 3" dot={false} />
          )}
          {showRef && showBrake && (
            <Area type="monotone" dataKey="ref_brake_pct"
              fill="#ef444410" stroke="#ef444499" strokeWidth={1.5}
              strokeDasharray="5 3" dot={false} />
          )}

          {/* Best lap — solid, on top */}
          {showBest && showThrottle && (
            <Area type="monotone" dataKey="best_throttle_pct"
              fill="#4ade8028" stroke="#4ade80" strokeWidth={2} dot={false} />
          )}
          {showBest && showBrake && (
            <Area type="monotone" dataKey="best_brake_pct"
              fill="#ef444428" stroke="#ef4444" strokeWidth={2} dot={false} />
          )}
        </ComposedChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 14, marginTop: 7, flexWrap: 'wrap' }}>
        {showBest && showThrottle && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <LegendSwatch color="#4ade80" />
            <span style={{ fontSize: 10, color: '#475569' }}>Throttle L{best_lap_number}</span>
          </div>
        )}
        {showBest && showBrake && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <LegendSwatch color="#ef4444" />
            <span style={{ fontSize: 10, color: '#475569' }}>Brake L{best_lap_number}</span>
          </div>
        )}
        {showRef && showThrottle && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <LegendSwatch color="#4ade8099" dashed />
            <span style={{ fontSize: 10, color: '#475569' }}>Throttle L{reference_lap_number} ref</span>
          </div>
        )}
        {showRef && showBrake && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <LegendSwatch color="#ef444499" dashed />
            <span style={{ fontSize: 10, color: '#475569' }}>Brake L{reference_lap_number} ref</span>
          </div>
        )}
      </div>
    </div>
  )
}
