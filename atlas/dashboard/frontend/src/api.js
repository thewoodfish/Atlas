// In production (Vercel), VITE_API_URL points to the Railway backend.
// In dev, it's empty and Vite proxies /api → localhost:5000.
const BASE = (import.meta.env.VITE_API_URL || '') + '/api'

async function get(path) {
  const r = await fetch(`${BASE}${path}`)
  const json = await r.json()
  if (!json.success) throw new Error(json.error || 'API error')
  return json.data
}

export const fetchStatus       = () => get('/status')
export const fetchPortfolio    = () => get('/portfolio')
export const fetchOpportunities = () => get('/opportunities')
export const fetchStrategies   = () => get('/strategies')
export const fetchTransactions = (page = 1, perPage = 20) =>
  get(`/transactions?page=${page}&per_page=${perPage}`)
export const fetchMetrics      = () => get('/metrics')
export const fetchGuardrails   = () => get('/guardrails')
export const fetchAgentTraces  = () => get('/agent-traces')
export const fetchYieldEvents  = () => get('/yield-events')
export const postControl       = (action) =>
  fetch('/api/control', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }) }).then(r => r.json())
