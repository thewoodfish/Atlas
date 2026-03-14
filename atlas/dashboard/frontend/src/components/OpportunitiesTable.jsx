import { Skeleton } from './Skeleton'

const TYPE_COLOR = { lending: '#3b82f6', stable_swap: '#8b5cf6', yield_vault: '#f59e0b', liquidity_pool: '#22c55e', unknown: '#475569' }

function RiskDot({ vol }) {
  const color = vol < 0.05 ? '#22c55e' : vol < 0.12 ? '#f59e0b' : '#ef4444'
  return <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block' }} title={`Vol ${(vol * 100).toFixed(1)}%`} />
}

export default function OpportunitiesTable({ opportunities, loading }) {
  const opps = opportunities?.opportunities ?? []
  const sentiment = opportunities?.sentiment
  const source    = opportunities?.source

  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <p style={{ fontSize: 10, color: '#475569', letterSpacing: '0.15em' }}>OPPORTUNITIES</p>
        <div style={{ display: 'flex', gap: 8 }}>
          {sentiment && (
            <span style={{ fontSize: 9, padding: '1px 7px', borderRadius: 9999, fontWeight: 700,
              background: sentiment === 'bullish' ? 'rgba(34,197,94,0.15)' : sentiment === 'bearish' ? 'rgba(239,68,68,0.15)' : 'rgba(100,116,139,0.15)',
              color: sentiment === 'bullish' ? '#22c55e' : sentiment === 'bearish' ? '#ef4444' : '#94a3b8',
            }}>{sentiment.toUpperCase()}</span>
          )}
          {source && <span style={{ fontSize: 9, color: '#475569' }}>{source.toUpperCase()}</span>}
        </div>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #1e293b' }}>
              {['#','PROTOCOL','SYMBOL','APY','TVL','TYPE','RISK'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '4px 10px', color: '#475569', fontWeight: 600, letterSpacing: '0.1em', fontSize: 9 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? Array(6).fill(0).map((_, i) => (
              <tr key={i}><td colSpan={7} style={{ padding: '6px 10px' }}><Skeleton h={14} /></td></tr>
            )) : opps.map((opp, i) => {
              const typeColor = TYPE_COLOR[opp.pool_type] ?? '#475569'
              const tvlM = (opp.tvl_usd / 1e6).toFixed(0)
              return (
                <tr key={i} style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '7px 10px', color: '#334155', fontFamily: 'monospace' }}>{opp.rank ?? i + 1}</td>
                  <td style={{ padding: '7px 10px', color: '#f1f5f9', fontWeight: 600 }}>{opp.protocol}</td>
                  <td style={{ padding: '7px 10px', color: '#64748b' }}>{opp.symbol}</td>
                  <td style={{ padding: '7px 10px', color: '#22c55e', fontFamily: 'monospace', fontWeight: 700 }}>
                    {Number(opp.apy).toFixed(1)}%
                  </td>
                  <td style={{ padding: '7px 10px', color: '#94a3b8', fontFamily: 'monospace' }}>${tvlM}M</td>
                  <td style={{ padding: '7px 10px' }}>
                    <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 4, fontWeight: 700,
                      background: `${typeColor}22`, color: typeColor }}>{(opp.pool_type ?? '').replace('_',' ').toUpperCase()}</span>
                  </td>
                  <td style={{ padding: '7px 10px' }}><RiskDot vol={opp.volatility_7d ?? 0} /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
