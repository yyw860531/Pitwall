import { useState, useEffect, useCallback, useMemo } from 'react'
import {
	LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'

const S = {
	panel: {
		background: '#0a0f1a',
		border: '1px solid #1e293b',
		borderRadius: 6,
		padding: '16px',
		marginTop: 1,
	},
	header: {
		display: 'flex',
		alignItems: 'center',
		justifyContent: 'space-between',
		marginBottom: 12,
	},
	title: { fontSize: '13px', color: '#e2e8f0', fontWeight: 600 },
	close: {
		background: 'none', border: 'none', color: '#64748b',
		cursor: 'pointer', fontSize: '16px', lineHeight: 1, padding: '0 4px',
	},
	tip: {
		background: '#1a1f2e',
		border: '1px solid #f97316',
		borderLeft: '3px solid #f97316',
		borderRadius: 4,
		padding: '8px 12px',
		marginBottom: 12,
		fontSize: '12px',
		color: '#fed7aa',
	},
	charts: { display: 'flex', flexDirection: 'column', gap: 12 },
	chartLabel: {
		fontSize: '10px', color: '#64748b',
		textTransform: 'uppercase', letterSpacing: '0.08em',
		marginBottom: 2,
	},
	grid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 },
	racingLineBox: {
		background: '#060b14',
		borderRadius: 4,
		overflow: 'hidden',
		display: 'flex',
		alignItems: 'center',
		justifyContent: 'center',
		minHeight: 160,
	},
	nav: {
		display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12,
	},
	navBtn: {
		background: '#1e293b', border: '1px solid #334155', color: '#94a3b8',
		borderRadius: 4, padding: '3px 10px', cursor: 'pointer', fontSize: '11px',
	},
	navLabel: { fontSize: '12px', color: '#e2e8f0', fontWeight: 600, flex: 1, textAlign: 'center' },
	loading: { fontSize: '12px', color: '#475569', padding: '24px', textAlign: 'center' },
}

// ---- Racing line SVG --------------------------------------------------------

const RL_W = 200
const RL_H = 200
const RL_PAD = 12

function projectRacingLine(samples) {
	const pts = samples.filter(s => s.x_m != null && s.z_m != null)
	if (pts.length < 2) return null
	let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity
	for (const p of pts) {
		if (p.x_m < minX) minX = p.x_m
		if (p.x_m > maxX) maxX = p.x_m
		if (p.z_m < minZ) minZ = p.z_m
		if (p.z_m > maxZ) maxZ = p.z_m
	}
	const rangeX = maxX - minX || 1
	const rangeZ = maxZ - minZ || 1
	const drawW = RL_W - RL_PAD * 2
	const drawH = RL_H - RL_PAD * 2
	const scale = Math.min(drawW / rangeX, drawH / rangeZ)
	const offX = RL_PAD + (drawW - rangeX * scale) / 2
	const offZ = RL_PAD + (drawH - rangeZ * scale) / 2
	return pts.map(p => ({
		sx: offX + (p.x_m - minX) * scale,
		sy: offZ + (p.z_m - minZ) * scale,
	}))
}

function toPolyline(projPts) {
	if (!projPts) return ''
	return projPts.map(p => `${p.sx.toFixed(1)},${p.sy.toFixed(1)}`).join(' ')
}

