export default function Header({ status, connected }) {
  const state = status?.system_state ?? 'IDLE'
  const addr  = status?.wallet?.address ?? '0x000…'
  const short = addr ? addr.slice(0, 6) + '…' + addr.slice(-4) : '—'
  const isActive = ['SCANNING','STRATEGIZING','RISK_CHECK','SIMULATING','EXECUTING','MONITORING','REBALANCING'].includes(state)

  return (
    <header style={{ background: 'linear-gradient(90deg,#0f172a 0%,#0d1f3c 100%)', borderBottom: '1px solid #1e3a5f' }}
      className="flex items-center justify-between px-6 py-3 sticky top-0 z-50">
      <div className="flex items-center gap-3">
        <div style={{ width: 36, height: 36, background: 'linear-gradient(135deg,#06b6d4,#3b82f6)', borderRadius: 10 }}
          className="flex items-center justify-center text-white font-black text-lg">A</div>
        <div>
          <h1 className="text-lg font-black tracking-widest" style={{ color: '#06b6d4', letterSpacing: '0.2em' }}>ATLAS</h1>
          <p style={{ fontSize: 9, color: '#475569', letterSpacing: '0.15em' }}>AUTONOMOUS TREASURY</p>
        </div>
      </div>

      <div className="flex items-center gap-6 text-xs">
        <div className="flex items-center gap-2">
          <span style={{ color: '#475569' }}>WALLET</span>
          <span style={{ color: '#94a3b8', fontFamily: 'monospace' }}>{short}</span>
        </div>

        <div className="flex items-center gap-2">
          <span style={{ color: '#475569' }}>WS</span>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: connected ? '#22c55e' : '#ef4444', display: 'inline-block' }} />
        </div>

        <div className="flex items-center gap-2">
          {isActive && (
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#22c55e', display: 'inline-block', animation: 'pulse 1.5s infinite' }} />
          )}
          <span style={{
            padding: '2px 10px', borderRadius: 9999, fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
            background: isActive ? 'rgba(34,197,94,0.15)' : 'rgba(100,116,139,0.15)',
            color: isActive ? '#22c55e' : '#64748b',
            border: `1px solid ${isActive ? 'rgba(34,197,94,0.3)' : 'rgba(100,116,139,0.3)'}`,
          }}>
            {state}
          </span>
        </div>

        {status?.demo_mode && (
          <span style={{ padding: '2px 10px', borderRadius: 9999, fontSize: 10, fontWeight: 700,
            background: 'rgba(251,191,36,0.15)', color: '#fbbf24', border: '1px solid rgba(251,191,36,0.3)' }}>
            DEMO
          </span>
        )}
      </div>
    </header>
  )
}
