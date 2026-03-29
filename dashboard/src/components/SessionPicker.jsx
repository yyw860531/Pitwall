import { useState, useEffect } from 'react'

function fmtMs(ms) {
  if (!ms) return '—'
  const m = Math.floor(ms / 60000)
  const s = ((ms % 60000) / 1000).toFixed(3)
  return `${m}:${s.padStart(6, '0')}`
}

const S = {
  bar: {
    background: '#060b14',
    borderBottom: '1px solid #1e293b',
    padding: '6px 16px',
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    flexWrap: 'wrap',
  },
  label: { fontSize: '10px', color: '#475569', textTransform: 'uppercase', letterSpacing: '0.08em' },
  select: {
    background: '#0f172a',
    border: '1px solid #334155',
    borderRadius: '4px',
    color: '#e2e8f0',
    fontSize: '12px',
    padding: '4px 8px',
    fontFamily: 'monospace',
    minWidth: '320px',
    cursor: 'pointer',
  },
  btn: {
    background: '#1e40af',
    color: '#e2e8f0',
    border: 'none',
    borderRadius: '4px',
    padding: '4px 12px',
    cursor: 'pointer',
    fontSize: '12px',
    fontFamily: 'monospace',
  },
  analyseBtn: (busy) => ({
    background: busy ? '#14532d' : '#166534',
    color: '#e2e8f0',
    border: 'none',
    borderRadius: '4px',
    padding: '4px 12px',
    cursor: busy ? 'default' : 'pointer',
    fontSize: '12px',
    fontFamily: 'monospace',
    opacity: busy ? 0.7 : 1,
  }),
  status: { fontSize: '11px', color: '#64748b' },
  statusGreen: { fontSize: '11px', color: '#86efac' },
}

export default function SessionPicker({ currentSessionId, onSessionData }) {
  const [sessions, setSessions]     = useState([])
  const [selected, setSelected]     = useState(currentSessionId || '')
  const [loadStatus, setLoadStatus] = useState('')
  const [analyseStatus, setAnalyseStatus] = useState('')

  useEffect(() => {
    fetch('/api/sessions')
      .then(r => r.json())
      .then(setSessions)
      .catch(() => {})
  }, [])

  // Keep selected in sync if parent reloads with a new session
  useEffect(() => {
    if (currentSessionId) setSelected(currentSessionId)
  }, [currentSessionId])

  const handleLoad = () => {
    if (!selected) return
    setLoadStatus('Loading…')
    fetch(`/api/export/${selected}`, { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          setLoadStatus(`Error: ${data.error}`)
          setTimeout(() => setLoadStatus(''), 4000)
        } else {
          onSessionData(data)
          setLoadStatus('')
        }
      })
      .catch(() => {
        setLoadStatus('Server not running.')
        setTimeout(() => setLoadStatus(''), 4000)
      })
  }

  const handleAnalyse = () => {
    if (!selected || analyseStatus) return
    setAnalyseStatus('Running AI analysis… this may take a minute.')
    fetch(`/api/analyse/${selected}`, { method: 'POST' })
      .then(r => r.json())
      .then(result => {
        if (result.error) {
          setAnalyseStatus(`Error: ${result.error}`)
          setTimeout(() => setAnalyseStatus(''), 6000)
        } else {
          onSessionData(result)
          setAnalyseStatus('Analysis complete.')
          setTimeout(() => setAnalyseStatus(''), 2000)
        }
      })
      .catch(() => {
        setAnalyseStatus('Analysis failed — check server logs.')
        setTimeout(() => setAnalyseStatus(''), 5000)
      })
  }

  if (!sessions.length) return null

  return (
    <div style={S.bar}>
      <span style={S.label}>Session</span>
      <select
        style={S.select}
        value={selected}
        onChange={e => setSelected(e.target.value)}
      >
        {sessions.map(s => (
          <option key={s.session_id} value={s.session_id}>
            {s.session_id}  ·  {s.track}  ·  {s.valid_lap_count} laps  ·  best {fmtMs(s.fastest_time_ms)}
          </option>
        ))}
      </select>

      {selected !== currentSessionId && (
        <button style={S.btn} onClick={handleLoad}>Load</button>
      )}

      <button
        style={S.analyseBtn(!!analyseStatus)}
        onClick={handleAnalyse}
        disabled={!!analyseStatus}
      >
        {analyseStatus ? '⏳ Analysing…' : '▶ Run AI Analysis'}
      </button>

      {loadStatus    && <span style={S.status}>{loadStatus}</span>}
      {analyseStatus && <span style={S.statusGreen}>{analyseStatus}</span>}
    </div>
  )
}
