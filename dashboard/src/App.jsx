import { useState, useEffect } from 'react'
import SessionHeader from './components/SessionHeader.jsx'
import LapTimeBarChart from './components/LapTimeBarChart.jsx'
import SpeedTraceChart from './components/SpeedTraceChart.jsx'
import InputTraceChart from './components/InputTraceChart.jsx'
import CornerSummaryTable from './components/CornerSummaryTable.jsx'
import CoachingPanel from './components/CoachingPanel.jsx'

const styles = {
  app: {
    minHeight: '100vh',
    background: '#0a0a0f',
    color: '#e2e8f0',
  },
  loading: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100vh',
    fontSize: '14px',
    color: '#64748b',
    fontFamily: 'monospace',
  },
  error: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100vh',
    gap: '12px',
    color: '#ef4444',
    fontFamily: 'monospace',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: '1fr 340px',
    gridTemplateRows: 'auto',
    gap: '1px',
    background: '#1e293b',
    minHeight: 'calc(100vh - 56px)',
  },
  left: {
    background: '#0a0a0f',
    display: 'flex',
    flexDirection: 'column',
    gap: '1px',
  },
  right: {
    background: '#0f172a',
    borderLeft: '1px solid #1e293b',
    position: 'sticky',
    top: 56,
    height: 'calc(100vh - 56px)',
    overflowY: 'auto',
  },
  panel: {
    background: '#0f172a',
    padding: '16px',
  },
  importBar: {
    background: '#0f172a',
    borderBottom: '1px solid #1e293b',
    padding: '8px 16px',
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  importBtn: {
    background: '#1e40af',
    color: '#e2e8f0',
    border: 'none',
    borderRadius: '4px',
    padding: '4px 12px',
    cursor: 'pointer',
    fontSize: '12px',
    fontFamily: 'monospace',
  },
  importStatus: {
    fontSize: '11px',
    color: '#64748b',
  },
}

export default function App() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [importStatus, setImportStatus] = useState('')

  const loadData = () => {
    setLoading(true)
    fetch('/dashboard.json')
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }

  useEffect(() => { loadData() }, [])

  const handleImport = () => {
    setImportStatus('Scanning for new sessions…')
    fetch('/api/scan', { method: 'POST' })
      .then(r => r.json())
      .then(result => {
        if (result.new_sessions > 0) {
          setImportStatus(`Imported ${result.new_sessions} new session(s). Reloading…`)
          setTimeout(loadData, 1000)
        } else {
          setImportStatus('No new sessions found.')
          setTimeout(() => setImportStatus(''), 3000)
        }
      })
      .catch(() => {
        setImportStatus('API not available — run scripts/run_session.py manually.')
        setTimeout(() => setImportStatus(''), 4000)
      })
  }

  if (loading) return <div style={styles.loading}>Loading telemetry…</div>
  if (error) return (
    <div style={styles.error}>
      <span>Failed to load dashboard.json</span>
      <span style={{ color: '#64748b', fontSize: '12px' }}>{error}</span>
      <span style={{ color: '#64748b', fontSize: '11px' }}>
        Run: python -m pitwall.export &lt;session_id&gt;
      </span>
    </div>
  )

  return (
    <div style={styles.app}>
      <SessionHeader session={data.session} />

      <div style={styles.importBar}>
        <button style={styles.importBtn} onClick={handleImport}>
          ↓ Import New Session
        </button>
        {importStatus && <span style={styles.importStatus}>{importStatus}</span>}
      </div>

      <div style={styles.grid}>
        <div style={styles.left}>
          <div style={styles.panel}>
            <LapTimeBarChart laps={data.laps} session={data.session} />
          </div>
          <div style={styles.panel}>
            <SpeedTraceChart
              speedTrace={data.speed_trace}
              cornerSummary={data.corner_summary}
              trackLength={data.session.track_length_m}
            />
          </div>
          <div style={styles.panel}>
            <InputTraceChart
              inputTrace={data.input_trace}
              cornerSummary={data.corner_summary}
            />
          </div>
          <div style={styles.panel}>
            <CornerSummaryTable cornerSummary={data.corner_summary} />
          </div>
        </div>
        <div style={styles.right}>
          <CoachingPanel report={data.coaching_report} session={data.session} />
        </div>
      </div>
    </div>
  )
}
