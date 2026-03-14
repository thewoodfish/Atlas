import { Skeleton } from './Skeleton'

function Metric({ label, value, sub, color = '#06b6d4', loading }) {
  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: '14px 20px', flex: 1, minWidth: 140 }}>
      <p style={{ fontSize: 10, color: '#475569', letterSpacing: '0.12em', marginBottom: 6 }}>{label}</p>
      {loading ? <Skeleton h={28} w="70%" /> : (
        <p style={{ fontSize: 22, fontWeight: 800, color, fontFamily: 'monospace' }}>{value}</p>
      )}
      {sub && !loading && <p style={{ fontSize: 10, color: '#64748b', marginTop: 2 }}>{sub}</p>}
    </div>
  )
}

export default function MetricsBar({ metrics, status, loading }) {
  const total   = metrics?.total_value_usd
  const apy     = metrics?.current_apy
  const pnl24h  = metrics?.pnl_24h_usd
  const pct24h  = metrics?.pnl_24h_pct
  const ret     = metrics?.total_return_usd
  const retPct  = metrics?.total_return_pct
  const cycles  = metrics?.cycle_count ?? status?.cycle_count ?? 0
  const txCount = status?.wallet ? Object.keys(status.wallet.allocations ?? {}).length : 0

  const fmt$ = v => v == null ? '—' : `$${Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  const fmtPct = v => v == null ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(3)}%`
  const pnlColor = v => (v ?? 0) >= 0 ? '#22c55e' : '#ef4444'

  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
      <Metric label="TOTAL VALUE"     value={fmt$(total)}  sub="USD"                    loading={loading} />
      <Metric label="CURRENT APY"     value={apy == null ? '—' : `${Number(apy).toFixed(2)}%`}  color="#06b6d4" loading={loading} />
      <Metric label="24H PnL"         value={fmt$(pnl24h)} sub={fmtPct(pct24h)}         color={pnlColor(pnl24h)} loading={loading} />
      <Metric label="TOTAL RETURN"    value={fmt$(ret)}    sub={fmtPct(retPct)}          color={pnlColor(ret)} loading={loading} />
      <Metric label="CYCLES"          value={cycles}       sub="completed"               color="#a78bfa" loading={loading} />
    </div>
  )
}
