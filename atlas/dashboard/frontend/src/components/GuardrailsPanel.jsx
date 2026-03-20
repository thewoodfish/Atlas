import { Skeleton } from './Skeleton'

const fmt = v => v == null ? '—' : v

const Rule = ({ label, value, highlight }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '6px 0', borderBottom: '1px solid #0f172a' }}>
    <span style={{ color: '#64748b', fontSize: 10, letterSpacing: '0.05em' }}>{label}</span>
    <span style={{ color: highlight ? '#f59e0b' : '#e2e8f0', fontSize: 10,
      fontFamily: 'monospace', fontWeight: 600 }}>{value}</span>
  </div>
)

export default function GuardrailsPanel({ guardrails, loading }) {
  const g = guardrails

  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 10, color: '#475569', letterSpacing: '0.15em' }}>AGENT PERMISSIONS & GUARDRAILS</span>
        <span style={{ marginLeft: 'auto', padding: '1px 8px', borderRadius: 4, fontSize: 8,
          background: '#16a34a22', color: '#22c55e', fontWeight: 700, letterSpacing: '0.1em' }}>ACTIVE</span>
      </div>

      {loading ? (
        Array(8).fill(0).map((_, i) => <div key={i} style={{ marginBottom: 6 }}><Skeleton h={14} /></div>)
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 24px' }}>
          <div>
            <p style={{ fontSize: 8, color: '#334155', letterSpacing: '0.15em', marginBottom: 6 }}>RISK CONTROLS</p>
            <Rule label="Max allocation per protocol" value={`≤ ${fmt(g?.max_protocol_allocation_pct)}%`} />
            <Rule label="Min pool TVL" value={`≥ $${((g?.min_tvl_usd ?? 0) / 1e6).toFixed(0)}M`} />
            <Rule label="Max risk score" value={`≤ ${fmt(g?.max_risk_score)} / 10`} />
            <Rule label="Max 7-day volatility" value={`≤ ${fmt(g?.max_volatility_pct)}%`} />
          </div>
          <div>
            <p style={{ fontSize: 8, color: '#334155', letterSpacing: '0.15em', marginBottom: 6 }}>AUTONOMOUS TRIGGERS</p>
            <Rule label="Emergency exit TVL floor" value={`< $${((g?.emergency_exit_tvl_usd ?? 0) / 1e6).toFixed(0)}M`} highlight />
            <Rule label="Yield drop exit trigger" value={`> ${fmt(g?.yield_drop_trigger_pct)}% drop`} highlight />
            <Rule label="Rebalance drift trigger" value={`> ${fmt(g?.drift_trigger_pct)}pp drift`} highlight />
            <Rule label="XAUT hedge" value={fmt(g?.xaut_hedge)} />
            <Rule label="Capital preservation fallback" value="On" />
            <Rule label="Yield payout threshold" value={g?.yield_payout_threshold_usd ? `$${g.yield_payout_threshold_usd}` : 'Not set'} />
            <Rule
              label="Yield payout address"
              value={g?.yield_payout_address
                ? g.yield_payout_address.slice(0, 8) + '…' + g.yield_payout_address.slice(-4)
                : 'Not configured'}
            />
          </div>
        </div>
      )}
    </div>
  )
}