function RacingLine({ bestSamples, refSamples }) {
	const bestPts = useMemo(() => projectRacingLine(bestSamples), [bestSamples])
	const refPts  = useMemo(() => {
		// Project ref using the same bounds as best for fair comparison
		const allPts = [...bestSamples, ...refSamples].filter(s => s.x_m != null && s.z_m != null)
		if (allPts.length < 2) return null
		let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity
		for (const p of allPts) {
			if (p.x_m < minX) minX = p.x_m
			if (p.x_m > maxX) maxX = p.x_m
			if (p.z_m < minZ) minZ = p.z_m
			if (p.z_m > maxZ) maxZ = p.z_m
		}
		const rangeX = maxX - minX || 1
		const rangeZ = maxZ - minZ || 1
		const drawW = RL_W - RL_PAD * 2
		const drawH = RL_H - RL_PAD * 2
		const scale = Math.min(drawW / rangeX, drawH / rangeZ)
		const offX = RL_PAD + (drawW - rangeX * scale) / 2
		const offZ = RL_PAD + (drawH - rangeZ * scale) / 2
		return refSamples
			.filter(s => s.x_m != null && s.z_m != null)
			.map(p => ({
				sx: offX + (p.x_m - minX) * scale,
				sy: offZ + (p.z_m - minZ) * scale,
			}))
	}, [bestSamples, refSamples])

	const hasData = bestPts && bestPts.length > 1

	return (
		<div style={S.racingLineBox}>
			{!hasData ? (
				<span style={{ fontSize: '11px', color: '#334155' }}>
					No position data — re-ingest session
				</span>
			) : (
				<svg width={RL_W} height={RL_H} viewBox={`0 0 ${RL_W} ${RL_H}`}>
					{/* Reference line (blue) */}
					{refPts && refPts.length > 1 && (
						<polyline
							points={toPolyline(refPts)}
							fill="none" stroke="#60a5fa" strokeWidth="3"
							strokeLinecap="round" strokeLinejoin="round" opacity="0.7"
						/>
					)}
					{/* Best lap line (orange) */}
					<polyline
						points={toPolyline(bestPts)}
						fill="none" stroke="#f97316" strokeWidth="3"
						strokeLinecap="round" strokeLinejoin="round"
					/>
					{/* Start dot */}
					{bestPts[0] && (
						<circle cx={bestPts[0].sx} cy={bestPts[0].sy} r={3} fill="#4ade80" />
					)}
				</svg>
			)}
		</div>
	)
}

// ---- Trace chart ------------------------------------------------------------

function TraceChart({ data, dataKeyA, dataKeyB, labelA, labelB, colorA, colorB, unit, height = 90 }) {
	return (
		<ResponsiveContainer width="100%" height={height}>
			<LineChart data={data} margin={{ top: 2, right: 4, bottom: 0, left: -20 }}>
				<XAxis
					dataKey="distance_m"
					tick={{ fontSize: 9, fill: '#475569' }}
					tickFormatter={v => `${v}m`}
					interval="preserveStartEnd"
				/>
				<YAxis tick={{ fontSize: 9, fill: '#475569' }} />
				<Tooltip
					contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: 10 }}
					formatter={(v, name) => [`${v.toFixed(1)}${unit}`, name]}
					labelFormatter={v => `${v}m`}
				/>
				<Line
					type="monotone" dataKey={dataKeyA} name={labelA}
					stroke={colorA} dot={false} strokeWidth={1.5} isAnimationActive={false}
				/>
				{dataKeyB && (
					<Line
						type="monotone" dataKey={dataKeyB} name={labelB}
						stroke={colorB} dot={false} strokeWidth={1.5}
						strokeDasharray="4 2" isAnimationActive={false}
					/>
				)}
			</LineChart>
		</ResponsiveContainer>
	)
}

// ---- Diff to Ref chart ------------------------------------------------------

