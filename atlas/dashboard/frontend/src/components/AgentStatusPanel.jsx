import { Skeleton } from './Skeleton'

const AGENTS = [
  { key: 'market_analyst',  label: 'Market Analyst',  icon: '📡', stateKey: 'last_market_report' },
  { key: 'strategy_agent',  label: 'Strategy Agent',  icon: '🧠', stateKey: 'last_strategy' },
  { key: 'risk_manager',    label: 'Risk Manager',    icon: '🛡️', stateKey: 'last_simulation' },
  { key: 'execution_agent', label: 'Execution Agent', icon: '⚡', stateKey: 'last_execution' },
]

const STATE_AGENT_MAP = {
  SCANNING:     'market_analyst',
  STRATEGIZING: 'strategy_agent',
  RISK_CHECK:   'risk_manager',
  SIMULATING:   'risk_manager',
  EXECUTING:    'execution_agent',
  REBALANCING:  'execution_agent',
}

function AgentCard({ agent, status, systemState, loading }) {
  const isActive = STATE_AGENT_MAP[systemState] === agent.key
  const data = status?.[agent.stateKey]

  let summary = '—'
  if (data) {
    if (agent.key === 'market_analyst') summary = `${data.opportunities ?? 0} opportunities · ${data.sentiment ?? '—'}`
    if (agent.key === 'strategy_agent') summary = data.name ? `Selected: ${data.name} (${data.expected_yield?.toFixed(1)}% APY)` : '—'
    if (agent.key === 'risk_manager')   summary = data.approved ? `✓ Approved · APY ${data.projected_apy?.toFixed(1)}%` : '✗ Rejected'
    if (agent.key === 'execution_agent') summary = data.trigger ? `${data.trigger} · ${data.tx_count} txs · $${data.gas_usd?.toFixed(0)} gas` : '—'
  }

  return (
    <div style={{
      background: isActive ? 'rgba(6,182,212,0.05)' : '#0f172a',
      border: `1px solid ${isActive ? 'rgba(6,182,212,0.3)' : '#1e293b'}`,
      borderRadius: 12, padding: 16, flex: 1, minWidth: 160,
      transition: 'all 0.3s ease',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: 18 }}>{agent.icon}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {isActive && (
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#06b6d4', display: 'inline-block', animation: 'pulse 1s infinite' }} />
          )}
          <span style={{
            fontSize: 9, fontWeight: 700, padding: '1px 7px', borderRadius: 9999, letterSpacing: '0.1em',
            background: isActive ? 'rgba(6,182,212,0.2)' : 'rgba(100,116,139,0.1)',
            color: isActive ? '#06b6d4' : '#64748b',
            border: `1px solid ${isActive ? 'rgba(6,182,212,0.3)' : 'transparent'}`,
          }}>{isActive ? 'ACTIVE' : 'IDLE'}</span>
        </div>
      </div>
      <p style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', marginBottom: 6, letterSpacing: '0.05em' }}>{agent.label.toUpperCase()}</p>
      {loading ? <Skeleton h={12} w="80%" /> : (
        <p style={{ fontSize: 11, color: '#64748b', lineHeight: 1.5 }}>{summary}</p>
      )}
    </div>
  )
}

export default function AgentStatusPanel({ status, loading }) {
  const systemState = status?.system_state ?? 'IDLE'
  return (
    <div>
      <p style={{ fontSize: 10, color: '#475569', letterSpacing: '0.15em', marginBottom: 10 }}>AGENT STATUS</p>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        {AGENTS.map(a => (
          <AgentCard key={a.key} agent={a} status={status} systemState={systemState} loading={loading} />
        ))}
      </div>
    </div>
  )
}
