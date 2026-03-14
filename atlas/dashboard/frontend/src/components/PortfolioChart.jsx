import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { Skeleton } from './Skeleton'

const COLORS = ['#06b6d4','#3b82f6','#8b5cf6','#22c55e','#f59e0b','#ec4899','#14b8a6']

const fmtUSD = v => `$${Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 })}`

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const { name, value } = payload[0]
  return (
    <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, padding: '8px 14px', fontSize: 12 }}>
      <p style={{ color: '#94a3b8', marginBottom: 2 }}>{name}</p>
      <p style={{ color: '#f1f5f9', fontWeight: 700 }}>{fmtUSD(value)}</p>
    </div>
  )
}

export default function PortfolioChart({ portfolio, loading }) {
  if (loading) return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 16 }}>
      <p style={{ fontSize: 10, color: '#475569', letterSpacing: '0.15em', marginBottom: 12 }}>ALLOCATION</p>
      <Skeleton h={200} />
    </div>
  )

  const allocs = portfolio?.allocations ?? {}
  const data = Object.entries(allocs)
    .filter(([, v]) => v > 0)
    .map(([name, value]) => ({ name, value }))

  if (!data.length) {
    data.push({ name: 'Idle USDT', value: portfolio?.idle_usdt ?? 1000 })
  }

  const total = portfolio?.total_value_usd
  const pnl   = portfolio?.pnl_usd
  const pct   = portfolio?.pnl_pct

  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <p style={{ fontSize: 10, color: '#475569', letterSpacing: '0.15em' }}>ALLOCATION</p>
        {total != null && (
          <div style={{ textAlign: 'right' }}>
            <p style={{ fontSize: 14, fontWeight: 800, color: '#f1f5f9' }}>{fmtUSD(total)}</p>
            <p style={{ fontSize: 10, color: (pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>
              {(pnl ?? 0) >= 0 ? '+' : ''}{fmtUSD(pnl ?? 0)} ({(pct ?? 0).toFixed(3)}%)
            </p>
          </div>
        )}
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <PieChart>
          <Pie data={data} cx="50%" cy="50%" innerRadius={55} outerRadius={90}
            paddingAngle={3} dataKey="value" strokeWidth={0}>
            {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Pie>
          <Tooltip content={<CustomTooltip />} />
          <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11, color: '#64748b' }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}
