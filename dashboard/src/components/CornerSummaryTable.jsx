function DeltaCell({ value, positiveIsGood = true, suffix = '' }) {
  if (value === null || value === undefined) return <td style={tdStyle}>—</td>
  const good = positiveIsGood ? value > 0 : value < 0
  const neutral = value === 0
  const color = neutral ? '#64748b' : good ? '#4ade80' : '#ef4444'
  const prefix = value > 0 ? '+' : ''
  return (
    <td style={{ ...tdStyle, color, fontWeight: neutral ? 400 : 600 }}>
      {prefix}{value}{suffix}
    </td>
  )
}

function TimeLossCell({ value }) {
  if (!value) return <td style={{ ...tdStyle, color: '#64748b' }}>—</td>
  return (
    <td style={{ ...tdStyle, color: '#ef4444', fontWeight: 600 }}>
      +{value}ms
    </td>
  )
}

const tableStyle = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: '12px',
}

const thStyle = {
  padding: '6px 10px',
  textAlign: 'left',
  color: '#475569',
  fontSize: '10px',
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  borderBottom: '1px solid #1e293b',
  fontWeight: 400,
}

const tdStyle = {
  padding: '7px 10px',
  color: '#94a3b8',
  borderBottom: '1px solid #1e293b',
  fontVariantNumeric: 'tabular-nums',
}

const priorityBadge = (priority) => ({
  display: 'inline-block',
  background: priority === 1 ? '#7f1d1d' : priority === 2 ? '#713f12' : '#1e293b',
  color: priority === 1 ? '#fca5a5' : priority === 2 ? '#fde68a' : '#64748b',
  borderRadius: '4px',
  padding: '1px 6px',
  fontSize: '10px',
  fontWeight: 700,
})

export default function CornerSummaryTable({ cornerSummary, selectedCorner, onCornerSelect }) {
  return (
    <div>
      <div style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
        Corner Summary
      </div>
      <table style={tableStyle}>
        <thead>
          <tr>
            <th style={thStyle}>Corner</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Min Speed Δ</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Brake Pt Δ</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Throttle Δ</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Est. Loss</th>
          </tr>
        </thead>
        <tbody>
          {cornerSummary.map(corner => {
            const isSelected = corner.corner_name === selectedCorner
            return (
            <tr
              key={corner.corner_name}
              onClick={() => onCornerSelect?.(isSelected ? null : corner.corner_name)}
              style={{
                background: isSelected ? 'rgba(249,115,22,0.08)' : corner.priority <= 2 ? 'rgba(255,255,255,0.02)' : 'transparent',
                cursor: onCornerSelect ? 'pointer' : 'default',
                outline: isSelected ? '1px solid rgba(249,115,22,0.3)' : 'none',
              }}
            >
              <td style={tdStyle}>
                <span style={priorityBadge(corner.priority)}>P{corner.priority}</span>
                {' '}
                <span style={{ color: isSelected ? '#fed7aa' : '#cbd5e1' }}>{corner.corner_display}</span>
              </td>
              <DeltaCell
                value={corner.delta.min_speed_kph}
                positiveIsGood={true}
                suffix=" kph"
              />
              <DeltaCell
                value={corner.delta.brake_point_m}
                positiveIsGood={true}
                suffix="m"
              />
              <DeltaCell
                value={corner.delta.throttle_pickup_m}
                positiveIsGood={false}
                suffix="m"
              />
              <TimeLossCell value={corner.delta.estimated_time_loss_ms} />
            </tr>
            )
          })}
        </tbody>
      </table>
      <div style={{ marginTop: 8, fontSize: '10px', color: '#334155' }}>
        Δ = best lap vs reference lap · positive min speed = faster · positive brake = later braking · negative throttle = earlier pickup
      </div>
    </div>
  )
}
