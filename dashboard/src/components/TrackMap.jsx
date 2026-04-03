import { useMemo } from 'react'

const SVG_W = 480
const SVG_H = 300
const PADDING = 28  // room for corner bubble labels at edges

// Project world XZ points into SVG space, preserving aspect ratio
function projectPoints(pts) {
	if (!pts || pts.length === 0) return []

	let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity
	for (const p of pts) {
		if (p.x < minX) minX = p.x
		if (p.x > maxX) maxX = p.x
		if (p.z < minZ) minZ = p.z
		if (p.z > maxZ) maxZ = p.z
	}

	const rangeX = maxX - minX || 1
	const rangeZ = maxZ - minZ || 1
	const drawW = SVG_W - PADDING * 2
	const drawH = SVG_H - PADDING * 2
	const scale = Math.min(drawW / rangeX, drawH / rangeZ)
	const offX = PADDING + (drawW - rangeX * scale) / 2
	const offZ = PADDING + (drawH - rangeZ * scale) / 2

	return {
		project: (x, z) => ({
			sx: offX + (x - minX) * scale,
			sy: offZ + (z - minZ) * scale,
		}),
	}
}

function deltaColor(ms) {
	if (ms === null || ms === undefined) return '#64748b'
	// positive ms = time lost (bad), negative = time gained (good)
	if (ms <= 0) return '#4ade80'
	if (ms < 200) return '#facc15'
	return '#ef4444'
}

function formatDelta(ms) {
	if (ms === null || ms === undefined) return '—'
	const sign = ms > 0 ? '+' : ''
	return `${sign}${(ms / 1000).toFixed(3)}s`
}

export default function TrackMap({ trackPath, cornerSummary, selectedCorner, onCornerSelect }) {
	const proj = useMemo(() => {
		if (!trackPath || trackPath.length === 0) return null
		return projectPoints(trackPath)
	}, [trackPath])

	// Project corner apex positions
	const cornerPositions = useMemo(() => {
		if (!proj || !cornerSummary) return []
		return cornerSummary
			.filter(c => c.apex_x != null && c.apex_z != null)
			.map(c => ({
				...c,
				...proj.project(c.apex_x, c.apex_z),
			}))
	}, [proj, cornerSummary])

	// Build SVG polyline string from track path
	const polyline = useMemo(() => {
		if (!proj || !trackPath) return ''
		return trackPath
			.map(p => {
				const { sx, sy } = proj.project(p.x, p.z)
				return `${sx.toFixed(1)},${sy.toFixed(1)}`
			})
			.join(' ')
	}, [proj, trackPath])

	// Fallback: no track path data
	if (!trackPath || trackPath.length === 0) {
		return (
			<div style={{ fontSize: '11px', color: '#334155', padding: '12px 0' }}>
				Track map unavailable — re-ingest session to generate path data.
			</div>
		)
	}

	return (
		<div>
			<div style={{
				fontSize: '11px', color: '#64748b',
				textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8,
			}}>
				Track Map
			</div>
			<svg
				width={SVG_W}
				height={SVG_H}
				style={{ display: 'block', background: '#060b14', borderRadius: 4, maxWidth: '100%' }}
				viewBox={`0 0 ${SVG_W} ${SVG_H}`}
			>
				{/* Track outline */}
				<polyline
					points={polyline}
					fill="none"
					stroke="#1e3a5f"
					strokeWidth="8"
					strokeLinecap="round"
					strokeLinejoin="round"
				/>
				<polyline
					points={polyline}
					fill="none"
					stroke="#334155"
					strokeWidth="4"
					strokeLinecap="round"
					strokeLinejoin="round"
				/>

				{/* Highlight selected corner segment */}
				{selectedCorner && (() => {
					const sel = cornerSummary?.find(c => c.corner_name === selectedCorner)
					if (!sel || sel.apex_x == null) return null
					const { sx, sy } = proj.project(sel.apex_x, sel.apex_z)
					return (
						<circle
							cx={sx} cy={sy} r={14}
							fill="none"
							stroke="#f97316"
							strokeWidth="2"
							opacity={0.6}
						/>
					)
				})()}

				{/* Corner bubbles */}
				{cornerPositions.map((c, i) => {
					const isSelected = c.corner_name === selectedCorner
					const ms = c.delta?.estimated_time_loss_ms
					const color = deltaColor(ms)
					const label = formatDelta(ms)
					// Keep bubble inside SVG bounds
					const bx = Math.max(18, Math.min(SVG_W - 18, c.sx))
					const by = Math.max(18, Math.min(SVG_H - 18, c.sy))
					return (
						<g
							key={c.corner_name}
							style={{ cursor: 'pointer' }}
							onClick={() => onCornerSelect(isSelected ? null : c.corner_name)}
						>
							{/* Connector line from track point to bubble (if offset) */}
							{(Math.abs(bx - c.sx) > 2 || Math.abs(by - c.sy) > 2) && (
								<line x1={c.sx} y1={c.sy} x2={bx} y2={by}
									stroke={color} strokeWidth="1" opacity="0.4" />
							)}
							{/* Bubble background */}
							<circle
								cx={bx} cy={by} r={isSelected ? 13 : 11}
								fill={isSelected ? color : '#0f172a'}
								stroke={color}
								strokeWidth={isSelected ? 2 : 1.5}
							/>
							{/* Corner number */}
							<text
								x={bx} y={by + 1}
								textAnchor="middle" dominantBaseline="middle"
								fill={isSelected ? '#0f172a' : color}
								fontSize="8"
								fontWeight="700"
								fontFamily="monospace"
							>
								{i + 1}
							</text>
							{/* Delta label below bubble */}
							<text
								x={bx} y={by + 17}
								textAnchor="middle" dominantBaseline="middle"
								fill={color}
								fontSize="7"
								fontFamily="monospace"
							>
								{label}
							</text>
						</g>
					)
				})}
			</svg>

			{/* Legend */}
			<div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: '10px', color: '#475569' }}>
				<span style={{ color: '#4ade80' }}>● gain</span>
				<span style={{ color: '#facc15' }}>● small loss</span>
				<span style={{ color: '#ef4444' }}>● loss &gt;0.2s</span>
				<span style={{ color: '#64748b' }}>click corner to drill down</span>
			</div>
		</div>
	)
}
