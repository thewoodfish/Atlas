# Atlas

> **The autonomous treasury officer for onchain organisations.**

[![Tests](https://img.shields.io/badge/tests-76%20passed-brightgreen)](tests/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![Claude](https://img.shields.io/badge/powered%20by-Claude%20Haiku-orange)](https://anthropic.com)
[![WDK](https://img.shields.io/badge/wallet-Tether%20WDK-green)](https://github.com/tetherto/wallet-sdk)

---

**The problem:** DAOs and crypto-native funds manage millions in on-chain treasuries manually — copying APYs from dashboards, debating allocations in Discord, executing transactions one by one. It's slow, error-prone, and never sleeps.

**Atlas fixes this.** It is a fully autonomous multi-agent system that continuously monitors DeFi yield markets, reasons about risk, simulates outcomes before committing capital, executes rebalancing, and — when markets turn — rotates into XAUT (Tether Gold) as a safe-haven hedge. No human in the loop. No cron job. A real AI agent acting as a treasury officer.

Built with [Tether WDK](https://github.com/tetherto/wallet-sdk) for self-custodial wallet operations and [Anthropic Claude](https://www.anthropic.com) for agent reasoning.

---

## What makes Atlas different

Most DeFi automation tools are rule-based scripts that execute a fixed strategy. Atlas uses a **pipeline of specialised AI agents**, each with a distinct role and its own Claude reasoning context — closer to a team of analysts than a bot:

| | Rule-based automation | **Atlas** |
|---|---|---|
| Market analysis | Fetches APYs | Claude ranks by risk-adjusted return + forms market sentiment |
| Strategy | One fixed allocation | 3 philosophically distinct strategies generated and justified |
| Risk | Hard rules only | Hard rules **and** independent Claude qualitative review |
| Pre-trade | None | 7-day shadow simulation with gas + slippage models |
| Execution | Manual trigger | Fully autonomous; monitors positions every 60s |
| On-chain | Signed messages | **Real USDT transfers to protocol addresses via WDK — verifiable on Etherscan** |
| Downside | Exit manually | Auto-emergency-exit on TVL crisis or yield collapse |
| Safe haven | USDT only | **Rotates to XAUT (Tether Gold) when sentiment turns bearish** |

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
│  │ + mock fallbk │    │ 3 strategies  │    │ Claude review │          │
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
│  │  SQLite persistence · asyncio event bus · 60 s loop            │   │
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
| 3 | **Risk Manager** | `StrategyBundle` → `RiskAssessment` | Layer 1: hard rules (≤40% concentration, TVL ≥$10M, risk score ≤8, volatility flag). Layer 2: Claude qualitative review. XAUT exempt from DeFi pool checks. Falls back to capital-preservation if all strategies fail |
| 4 | **Simulator** | `RiskAssessment` → `SimulationResult` | 7-day compounding projection with per-protocol gas ($1.50–$3/tx on L2) and slippage (2–8 bps); XAUT modelled as 0% APY store-of-value; rejects strategy if net return < 0 |
| 5 | **Execution Agent** | `SimulationResult` → `ExecutionReport` | Deploys capital via WDK; buys XAUT when hedging; monitors every 60s; auto-exits on yield drop >20%, TVL < $5M, or allocation drift >10pp |

---

## XAUT Safe-Haven Hedge

When the Market Analyst reports **bearish or volatile** sentiment, Atlas automatically shifts a portion of the treasury into **XAUT (Tether Gold)**:

- Strategy Agent instructs Claude to allocate 10–20% to `XAUT` in the conservative strategy
- Risk Manager exempts XAUT from DeFi-specific TVL and concentration checks
- Simulator treats XAUT as 0% APY — pure capital preservation, no phantom yield
- Execution Agent calls `buy_xaut()` → converts USDT → XAUT on-chain and signs an EIP-191 audit message via the WDK microservice
- When sentiment recovers, XAUT is sold back to USDT and redeployed into yield-bearing protocols

**This is real multi-asset treasury management** — not just yield optimisation.

---

## Tether WDK Integration

Atlas ships a dedicated **Node.js microservice** (`wdk_service/`) that wraps the [Tether Wallet Development Kit](https://github.com/tetherto/wallet-sdk):

- Self-custodial EVM wallet initialised from a BIP-39 seed phrase
- Live on-chain balances: ETH, USDT (ERC-20), and **XAUT (Tether Gold)**
- `POST /wallet/send-usdt` — on-chain USDT transfer
- `POST /wallet/send-xaut` — on-chain XAUT transfer
- `POST /wallet/sign` — EIP-191 message signing (audit trail for every rebalance and XAUT hedge)
- Python `WDKWallet` calls the service over HTTP; degrades gracefully to simulation when the service is offline
- **Real on-chain transfers:** every `deposit()` calls `send_usdt()` to the protocol's mainnet contract address — producing a real, Etherscan-verifiable tx hash when the wallet is funded. Falls back to EIP-191 sign-only audit trail if balance is insufficient
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
# Edit .env:
#   ANTHROPIC_API_KEY=sk-ant-...   (required)
#   WDK_SEED_PHRASE=...            (optional — persists wallet across runs)

# 3. Install Python + Node dependencies
make install

# 4. Terminal 1 — run the demo (2 full autonomous cycles)
make run-demo

# 5. Terminal 2 — launch the dashboard
cd atlas/dashboard/frontend && npm run dev -- --port 3000
# → http://localhost:3000
```

---

## Demo Walkthrough

`make run-demo` seeds a **$100,000 USDT** treasury and runs two complete autonomous cycles:

**Preflight** — Atlas validates the Anthropic API key and fails fast with a clear error if credentials are invalid.

**Cycle 1: Full pipeline**
1. Market Analyst fetches live pools from DeFiLlama, filters to top 15 by TVL and quality, sends to Claude for risk-adjusted ranking
2. Strategy Agent generates Conservative / Balanced / Aggressive strategies with full allocation rationale
3. Risk Manager runs hard rules then a separate Claude qualitative review — both must pass
4. Simulator projects a 7-day return with realistic gas and slippage; rejects if net return is negative
5. Execution Agent deploys capital across approved allocations via the WDK wallet, signing each transaction

**Cycle 2: Autonomous response to market shock**
- 5 seconds after Cycle 1, a market shock is injected: Curve Finance APY collapses to 1%, TVL drops to $4M
- Position monitor detects yield-drop and emergency TVL triggers simultaneously
- Atlas **autonomously exits the position** — no human input required
- If sentiment is bearish, the conservative strategy rotates 10–20% into **XAUT** as a gold hedge

**Dashboard** — every state transition, Claude decision, simulation result, and transaction streams live to the React frontend via WebSocket.

---

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

## Docker

```bash
cp .env.example .env   # add ANTHROPIC_API_KEY

docker compose up --build
# WDK service:  http://localhost:3001
# Atlas API:    http://localhost:5000
# Dashboard:    http://localhost:3000
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Agent reasoning | Anthropic SDK — `claude-haiku-4-5-20251001` with forced `tool_use` for structured JSON output |
| Async runtime | Python 3.11+ `asyncio` — fully async agent pipeline, no blocking I/O |
| Wallet / signing | Tether WDK (`@tetherto/wdk`, `@tetherto/wdk-wallet-evm`) via Node.js microservice |
| DeFi data | DeFiLlama REST API (`yields.llama.fi/pools`) — 30s cache, quality filters, mock fallback |
| Data models | Pydantic v2 — strict validation on all agent I/O boundaries |
| State persistence | SQLAlchemy + SQLite — every run, simulation, and transaction persisted |
| REST API | Flask 3 + Flask-CORS |
| Real-time feed | Flask-SocketIO — event bus from orchestrator to dashboard via WebSocket |
| Frontend | Vite + React + TailwindCSS + Recharts |
| Logging | Loguru — structured, coloured, file-rotated |
| Testing | pytest — 76 tests, real dependencies on critical paths |
| Container | Docker Compose — wdk-service + api + nginx-fronted React |

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
| `SCAN_INTERVAL_SECONDS` | `30` | Market Analyst poll interval |
| `MAX_PROTOCOL_ALLOCATION` | `0.40` | Max concentration per DeFi protocol (40%) |
| `MIN_LIQUIDITY_USD` | `10000000` | TVL floor for protocol eligibility ($10M) |
| `DASHBOARD_PORT` | `5000` | Flask API port |
| `LOG_LEVEL` | `INFO` | Loguru log level |

---

## What's Next

Atlas is a foundation. The architecture is deliberately extensible:

- **Full ABI protocol calls** — Atlas already sends real USDT on-chain via WDK; the next step is calling Aave's `deposit()` / Compound's `supply()` directly with encoded calldata, turning transfers into actual yield-bearing positions
- **More asset classes** — XAUT is the first non-USDT asset; the pattern extends to any ERC-20 (wBTC, stETH, USDC)
- **Cross-chain** — the WDK supports multiple EVM chains; the agent pipeline is chain-agnostic; Arbitrum and Base are the natural next targets
- **Governance hooks** — add a DAO vote threshold before large rebalances execute, making Atlas safe for community-governed treasuries
- **Richer Claude models** — swap Haiku for Opus on high-stakes decisions above a configurable capital threshold
