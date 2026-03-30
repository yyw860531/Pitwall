export default function TrackMap({ trackMapUrl }) {
  if (!trackMapUrl) return null

  return (
    <div>
      <div style={{
        fontSize: '11px', color: '#64748b',
        textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8,
      }}>
        Track Map
      </div>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#060b14',
        borderRadius: '4px',
        overflow: 'hidden',
        maxHeight: 200,
        padding: 12,
      }}>
        <img
          src={trackMapUrl}
          alt="Track map"
          style={{
            maxWidth: '100%',
            maxHeight: 180,
            objectFit: 'contain',
            filter: 'invert(1) hue-rotate(180deg) brightness(0.85)',
            opacity: 0.9,
          }}
        />
      </div>
    </div>
  )
}
