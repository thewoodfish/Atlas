const BASE = '/api'

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
