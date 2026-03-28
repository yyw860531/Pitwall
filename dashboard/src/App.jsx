import { useState, useEffect, useMemo } from 'react'
import SessionHeader from './components/SessionHeader.jsx'
import LapTimeBarChart from './components/LapTimeBarChart.jsx'
import SpeedTraceChart from './components/SpeedTraceChart.jsx'
import InputTraceChart from './components/InputTraceChart.jsx'
import CornerSummaryTable from './components/CornerSummaryTable.jsx'
import CoachingPanel from './components/CoachingPanel.jsx'
import TrackMap from './components/TrackMap.jsx'
import LapCompareSelector from './components/LapCompareSelector.jsx'

const S = {
  app:    { minHeight: '100vh', background: '#0a0a0f', color: '#e2e8f0' },
  load:   { display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', fontSize: '14px', color: '#64748b', fontFamily: 'monospace' },
  err:    { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100vh', gap: '12px', color: '#ef4444', fontFamily: 'monospace' },
  importBar: { background: '#0f172a', borderBottom: '1px solid #1e293b', padding: '6px 16px', display: 'flex', alignItems: 'center', gap: '12px' },
  importBtn: { background: '#1e40af', color: '#e2e8f0', border: 'none', borderRadius: '4px', padding: '4px 12px', cursor: 'pointer', fontSize: '12px', fontFamily: 'monospace' },
  importStatus: { fontSize: '11px', color: '#64748b' },
  // Main layout: charts (left, 60%) + coaching (right, 40%)
  grid:   { display: 'grid', gridTemplateColumns: '1fr 420px', gap: '1px', background: '#1e293b', minHeight: 'calc(100vh - 88px)' },
  left:   { background: '#0a0a0f', display: 'flex', flexDirection: 'column', gap: '1px' },
  right:  { background: '#0f172a', borderLeft: '1px solid #1e293b', position: 'sticky', top: 88, height: 'calc(100vh - 88px)', overflowY: 'auto' },
  // Top row inside left: lap bar chart + track map side by side
  topRow: { display: 'grid', gridTemplateColumns: '1fr 200px', gap: '1px', background: '#1e293b' },
  panel:  { background: '#0f172a', padding: '16px' },
}

// Build a merged speed/input trace from two individual lap traces
function mergeTraces(targetTrace, refTrace) {
  if (!targetTrace || !refTrace) return null
  const tMap = {}
  targetTrace.speed_trace.forEach(p => { tMap[p.distance_m] = p.speed_kph })
  const tInputMap = {}
  targetTrace.input_trace.forEach(p => { tInputMap[p.distance_m] = p })

  // Align on target lap distance grid
  return {
    speed_trace: {
      best_lap_number:      targetTrace.lap_number || '?',
      reference_lap_number: refTrace.best_s1_lap_number
        ? `T.Best (S1:L${refTrace.best_s1_lap_number}/S2:L${refTrace.best_s2_lap_number})`
        : (refTrace.lap_number || '?'),
      samples: targetTrace.speed_trace.map((tp, i) => {
        const rp = refTrace.speed_trace[i] || {}
        return {
          distance_m:      tp.distance_m,
          best_speed_kph:  tp.speed_kph,
          ref_speed_kph:   rp.speed_kph ?? tp.speed_kph,
          delta_kph:       rp.speed_kph != null ? +(tp.speed_kph - rp.speed_kph).toFixed(2) : 0,
        }
      }),
    },
    input_trace: {
      best_lap_number:      targetTrace.lap_number || '?',
      reference_lap_number: refTrace.lap_number || '?',
      samples: targetTrace.input_trace.map((tp, i) => {
        const rp = refTrace.input_trace[i] || {}
        return {
          distance_m:        tp.distance_m,
          best_throttle_pct: tp.throttle_pct,
          best_brake_pct:    tp.brake_pct,
          ref_throttle_pct:  rp.throttle_pct ?? tp.throttle_pct,
          ref_brake_pct:     rp.brake_pct ?? tp.brake_pct,
        }
      }),
    },
  }
}

export default function App() {
  const [data, setData]               = useState(null)
  const [loading, setLoading]         = useState(true)
  const [error, setError]             = useState(null)
  const [importStatus, setImportStatus] = useState('')
  const [targetLapNum, setTargetLapNum] = useState(null)
  const [refLapNum, setRefLapNum]     = useState(null)

  const loadData = () => {
    setLoading(true)
    fetch('/dashboard.json')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(d => {
        setData(d)
        setLoading(false)
        // Default: best lap vs theoretical best (or existing reference)
        const bestLap = d.laps.find(l => l.is_best)
        setTargetLapNum(bestLap ? String(bestLap.lap_number) : null)
        setRefLapNum('__theoretical__')
      })
      .catch(e => { setError(e.message); setLoading(false) })
  }

  useEffect(() => { loadData() }, [])

  const handleImport = () => {
    setImportStatus('Scanning…')
    fetch('/api/scan', { method: 'POST' })
      .then(r => r.json())
      .then(result => {
        if (result.new_sessions > 0) {
          setImportStatus(`Imported ${result.new_sessions} session(s). Reloading…`)
          setTimeout(loadData, 1000)
        } else {
          setImportStatus('No new sessions.')
          setTimeout(() => setImportStatus(''), 3000)
        }
      })
      .catch(() => {
        setImportStatus('API not available — run scripts/run_session.py manually.')
        setTimeout(() => setImportStatus(''), 4000)
      })
  }

  // Compute the active speed/input traces based on lap selector state
  const activeTraces = useMemo(() => {
    if (!data) return null
    const allTraces = data.all_lap_traces || {}
    const theoBest  = data.theoretical_best_trace

    const targetTrace = targetLapNum ? allTraces[targetLapNum] : null
    const refTrace    = refLapNum === '__theoretical__'
      ? theoBest
      : (refLapNum ? allTraces[refLapNum] : null)

    if (targetTrace && refTrace) {
      return mergeTraces(targetTrace, refTrace)
    }
    // Fall back to pre-baked traces from export
    return {
      speed_trace: data.speed_trace,
      input_trace: data.input_trace,
    }
  }, [data, targetLapNum, refLapNum])

  if (loading) return <div style={S.load}>Loading telemetry…</div>
  if (error) return (
    <div style={S.err}>
      <span>Failed to load dashboard.json</span>
      <span style={{ color: '#64748b', fontSize: '12px' }}>{error}</span>
      <span style={{ color: '#64748b', fontSize: '11px' }}>
        Run: python scripts/run_session.py &lt;file.ld&gt;
      </span>
    </div>
  )

  return (
    <div style={S.app}>
      <SessionHeader session={data.session} />

      <div style={S.importBar}>
        <button style={S.importBtn} onClick={handleImport}>↓ Import New Session</button>
        {importStatus && <span style={S.importStatus}>{importStatus}</span>}
      </div>

      <LapCompareSelector
        laps={data.laps}
        allLapTraces={data.all_lap_traces}
        theoreticalBestTrace={data.theoretical_best_trace}
        targetLapNum={targetLapNum}
        refLapNum={refLapNum}
        onTargetChange={setTargetLapNum}
        onRefChange={setRefLapNum}
      />

      <div style={S.grid}>
        <div style={S.left}>
          {/* Top row: lap bar chart + track map */}
          <div style={S.topRow}>
            <div style={S.panel}>
              <LapTimeBarChart laps={data.laps} session={data.session} />
            </div>
            <div style={{ ...S.panel, padding: '16px' }}>
              <TrackMap trackMapUrl={data.session.track_map_url} />
            </div>
          </div>

          <div style={S.panel}>
            <SpeedTraceChart
              speedTrace={activeTraces?.speed_trace || data.speed_trace}
              cornerSummary={data.corner_summary}
              trackLength={data.session.track_length_m}
            />
          </div>
          <div style={S.panel}>
            <InputTraceChart
              inputTrace={activeTraces?.input_trace || data.input_trace}
              cornerSummary={data.corner_summary}
            />
          </div>
          <div style={S.panel}>
            <CornerSummaryTable cornerSummary={data.corner_summary} />
          </div>
        </div>

        <div style={S.right}>
          <CoachingPanel report={data.coaching_report} session={data.session} />
        </div>
      </div>
    </div>
  )
}
