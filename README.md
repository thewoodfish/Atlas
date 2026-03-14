# Atlas

> **Autonomous onchain treasury infrastructure powered by multi-agent AI.**

Atlas is a fully autonomous DeFi portfolio manager. It continuously scans live yield markets, generates allocation strategies, enforces risk constraints through a two-layer validation pipeline, shadow-simulates outcomes before committing capital, and executes rebalancing — all without human intervention. When market conditions deteriorate, it detects the threat and exits positions automatically.

Built with the [Tether WDK](https://github.com/tetherto/wallet-sdk) for self-custodial wallet operations and [Anthropic Claude](https://www.anthropic.com) for agent reasoning.

---

## What makes Atlas different

Most DeFi automation tools are rule-based scripts. Atlas uses a **pipeline of specialized AI agents**, each with a distinct role and its own Claude reasoning context:

- The **Market Analyst** doesn't just fetch APYs — it asks Claude to rank opportunities by risk-adjusted return and form a market view.
- The **Strategy Agent** doesn't pick the highest yield — it generates three philosophically distinct strategies (Conservative / Balanced / Aggressive) and justifies each one.
- The **Risk Manager** runs two independent checks: deterministic hard rules (concentration limits, TVL floors, volatility flags) *and* a separate Claude qualitative review. Both must pass.
- The **Simulator** shadow-executes the strategy over a 7-day projection with realistic gas and slippage models before a single transaction is submitted.
- The **Execution Agent** doesn't just deploy capital — it monitors positions every 60 seconds and triggers autonomous emergency exits on yield collapse or TVL crisis.

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
| 1 | **Market Analyst** | DeFiLlama pools → `MarketReport` | Claude ranks opportunities by risk-adjusted return; forms bullish/bearish/neutral/volatile sentiment |
| 2 | **Strategy Agent** | `MarketReport` → `StrategyBundle` | Claude generates 3 distinct strategies with allocation rationale |
| 3 | **Risk Manager** | `StrategyBundle` → `RiskAssessment` | Layer 1: hard rules (≤40% concentration, TVL ≥$10M, score ≤8, vol flag). Layer 2: Claude qualitative review. Falls back to capital-preservation strategy if all fail |
| 4 | **Simulator** | `RiskAssessment` → `SimulationResult` | 7-day compounding projection with per-protocol gas ($12–$25/tx) and slippage (2–8 bps) models; rejects if net return < 0 |
| 5 | **Execution Agent** | `SimulationResult` → `ExecutionReport` | Deploys capital; monitors every 60s; auto-exits on yield drop >20%, TVL < $5M, or drift >10pp |

---

## Tether WDK Integration

Atlas ships a dedicated **Node.js microservice** (`wdk_service/`) that wraps the [Tether Wallet Development Kit](https://github.com/tetherto/wallet-sdk):

- Self-custodial EVM wallet initialised from a BIP-39 seed phrase
- Live on-chain balances: ETH, USDT (ERC-20), and **XAUT (Tether Gold)**
- `POST /wallet/send-usdt` — on-chain USDT transfer
- `POST /wallet/send-xaut` — on-chain XAUT transfer
- `POST /wallet/sign` — EIP-191 message signing (audit trail for every rebalance)
- Python `WDKWallet` calls the service over HTTP; degrades gracefully to simulation when the service is offline

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
# → set ANTHROPIC_API_KEY (required)
# → optionally set WDK_SEED_PHRASE to persist a real wallet

# 3. Install all dependencies (Python + Node)
make install

# 4. Run the demo  (validates API key, then runs two full cycles)
make run-demo

# 5. Open the dashboard in a second terminal
make dashboard          # → http://localhost:5173
```

---

## Demo Walkthrough

`make run-demo` seeds a $100,000 USDT treasury and runs the full autonomous pipeline:

1. **Preflight** — Atlas validates the Anthropic API key before starting. Fails fast with a clear error if the key is invalid or the network is unreachable.

2. **Cycle 1** — Market Analyst fetches live DeFiLlama data, Claude ranks the opportunities, Strategy Agent generates three allocation strategies, Risk Manager validates them through hard rules and qualitative review, Simulator projects a 7-day return (accounting for gas and slippage), and Execution Agent deploys capital across the approved strategy.

3. **Cycle 2** — Begins 5 seconds after Cycle 1 completes. Mid-cycle, a **market shock is injected**: Curve Finance APY collapses to 1% and TVL drops to $4M. The position monitor detects both a yield-drop trigger and an emergency TVL condition, and **autonomously exits the position** without any human input.

4. **Dashboard** — Every state transition, strategy decision, simulation result, and transaction streams live to the React frontend via WebSocket.

---

## Running Tests

```bash
make test
# or with coverage report:
make test-coverage
```

**76 tests, 0 failures:**

| Suite | Tests | Coverage |
|-------|-------|---------|
| `tests/test_risk_manager.py` | 17 | All hard-rule constraint paths |
| `tests/test_simulator.py` | 22 | Projection math, gas model, approval/rejection logic |
| `tests/test_wallet.py` | 22 | Balance accounting, overdraft guards, tx recording |
| `tests/test_api.py` | 15 | All REST endpoints + pagination |

---

## Docker

```bash
cp .env.example .env   # fill in ANTHROPIC_API_KEY

docker compose up --build
# WDK service:  http://localhost:3001
# Atlas API:    http://localhost:5000
# Dashboard:    http://localhost:3000
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Agent reasoning | Anthropic SDK — `claude-sonnet-4-6` with forced `tool_use` for structured JSON |
| Async runtime | Python 3.11+ `asyncio` — full async agent pipeline |
| Wallet / signing | Tether WDK (`@tetherto/wdk`, `@tetherto/wdk-wallet-evm`) via Node.js microservice |
| DeFi data | DeFiLlama REST API (`yields.llama.fi/pools`) with 30s cache + mock fallback |
| Data models | Pydantic v2 — strict validation on all agent I/O |
| HTTP client | aiohttp (async) + urllib (WDK service calls) |
| State persistence | SQLAlchemy + SQLite — every run, simulation, and transaction persisted |
| REST API | Flask 3 + Flask-CORS |
| Real-time feed | Flask-SocketIO — WebSocket event bus from orchestrator to dashboard |
| Frontend | Vite + React + TailwindCSS + Recharts |
| Logging | Loguru — structured, coloured, file-rotated |
| Testing | pytest — 76 tests, no mocks on critical paths |
| Container | Docker Compose — wdk-service + api + nginx-fronted React |

---

## Project Structure

```
Atlas/
├── atlas/
│   ├── agents/
│   │   ├── market_analyst.py    # DeFiLlama fetch + Claude ranking
│   │   ├── strategy_agent.py    # Claude strategy generator (3 variants)
│   │   ├── risk_manager.py      # Two-layer risk validation + capital preservation
│   │   └── execution_agent.py   # Wallet rebalancer + position monitor
│   ├── core/
│   │   ├── orchestrator.py      # Async state machine + event bus + SQLite runs
│   │   ├── wallet.py            # WDKWallet (HTTP→Node.js) + MockWallet fallback
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
├── main.py                      # Entry point — preflight check + asyncio.run
├── docker-compose.yml           # wdk-service + api + frontend
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
| `MAX_PROTOCOL_ALLOCATION` | `0.40` | Max concentration per protocol (40%) |
| `MIN_LIQUIDITY_USD` | `10000000` | Min TVL floor ($10M) |
| `DASHBOARD_PORT` | `5000` | Flask API port |
| `LOG_LEVEL` | `INFO` | Loguru log level |
