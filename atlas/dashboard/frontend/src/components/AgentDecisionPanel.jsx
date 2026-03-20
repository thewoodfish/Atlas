import { Skeleton } from './Skeleton'

const AGENT_COLOR = {
  'Market Analyst':  '#06b6d4',
  'Strategy Agent':  '#8b5cf6',
  'Risk Manager':    '#f59e0b',
  'Simulator':       '#22c55e',
  'Execution Agent': '#ef4444',
}

const AGENT_ICON = {
  'Market Analyst':  '📊',
  'Strategy Agent':  '🧠',
  'Risk Manager':    '🛡',
  'Simulator':       '🔬',
  'Execution Agent': '⚡',
}

export default function AgentDecisionPanel({ traces, loading }) {
  // Group by cycle, show last cycle's trace
  const lastCycle = traces?.length ? Math.max(...traces.map(t => t.cycle ?? 0)) : null
  const cycleTraces = lastCycle != null ? (traces ?? []).filter(t => t.cycle === lastCycle) : []

  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <span style={{ fontSize: 10, color: '#475569', letterSpacing: '0.15em' }}>AGENT DECISION TRACE</span>
        {lastCycle != null && (
          <span style={{ marginLeft: 4, padding: '1px 8px', borderRadius: 4, fontSize: 8,
            background: '#1e3a5f', color: '#60a5fa', fontWeight: 700, letterSpacing: '0.1em' }}>
            CYCLE #{lastCycle}
          </span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 8, color: '#334155' }}>CLAUDE REASONING CHAIN</span>
      </div>

      {loading ? (
        Array(5).fill(0).map((_, i) => <div key={i} style={{ marginBottom: 8 }}><Skeleton h={52} /></div>)
      ) : cycleTraces.length === 0 ? (
        <div style={{ textAlign: 'center', color: '#334155', fontSize: 12, padding: 20 }}>
          No traces yet — run a cycle to see agent reasoning
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
          {cycleTraces.map((trace, i) => {
            const color    = AGENT_COLOR[trace.agent] ?? '#64748b'
            const icon     = AGENT_ICON[trace.agent]  ?? '●'
            const approved = trace.decision?.includes('approved') || trace.decision?.includes('executed') || trace.decision?.includes('generated')
            const rejected = trace.decision?.includes('rejected')
            const ts       = trace.ts ? new Date(trace.ts * 1000).toLocaleTimeString('en-US', { hour12: false }) : ''
            const isLast   = i === cycleTraces.length - 1

            return (
              <div key={i} style={{ display: 'flex', gap: 12 }}>
                {/* connector line */}
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 24, flexShrink: 0 }}>
                  <div style={{ width: 24, height: 24, borderRadius: '50%', background: `${color}22`,
                    border: `1.5px solid ${color}`, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 11, flexShrink: 0 }}>{icon}</div>
                  {!isLast && <div style={{ width: 1, flexGrow: 1, background: '#1e293b', minHeight: 12, marginTop: 2 }} />}
                </div>

                {/* content */}
                <div style={{ paddingBottom: isLast ? 0 : 12, flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
                    <span style={{ color, fontSize: 10, fontWeight: 700 }}>{trace.agent}</span>
                    <span style={{
                      padding: '0px 6px', borderRadius: 3, fontSize: 8, fontWeight: 700,
                      background: rejected ? '#ef444422' : approved ? '#22c55e22' : '#64748b22',
                      color: rejected ? '#ef4444' : approved ? '#22c55e' : '#64748b',
                    }}>{(trace.decision ?? '').toUpperCase().slice(0, 40)}</span>
                    <span style={{ marginLeft: 'auto', color: '#334155', fontSize: 9, fontFamily: 'monospace' }}>{ts}</span>
                  </div>
                  {trace.detail && (
                    <p style={{ color: '#94a3b8', fontSize: 10, lineHeight: 1.5, margin: 0,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={trace.detail}>{trace.detail}</p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
