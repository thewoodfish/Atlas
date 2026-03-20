import { useState, useEffect, useCallback } from 'react'
import { fetchStatus, fetchPortfolio, fetchOpportunities, fetchStrategies, fetchTransactions, fetchMetrics, fetchGuardrails } from './api'
import { useSocket } from './useSocket'
import Header from './components/Header'
import MetricsBar from './components/MetricsBar'
import AgentStatusPanel from './components/AgentStatusPanel'
import PortfolioChart from './components/PortfolioChart'
import ActivityFeed from './components/ActivityFeed'
import TransactionTable from './components/TransactionTable'
import OpportunitiesTable from './components/OpportunitiesTable'
import GuardrailsPanel from './components/GuardrailsPanel'

const REFRESH_MS = 10_000

export default function App() {
  const [status,        setStatus]        = useState(null)
  const [portfolio,     setPortfolio]     = useState(null)
  const [opportunities, setOpportunities] = useState(null)
  const [strategies,    setStrategies]    = useState(null)
  const [transactions,  setTransactions]  = useState(null)
  const [metrics,       setMetrics]       = useState(null)
  const [guardrails,    setGuardrails]    = useState(null)
  const [loading,       setLoading]       = useState(true)
  const [lastRefresh,   setLastRefresh]   = useState(null)

  const { events, connected } = useSocket()

  const refresh = useCallback(async () => {
    try {
      const [s, p, o, st, t, m, g] = await Promise.allSettled([
        fetchStatus(), fetchPortfolio(), fetchOpportunities(),
        fetchStrategies(), fetchTransactions(), fetchMetrics(), fetchGuardrails(),
      ])
      if (s.status  === 'fulfilled') setStatus(s.value)
      if (p.status  === 'fulfilled') setPortfolio(p.value)
      if (o.status  === 'fulfilled') setOpportunities(o.value)
      if (st.status === 'fulfilled') setStrategies(st.value)
      if (t.status  === 'fulfilled') setTransactions(t.value)
      if (m.status  === 'fulfilled') setMetrics(m.value)
      if (g.status  === 'fulfilled') setGuardrails(g.value)
      setLastRefresh(new Date())
    } catch (e) {
      console.error('Refresh error', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, REFRESH_MS)
    return () => clearInterval(id)
  }, [refresh])

  useEffect(() => {
    if (events.length > 0 && ['execution_report','state_change'].includes(events[0].type)) {
      refresh()
    }
  }, [events])

  return (
    <div style={{ minHeight: '100vh', background: '#020617' }}>
      <Header status={status} connected={connected} />

      <main style={{ maxWidth: 1400, margin: '0 auto', padding: '20px 16px', display: 'flex', flexDirection: 'column', gap: 20 }}>
        <MetricsBar metrics={metrics} status={status} loading={loading} />
        <AgentStatusPanel status={status} loading={loading} />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.6fr', gap: 16 }}>
          <PortfolioChart portfolio={portfolio} loading={loading} />
          <ActivityFeed events={events} connected={connected} />
        </div>

        <GuardrailsPanel guardrails={guardrails} loading={loading} />
        <OpportunitiesTable opportunities={opportunities} loading={loading} />
        <TransactionTable transactions={transactions} loading={loading} />

        <div style={{ textAlign: 'center', padding: '12px 0', color: '#1e293b', fontSize: 10, letterSpacing: '0.1em' }}>
          ATLAS · AUTONOMOUS TREASURY INFRASTRUCTURE
          {lastRefresh && ` · LAST REFRESH ${lastRefresh.toLocaleTimeString('en-US', { hour12: false })}`}
        </div>
      </main>

      <style>{`
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
      `}</style>
    </div>
  )
}