function DiffChart({ bestSamples, refSamples, height = 70 }) {
	const data = useMemo(() => {
		// Interpolate ref onto best lap distance grid and compute cumulative delta
		if (!bestSamples.length || !refSamples.length) return []
		const refMap = {}
		for (const s of refSamples) refMap[s.distance_m] = s.speed_kph

		// Build cumulative time diff: integrate speed difference
		let cumDiff = 0
		const out = []
		for (let i = 0; i < bestSamples.length; i++) {
			const b = bestSamples[i]
			// Find nearest ref sample
			const rSpeed = refSamples.reduce((best, r) =>
				Math.abs(r.distance_m - b.distance_m) < Math.abs(best.distance_m - b.distance_m) ? r : best
			).speed_kph || b.speed_kph
			// dt ≈ ds / v_avg (in seconds)
			if (i > 0) {
				const ds = b.distance_m - bestSamples[i - 1].distance_m
				const vBest = (b.speed_kph || 1) / 3.6
				const vRef  = (rSpeed || 1) / 3.6
				cumDiff += ds / vRef - ds / vBest
			}
			out.push({ distance_m: b.distance_m, diff_s: parseFloat(cumDiff.toFixed(3)) })
		}
		return out
	}, [bestSamples, refSamples])

	return (
		<ResponsiveContainer width="100%" height={height}>
			<LineChart data={data} margin={{ top: 2, right: 4, bottom: 0, left: -20 }}>
				<XAxis dataKey="distance_m" tick={{ fontSize: 9, fill: '#475569' }} tickFormatter={v => `${v}m`} interval="preserveStartEnd" />
				<YAxis tick={{ fontSize: 9, fill: '#475569' }} />
				<ReferenceLine y={0} stroke="#334155" strokeDasharray="2 2" />
				<Tooltip
					contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: 10 }}
					formatter={(v) => [`${v > 0 ? '+' : ''}${v.toFixed(3)}s`, 'Δ time']}
					labelFormatter={v => `${v}m`}
				/>
				<Line
					type="monotone" dataKey="diff_s" name="Δ time"
					stroke="#f97316" dot={false} strokeWidth={1.5} isAnimationActive={false}
				/>
			</LineChart>
		</ResponsiveContainer>
	)
}

// ---- Main component ---------------------------------------------------------

