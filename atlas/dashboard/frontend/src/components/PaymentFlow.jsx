import { Skeleton } from './Skeleton'

const fmt = (v) => v == null ? '—' : v

export default function PaymentFlow({ events, loading }) {
  const rows = events ?? []

  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <span style={{ fontSize: 10, color: '#475569', letterSpacing: '0.15em' }}>AUTONOMOUS YIELD PAYMENTS</span>
        <span style={{ marginLeft: 'auto', padding: '1px 8px', borderRadius: 4, fontSize: 8,
          background: '#f59e0b22', color: '#f59e0b', fontWeight: 700, letterSpacing: '0.1em' }}>
          AGENT-DRIVEN
        </span>
      </div>

      {loading ? (
        Array(2).fill(0).map((_, i) => <div key={i} style={{ marginBottom: 8 }}><Skeleton h={80} /></div>)
      ) : rows.length === 0 ? (
        <div style={{ textAlign: 'center', color: '#334155', fontSize: 12, padding: 20 }}>
          No yield payments yet — threshold not yet crossed
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {rows.map((evt, i) => {
            const ts   = evt.ts ? new Date(evt.ts * 1000).toLocaleTimeString('en-US', { hour12: false }) : '—'
            const hash = evt.tx_hash ? evt.tx_hash.slice(0, 10) + '…' : '—'
            const to   = evt.to ? evt.to.slice(0, 8) + '…' + evt.to.slice(-4) : '—'
            return (
              <div key={i} style={{ background: '#0d1117', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' }}>
                {/* Header row */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <span style={{ padding: '1px 8px', borderRadius: 4, fontSize: 8, fontWeight: 700,
                    background: '#22c55e22', color: '#22c55e' }}>CONFIRMED</span>
                  <span style={{ fontSize: 9, color: '#334155' }}>Cycle #{fmt(evt.cycle)}</span>
                  <span style={{ marginLeft: 'auto', fontSize: 9, color: '#475569', fontFamily: 'monospace' }}>{ts}</span>
                </div>

                {/* Payment lifecycle steps */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                  <Step label="PROJECTED YIELD" value={`$${fmt(evt.projected_yield_usd)}`} color="#06b6d4" />
                  <Step label="THRESHOLD" value={`≥ $${fmt(evt.threshold_usd)}`} color="#8b5cf6" checkmark />
                  <Step label="BENEFICIARY" value={to} color="#f59e0b" mono />
                  <Step label="TX HASH" value={hash} color="#22c55e" mono />
                </div>

                <div style={{ marginTop: 8, fontSize: 9, color: '#475569' }}>
                  <span style={{ color: '#334155' }}>trigger:</span>{' '}
                  <span style={{ color: '#f59e0b', fontFamily: 'monospace' }}>{evt.trigger ?? 'threshold_crossed'}</span>
                  {' · '}
                  <span style={{ color: '#334155' }}>via:</span>{' '}
                  <span style={{ color: '#22c55e' }}>WDK send_usdt() → on-chain</span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* explanation footer */}
      <div style={{ marginTop: 12, padding: '8px 10px', background: '#020617', borderRadius: 6,
        border: '1px solid #0f172a', fontSize: 9, color: '#334155', lineHeight: 1.6 }}>
        Atlas autonomously pays harvested yield to a beneficiary wallet when the projected 7-day return
        exceeds the configured threshold — no human trigger required. Payments route through the
        WDK microservice as real on-chain USDT transfers.
      </div>
    </div>
  )
}

function Step({ label, value, color, mono, checkmark }) {
  return (
    <div style={{ background: '#0f172a', borderRadius: 6, padding: '6px 8px' }}>
      <div style={{ fontSize: 7, color: '#334155', letterSpacing: '0.1em', marginBottom: 3 }}>
        {label}{checkmark && <span style={{ color: '#22c55e', marginLeft: 4 }}>✓</span>}
      </div>
      <div style={{ color, fontSize: 10, fontFamily: mono ? 'monospace' : 'inherit',
        fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {value}
      </div>
    </div>
  )
}
