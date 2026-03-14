const TYPE_STYLE = {
  state_change:      { color: '#06b6d4', label: 'STATE' },
  market_report:     { color: '#3b82f6', label: 'MARKET' },
  strategy_bundle:   { color: '#8b5cf6', label: 'STRATEGY' },
  risk_assessment:   { color: '#f59e0b', label: 'RISK' },
  simulation_result: { color: '#14b8a6', label: 'SIM' },
  execution_report:  { color: '#22c55e', label: 'EXEC' },
  demo_shock:        { color: '#ef4444', label: 'SHOCK' },
  error:             { color: '#ef4444', label: 'ERROR' },
}

function fmtPayload(type, payload) {
  if (!payload) return ''
  if (type === 'state_change')      return payload.state ?? ''
  if (type === 'market_report')     return `${payload.opportunities} pools · ${payload.sentiment} · ${payload.source}`
  if (type === 'strategy_bundle')   return `C:${payload.conservative_yield?.toFixed(1)}% B:${payload.balanced_yield?.toFixed(1)}% A:${payload.aggressive_yield?.toFixed(1)}%`
  if (type === 'risk_assessment')   return `${payload.approved ? '✓' : '✗'} ${payload.selected_strategy} flags:[${(payload.risk_flags ?? []).join(',')||'none'}]`
  if (type === 'simulation_result') return `${payload.approved ? '✓' : '✗'} APY=${payload.projected_apy?.toFixed(2)}% net=$${payload.net_return?.toFixed(2)}`
  if (type === 'execution_report')  return `${payload.trigger} · ${payload.tx_count} txs · $${payload.gas_usd?.toFixed(0)} gas · $${payload.portfolio_value?.toFixed(2)}`
  if (type === 'demo_shock')        return `${payload.protocol} APY→${payload.new_apy}% TVL→$${(payload.new_tvl_usd/1e6).toFixed(1)}M`
  if (type === 'error')             return payload.message ?? ''
  return JSON.stringify(payload).slice(0, 80)
}

export default function ActivityFeed({ events, connected }) {
  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 16, display: 'flex', flexDirection: 'column', height: 320 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <p style={{ fontSize: 10, color: '#475569', letterSpacing: '0.15em' }}>ACTIVITY FEED</p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: connected ? '#22c55e' : '#ef4444' }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor', display: 'inline-block' }} />
          {connected ? 'LIVE' : 'OFFLINE'}
        </div>
      </div>
      <div style={{ overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
        {events.length === 0 && (
          <p style={{ color: '#334155', fontSize: 11, padding: '20px 0', textAlign: 'center' }}>Waiting for events…</p>
        )}
        {events.map((ev, i) => {
          const style = TYPE_STYLE[ev.type] ?? { color: '#64748b', label: ev.type.toUpperCase() }
          const ts = new Date(ev.ts).toLocaleTimeString('en-US', { hour12: false })
          return (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 11, padding: '3px 0', borderBottom: '1px solid #0f172a' }}>
              <span style={{ color: '#334155', flexShrink: 0, width: 60 }}>{ts}</span>
              <span style={{
                flexShrink: 0, padding: '0 5px', borderRadius: 4, fontSize: 9, fontWeight: 700,
                background: `${style.color}22`, color: style.color, width: 58, textAlign: 'center',
              }}>{style.label}</span>
              <span style={{ color: '#94a3b8', wordBreak: 'break-all' }}>{fmtPayload(ev.type, ev.payload)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