export default function CornerDrilldown({ sessionId, cornerName, cornerSummary, onClose, onNavigate }) {
	const [traceData, setTraceData] = useState(null)
	const [loading, setLoading]     = useState(false)

	const fetchTrace = useCallback((sid, name) => {
		if (!sid || !name) return
		setLoading(true)
		setTraceData(null)
		fetch(`/api/corner_trace/${sid}/${encodeURIComponent(name)}`)
			.then(r => r.json())
			.then(d => { setTraceData(d); setLoading(false) })
			.catch(() => setLoading(false))
	}, [])

	useEffect(() => {
		fetchTrace(sessionId, cornerName)
	}, [sessionId, cornerName, fetchTrace])

	// Sorted corner names for prev/next navigation
	const sortedCorners = useMemo(
		() => cornerSummary ? [...cornerSummary].sort((a, b) => a.apex_m - b.apex_m) : [],
		[cornerSummary]
	)
	const currentIdx = sortedCorners.findIndex(c => c.corner_name === cornerName)

	if (!cornerName) return null

	const corner = cornerSummary?.find(c => c.corner_name === cornerName)
	const timeLossMs = corner?.delta?.estimated_time_loss_ms
	const timeLossStr = timeLossMs != null
		? (timeLossMs > 0 ? `+${(timeLossMs / 1000).toFixed(3)}s` : `${(timeLossMs / 1000).toFixed(3)}s`)
		: null

	const bestSamples = traceData?.best_lap?.samples || []
	const refSamples  = traceData?.ref_lap?.samples  || []

	// Build merged data for speed/inputs charts
	const mergedData = useMemo(() => {
		if (!bestSamples.length) return []
		// Index ref by nearest distance
		return bestSamples.map(b => {
			const r = refSamples.length
				? refSamples.reduce((best, s) =>
					Math.abs(s.distance_m - b.distance_m) < Math.abs(best.distance_m - b.distance_m) ? s : best
				)
				: {}
			return {
				distance_m:    b.distance_m,
				best_speed:    b.speed_kph,
				ref_speed:     r.speed_kph ?? null,
				best_throttle: b.throttle_pct,
				ref_throttle:  r.throttle_pct ?? null,
				best_brake:    b.brake_pct,
				ref_brake:     r.brake_pct ?? null,
			}
		})
	}, [bestSamples, refSamples])

	const refLapLabel = traceData?.ref_lap?.lap_number != null
		? `Lap ${traceData.ref_lap.lap_number}`
		: 'Ref'
	const bestLapLabel = traceData?.best_lap?.lap_number != null
		? `Lap ${traceData.best_lap.lap_number}`
		: 'Best'

	return (
		<div style={S.panel}>
			{/* Header */}
			<div style={S.header}>
				<div>
					<span style={S.title}>
						{corner?.corner_display || cornerName}
					</span>
					{timeLossStr && (
						<span style={{
							marginLeft: 8, fontSize: '11px', fontFamily: 'monospace',
							color: timeLossMs > 0 ? '#ef4444' : '#4ade80',
						}}>
							{timeLossStr}
						</span>
					)}
				</div>
				<button style={S.close} onClick={onClose}>✕</button>
			</div>

			{/* Prev / Next navigation */}
			{sortedCorners.length > 1 && (
				<div style={S.nav}>
					<button
						style={S.navBtn}
						disabled={currentIdx <= 0}
						onClick={() => currentIdx > 0 && onNavigate(sortedCorners[currentIdx - 1].corner_name)}
					>← Prev</button>
					<span style={S.navLabel}>
						Corner {currentIdx + 1} / {sortedCorners.length}
					</span>
					<button
						style={S.navBtn}
						disabled={currentIdx >= sortedCorners.length - 1}
						onClick={() => currentIdx < sortedCorners.length - 1 && onNavigate(sortedCorners[currentIdx + 1].corner_name)}
					>Next →</button>
				</div>
			)}

			{/* Coaching tip */}
			{traceData?.coaching_tip && (
				<div style={S.tip}>
					⚑ {traceData.coaching_tip}
				</div>
			)}

			{loading && <div style={S.loading}>Loading corner data…</div>}

			{!loading && traceData && (
				<div style={S.charts}>
					<div style={S.grid}>
						{/* Racing line */}
						<div>
							<div style={S.chartLabel}>Racing Line</div>
							<RacingLine bestSamples={bestSamples} refSamples={refSamples} />
							<div style={{ fontSize: '10px', color: '#475569', marginTop: 4, display: 'flex', gap: 10 }}>
								<span style={{ color: '#f97316' }}>── {bestLapLabel}</span>
								<span style={{ color: '#60a5fa' }}>── {refLapLabel}</span>
								<span style={{ color: '#4ade80' }}>● entry</span>
							</div>
						</div>

						{/* Diff to ref */}
						<div>
							<div style={S.chartLabel}>Δ Time vs Ref</div>
							<DiffChart bestSamples={bestSamples} refSamples={refSamples} height={160} />
						</div>
					</div>

					{/* Speed */}
					<div>
						<div style={S.chartLabel}>Speed — {bestLapLabel} vs {refLapLabel}</div>
						<TraceChart
							data={mergedData}
							dataKeyA="best_speed" dataKeyB="ref_speed"
							labelA={bestLapLabel} labelB={refLapLabel}
							colorA="#f97316" colorB="#60a5fa"
							unit=" kph" height={100}
						/>
					</div>

					{/* Throttle + Brake */}
					<div style={S.grid}>
						<div>
							<div style={S.chartLabel}>Throttle %</div>
							<TraceChart
								data={mergedData}
								dataKeyA="best_throttle" dataKeyB="ref_throttle"
								labelA={bestLapLabel} labelB={refLapLabel}
								colorA="#4ade80" colorB="#60a5fa"
								unit="%" height={90}
							/>
						</div>
						<div>
							<div style={S.chartLabel}>Brake %</div>
							<TraceChart
								data={mergedData}
								dataKeyA="best_brake" dataKeyB="ref_brake"
								labelA={bestLapLabel} labelB={refLapLabel}
								colorA="#f87171" colorB="#60a5fa"
								unit="%" height={90}
							/>
						</div>
					</div>
				</div>
			)}
		</div>
	)
}
