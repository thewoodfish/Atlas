# Atlas

> **The autonomous treasury officer for onchain organisations.**

[![Live Demo](https://img.shields.io/badge/demo-live-brightgreen)](https://frontend-lyart-six-24.vercel.app)
[![Tests](https://img.shields.io/badge/tests-76%20passed-brightgreen)](tests/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![Claude](https://img.shields.io/badge/powered%20by-Claude%20Haiku-orange)](https://anthropic.com)
[![WDK](https://img.shields.io/badge/wallet-Tether%20WDK-green)](https://github.com/tetherto/wallet-sdk)

**[Live Dashboard →](https://frontend-lyart-six-24.vercel.app)** | **[API →](https://atlas-production-1fef.up.railway.app/health)**

---

![Atlas Dashboard](assets/Screenshot%202026-03-21%20at%2022.12.58.png)

---

DAOs and crypto-native funds collectively hold billions in stablecoins sitting idle in multi-sigs. Nobody's managing it — allocations are debated in Discord, executed manually, and never optimised.

**Atlas fixes this.** It is a fully autonomous multi-agent system that continuously monitors DeFi yield markets, reasons about risk using Claude, simulates outcomes before touching capital, executes rebalancing, and — when markets turn — rotates into XAUT (Tether Gold) as a safe-haven hedge. When accumulated yield crosses a threshold, it pays out autonomously to a beneficiary address via Tether WDK — no human trigger required.

Not a dashboard with buttons. Not a cron job. A real AI agent acting as a treasury officer — earning, deciding, and paying — 24/7.

Built with [Tether WDK](https://github.com/tetherto/wallet-sdk) for self-custodial wallet operations and [Anthropic Claude](https://www.anthropic.com) for agent reasoning.

---

## What makes Atlas different

Most DeFi automation tools are rule-based scripts with a fixed strategy. Atlas uses a **pipeline of specialised AI agents**, each with a distinct role and its own Claude reasoning context — closer to a team of analysts than a bot:

| | Rule-based automation | **Atlas** |
|---|---|---|
| Market analysis | Fetches APYs | Claude ranks 18,000+ pools by risk-adjusted return and forms market sentiment |
| Strategy | One fixed allocation | 3 philosophically distinct strategies generated and justified by Claude |
| Risk | Hard rules only | Hard rules **+** independent Claude qualitative review |
| Pre-trade | None | 7-day shadow simulation with gas + slippage models |
| Execution | Manual trigger | Fully autonomous; monitors positions every 30s |
| On-chain | Signed messages | **Real USDT transfers via WDK — verifiable on Etherscan** |
| Payments | Manual | **Agent autonomously pays harvested yield to a beneficiary when threshold is crossed** |
| Downside | Exit manually | Auto-emergency-exit on TVL crisis or yield collapse |
| Safe haven | USDT only | **Rotates to XAUT (Tether Gold) when sentiment turns bearish** |
| Auditability | Logs | **Full agent decision trace with Claude's exact reasoning, visible in dashboard** |

---

## Live Demo

The system is deployed and running autonomously right now:

| Service | URL |
|---------|-----|
| Dashboard (Vercel) | https://frontend-lyart-six-24.vercel.app |
| Backend API (Railway) | https://atlas-production-1fef.up.railway.app |
| Health check | https://atlas-production-1fef.up.railway.app/health |

The Railway backend is scanning real DeFiLlama data (18,000+ pools), running Claude reasoning cycles, and serving live WebSocket events to the dashboard.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                            ATLAS SYSTEM                                │
│                                                                        │
│  ┌───────────────┐    ┌───────────────┐    ┌───────────────┐          │
│  │ Market        │    │ Strategy      │    │ Risk          │          │
│  │ Analyst       │───▶│ Agent         │───▶│ Manager       │          │
│  │               │    │               │    │               │          │
│  │ DeFiLlama API │    │ Claude API    │    │ Hard rules +  │          │
│  │ 18,000+ pools │    │ 3 strategies  │    │ Claude review │          │
│  └───────────────┘    └───────────────┘    └──────┬────────┘          │
│                                                   │                    │
│  ┌───────────────┐    ┌───────────────┐    ┌──────▼────────┐          │
│  │ Execution     │◀───│ Simulator     │◀───│ Approved      │          │
│  │ Agent         │    │               │    │ Strategy      │          │
│  │               │    │ 7-day shadow  │    │               │          │
│  │ WDKWallet     │    │ projection    │    └───────────────┘          │
│  └──────┬────────┘    └───────────────┘                               │
│         │                                                              │
│  ┌──────▼─────────────────────────────────────────────────────────┐   │
│  │                       ORCHESTRATOR                              │   │
│  │  IDLE → SCANNING → STRATEGIZING → RISK_CHECK → SIMULATING      │   │
│  │       → EXECUTING → MONITORING → (REBALANCING) → IDLE          │   │
│  │  SQLite persistence · asyncio event bus · 30s loop             │   │
│  └─────────────────────────────┬──────────────────────────────────┘   │
│                                │                                       │
│  ┌─────────────────────────────▼──────────────────────────────────┐   │
│  │                        DASHBOARD                                │   │
│  │  Flask REST API (/api/*)  ·  Flask-SocketIO (/ws/feed)         │   │
│  │  React: Metrics · Portfolio donut · Agent feed · Tx table      │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │                    WDK MICROSERVICE (Node.js)                    │  │
│  │  Tether WDK · EVM wallet · USDT + XAUT send · EIP-191 sign     │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Agent Pipeline

| Step | Agent | Input → Output | Key behaviour |
|------|-------|---------------|---------------|
| 1 | **Market Analyst** | DeFiLlama pools → `MarketReport` | Claude ranks all opportunities by risk-adjusted return; forms bullish / bearish / neutral / volatile sentiment |
| 2 | **Strategy Agent** | `MarketReport` → `StrategyBundle` | Claude generates 3 distinct strategies with allocation rationale; adds XAUT hedge (10–20%) when sentiment is bearish or volatile |
| 3 | **Risk Manager** | `StrategyBundle` → `RiskAssessment` | Layer 1: hard rules (≤40% concentration, TVL ≥$10M, risk score ≤8). Layer 2: Claude qualitative review. Falls back to capital-preservation if all strategies fail |
| 4 | **Simulator** | `RiskAssessment` → `SimulationResult` | 7-day compounding projection with per-protocol gas ($1.50–$3/tx on L2) and slippage (2–8 bps); rejects strategy if net return < 0 |
| 5 | **Execution Agent** | `SimulationResult` → `ExecutionReport` | Deploys capital via WDK; buys XAUT when hedging; monitors every 30s; auto-exits on yield drop >20%, TVL < $5M, or allocation drift >10pp |

---

![Agent Decision Trace & Guardrails](assets/Screenshot%202026-03-21%20at%2021.25.13.png)

## Autonomous Yield Payments

Atlas doesn't just manage yield — it **pays it out automatically**.

After every execution cycle, the Orchestrator checks whether the projected 7-day yield exceeds a configured threshold. If it does, it autonomously calls `pay_yield()` which routes a real USDT transfer to the beneficiary address via the WDK `send_usdt()` endpoint — no human trigger required.

```
Cycle completes → projected yield $95 ≥ threshold $50
  → Orchestrator._step_pay_yield()
  → WDKWallet.pay_yield(YIELD_PAYOUT_ADDRESS, $95)
  → WDK send_usdt() → real on-chain tx hash
  → yield_payment event → dashboard activity feed
```

Configure in `.env`:
```bash
YIELD_PAYOUT_ADDRESS=0xYourBeneficiaryAddress
YIELD_PAYOUT_THRESHOLD_USD=50
```

This is programmable, agent-driven commerce: the agent observes yield, makes an autonomous payment decision, and executes a real on-chain transfer — all without human input.

---

## XAUT Safe-Haven Hedge

When the Market Analyst reports **bearish or volatile** sentiment, Atlas automatically shifts a portion of the treasury into **XAUT (Tether Gold)**:

- Strategy Agent instructs Claude to allocate 10–20% to `XAUT` in the conservative strategy
- Risk Manager exempts XAUT from DeFi-specific TVL and concentration checks
- Simulator treats XAUT as 0% APY — pure capital preservation, no phantom yield
- Execution Agent calls `buy_xaut()` → converts USDT → XAUT on-chain via the WDK microservice
- When sentiment recovers, XAUT is sold back to USDT and redeployed into yield-bearing protocols

**This is real multi-asset treasury management** — not just yield optimisation.

---

## Tether WDK Integration

Atlas ships a dedicated **Node.js microservice** (`wdk_service/`) that wraps the [Tether Wallet Development Kit](https://github.com/tetherto/wallet-sdk):

- Self-custodial EVM wallet initialised from a BIP-39 seed phrase
- Live on-chain balances: ETH, USDT (ERC-20), and **XAUT (Tether Gold)**
- `POST /wallet/send-usdt` — on-chain USDT transfer
- `POST /wallet/send-xaut` — on-chain XAUT transfer
- `POST /wallet/sign` — EIP-191 message signing (audit trail for every rebalance)
- Python `WDKWallet` calls the service over HTTP; degrades gracefully to simulation when the service is offline
- **Real on-chain transfers:** every `deposit()` calls `send_usdt()` to the protocol's mainnet contract address — producing a real, Etherscan-verifiable tx hash when the wallet is funded
- **Live balance polling:** `get_system_status()` fetches live ETH / USDT / XAUT balances from the WDK service on every dashboard refresh

```bash
# Start the WDK service standalone
make wdk-service        # node wdk_service/server.js  →  http://localhost:3001

# Or start everything together
docker compose up --build
```

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/thewoodfish/Atlas.git
cd Atlas

# 2. Configure
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY (required)

# 3. Install Python + Node dependencies
make install

# 4. Run the demo (2 full autonomous cycles, $100k simulated portfolio)
make run-demo

# 5. Open the dashboard
open http://localhost:8080
```

---

## Demo Walkthrough

`make run-demo` seeds a **$100,000 USDT** treasury and runs two complete autonomous cycles, including a market shock in Cycle 2.

### What to watch — step by step

| # | What happens | Where to look |
|---|---|---|
| 1 | Preflight validates Anthropic API key | Terminal logs |
| 2 | `SCANNING` — Market Analyst fetches 18,000+ DeFiLlama pools, Claude ranks by risk-adjusted return | Activity Feed → `market_report` event |
| 3 | `STRATEGIZING` — Strategy Agent asks Claude to generate 3 strategies; bearish → adds XAUT hedge | **Agent Decision Trace** panel → "Strategy Agent" node |
| 4 | `RISK_CHECK` — Hard rules run, then a second Claude qualitative review | **Agent Decision Trace** → "Risk Manager" decision + reasoning |
| 5 | `SIMULATING` — 7-day projection with L2 gas + slippage; rejected if net return < 0 | Agent Decision Trace → "Simulator" |
| 6 | `EXECUTING` — Execution Agent deploys capital via WDK wallet | Transaction Table → new `deposit` rows with tx hashes |
| 7 | **Yield payment** — if projected yield ≥ $50 threshold, Atlas autonomously pays USDT to beneficiary | **Autonomous Yield Payments** panel → confirmed payment card |
| 8 | `MONITORING` — position monitor watches for yield drop >20%, TVL < $5M, drift >10pp | Guardrails panel → Autonomous Triggers |
| 9 | **Market shock** (Cycle 2) — Curve APY → 1%, TVL → $4M injected automatically | Activity Feed → `demo_shock` event (amber) |
| 10 | `REBALANCING` — monitor detects both triggers, Atlas exits without human input | Transaction Table → `withdraw` + `emergency` trigger |

### Dashboard panels

- **Agent Decision Trace** — live reasoning chain for every agent in the last cycle; shows Claude's exact rationale
- **Autonomous Yield Payments** — payment lifecycle: projected yield → threshold check → WDK execute → tx hash
- **Permissions & Guardrails** — all active risk limits and autonomous trigger thresholds
- **PAUSE / RESUME / STOP** — control the agent without touching the terminal

---

![Opportunities & Transactions](assets/Screenshot%202026-03-21%20at%2022.13.37.png)

![Live Activity Feed & Agent Traces](assets/Screenshot%202026-03-21%20at%2023.53.15.png)

## Running Tests

```bash
make test
# or with coverage:
make test-coverage
```

**76 tests, 0 failures — no mocks on critical paths:**

| Suite | Tests | What's covered |
|-------|-------|----------------|
| `tests/test_risk_manager.py` | 17 | All hard-rule constraint paths, capital preservation fallback |
| `tests/test_simulator.py` | 22 | Projection math, gas model, approval/rejection logic |
| `tests/test_wallet.py` | 22 | Balance accounting, XAUT buy/sell, overdraft guards, tx recording |
| `tests/test_api.py` | 15 | All REST endpoints, WebSocket handshake, pagination |

---

## Deployment

### Railway (Backend)

```bash
# One-click deploy — Railway reads railway.json and Dockerfile automatically
railway up
```

Set these environment variables in Railway:
```
ANTHROPIC_API_KEY=sk-ant-...
START_MODE=agent          # runs full autonomous agent
INITIAL_PORTFOLIO_USDT=100000
```

### Vercel (Frontend)

```bash
cd atlas/dashboard/frontend
vercel --prod
```

Set in Vercel project settings:
```
VITE_API_URL=https://your-railway-url.up.railway.app
```

### Docker (local)

```bash
cp .env.example .env   # add ANTHROPIC_API_KEY
docker compose up --build
# Atlas API:    http://localhost:8080
# Dashboard:    http://localhost:3000
# WDK service:  http://localhost:3001
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Agent reasoning | Anthropic SDK — `claude-haiku-4-5-20251001` with forced `tool_use` for structured JSON output |
| Async runtime | Python 3.11+ `asyncio` — fully async agent pipeline, no blocking I/O |
| Wallet / signing | Tether WDK (`@tetherto/wdk`, `@tetherto/wdk-wallet-evm`) via Node.js microservice |
| DeFi data | DeFiLlama REST API (`yields.llama.fi/pools`) — 18,000+ pools, 30s cache, quality filters |
| Data models | Pydantic v2 — strict validation on all agent I/O boundaries |
| State persistence | SQLAlchemy + SQLite — every run, simulation, and transaction persisted |
| REST API | Flask 3 + Flask-CORS |
| Real-time feed | Flask-SocketIO — event bus from orchestrator to dashboard via WebSocket |
| Frontend | Vite + React + TailwindCSS + Recharts |
| Logging | Loguru — structured, coloured, file-rotated |
| Testing | pytest — 76 tests, real dependencies on critical paths |
| Container | Docker Compose — wdk-service + api + nginx-fronted React |
| Backend hosting | Railway (Dockerfile deploy, auto PORT injection) |
| Frontend hosting | Vercel (Vite build, SPA rewrites) |

---

## Project Structure

```
Atlas/
├── atlas/
│   ├── agents/
│   │   ├── market_analyst.py    # DeFiLlama fetch + Claude ranking
│   │   ├── strategy_agent.py    # Claude strategy generator (3 variants + XAUT hedge)
│   │   ├── risk_manager.py      # Two-layer risk validation + capital preservation
│   │   └── execution_agent.py   # Wallet rebalancer + XAUT buy/sell + position monitor
│   ├── core/
│   │   ├── orchestrator.py      # Async state machine + event bus + SQLite runs
│   │   ├── wallet.py            # WDKWallet (HTTP→Node.js) + MockWallet + XAUT accounting
│   │   └── simulator.py         # 7-day shadow projection engine
│   ├── data/
│   │   ├── defi_client.py       # DeFiLlama client — cache, retry, mock fallback
│   │   └── models.py            # All Pydantic models
│   └── dashboard/
│       ├── backend/
│       │   ├── app.py           # Flask app factory + SocketIO
│       │   └── api.py           # REST endpoints + WebSocket feed
│       └── frontend/            # React dashboard (Vite + TailwindCSS)
├── wdk_service/
│   └── server.js                # Node.js WDK microservice (USDT + XAUT + sign)
├── tests/                       # 76 pytest tests
├── config.py                    # Centralised env-var config
├── main.py                      # Entry point — preflight + asyncio.run
├── Dockerfile                   # Railway-ready, dynamic PORT
├── docker-compose.yml
└── Makefile                     # install · run-demo · test · wdk-service · docker-up
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | **Required.** Anthropic API key |
| `WDK_SEED_PHRASE` | random | BIP-39 seed for the WDK wallet (ephemeral if not set) |
| `WDK_SERVICE_URL` | `http://localhost:3001` | WDK microservice base URL |
| `EVM_PROVIDER` | `https://eth.drpc.org` | Ethereum JSON-RPC provider |
| `INITIAL_PORTFOLIO_USDT` | `100000` | Starting capital in USDT |
| `YIELD_PAYOUT_ADDRESS` | — | Beneficiary address for autonomous yield payments |
| `YIELD_PAYOUT_THRESHOLD_USD` | `50` | Minimum projected yield (USD) to trigger an autonomous payout |
| `SCAN_INTERVAL_SECONDS` | `30` | Market Analyst poll interval |
| `MAX_PROTOCOL_ALLOCATION` | `0.40` | Max concentration per DeFi protocol (40%) |
| `MIN_LIQUIDITY_USD` | `10000000` | TVL floor for protocol eligibility ($10M) |
| `DASHBOARD_PORT` | `8080` | Flask API port (Railway injects `PORT` automatically) |
| `START_MODE` | `dashboard` | Set to `agent` on Railway to run full autonomous agent |
| `LOG_LEVEL` | `INFO` | Loguru log level |

---

## What's Next

Atlas is a foundation. The architecture is deliberately extensible:

- **Full ABI protocol calls** — Atlas already sends real USDT on-chain and pays yield via WDK; next is calling Aave's `deposit()` / Compound's `supply()` directly with encoded calldata
- **More asset classes** — XAUT is the first non-USDT asset; the pattern extends to any ERC-20 (wBTC, stETH, USDC)
- **Cross-chain** — the WDK supports multiple EVM chains; Arbitrum and Base are the natural next targets
- **Governance hooks** — add a DAO vote threshold before large rebalances execute, making Atlas safe for community-governed treasuries
- **Richer Claude models** — swap Haiku for Opus on high-stakes decisions above a configurable capital threshold

---

## Hackathon Disclosure

Built from scratch during the hackathon period. No prior codebase was reused. All agents, wallet integration, simulation engine, dashboard, and tests were written during the event.

**Open-source dependencies:** Anthropic SDK, Tether WDK (`@tetherto/wdk`, `@tetherto/wdk-wallet-evm`), DeFiLlama public API, Flask, React, Pydantic, SQLAlchemy — standard open-source libraries only.
