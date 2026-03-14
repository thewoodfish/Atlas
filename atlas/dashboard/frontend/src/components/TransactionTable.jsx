import { Skeleton } from './Skeleton'

const TX_COLOR = { deposit: '#22c55e', withdraw: '#f59e0b', swap: '#06b6d4', rebalance: '#8b5cf6' }

export default function TransactionTable({ transactions, loading }) {
  const rows = transactions?.transactions ?? []

  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 16 }}>
      <p style={{ fontSize: 10, color: '#475569', letterSpacing: '0.15em', marginBottom: 12 }}>TRANSACTIONS</p>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #1e293b' }}>
              {['TYPE','PROTOCOL','AMOUNT','TX HASH','STATUS','TIME'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '4px 10px', color: '#475569', fontWeight: 600, letterSpacing: '0.1em', fontSize: 9 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? Array(5).fill(0).map((_, i) => (
              <tr key={i}><td colSpan={6} style={{ padding: '6px 10px' }}><Skeleton h={14} /></td></tr>
            )) : rows.length === 0 ? (
              <tr><td colSpan={6} style={{ padding: 20, textAlign: 'center', color: '#334155', fontSize: 12 }}>No transactions yet</td></tr>
            ) : rows.map((tx, i) => {
              const color = TX_COLOR[tx.tx_type] ?? '#64748b'
              const hash  = tx.tx_hash ? tx.tx_hash.slice(0, 10) + '…' : '—'
              const ts    = tx.created_at ? new Date(tx.created_at * 1000).toLocaleTimeString('en-US', { hour12: false }) : '—'
              return (
                <tr key={i} style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '7px 10px' }}>
                    <span style={{ padding: '1px 7px', borderRadius: 4, fontSize: 9, fontWeight: 700,
                      background: `${color}22`, color }}>{(tx.tx_type ?? '').toUpperCase()}</span>
                  </td>
                  <td style={{ padding: '7px 10px', color: '#94a3b8' }}>{tx.protocol}</td>
                  <td style={{ padding: '7px 10px', color: '#f1f5f9', fontFamily: 'monospace' }}>
                    ${Number(tx.amount_usd ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </td>
                  <td style={{ padding: '7px 10px', color: '#475569', fontFamily: 'monospace', fontSize: 10 }}>{hash}</td>
                  <td style={{ padding: '7px 10px' }}>
                    <span style={{ color: '#22c55e', fontSize: 9 }}>● {tx.status ?? 'confirmed'}</span>
                  </td>
                  <td style={{ padding: '7px 10px', color: '#475569' }}>{ts}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
