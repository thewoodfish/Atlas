# Atlas

**Autonomous onchain treasury infrastructure.** Atlas is a multi-agent system that continuously scans DeFi markets, generates portfolio strategies, enforces risk constraints, simulates outcomes, and executes rebalancing — without human intervention.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ATLAS SYSTEM                                 │
│                                                                       │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐           │
│  │   Market     │    │   Strategy   │    │    Risk      │           │
│  │   Analyst    │───▶│   Agent      │───▶│   Manager    │           │
│  │              │    │              │    │              │           │
│  │ DeFiLlama API│    │ Claude API   │    │ Hard rules + │           │
│  │ Mock fallback│    │ 3 strategies │    │ Claude review│           │
│  └──────────────┘    └──────────────┘    └──────┬───────┘           │
│                                                  │                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────▼───────┐           │
│  │  Execution   │◀───│  Simulator   │◀───│  Approved    │           │
│  │  Agent       │    │              │    │  Strategy    │           │
│  │              │    │ 7-day shadow │    │              │           │
│  │  MockWallet  │    │ projection   │    └──────────────┘           │
│  └──────┬───────┘    └──────────────┘                               │
│         │                                                             │
│  ┌──────▼───────────────────────────────────────────────────────┐   │
│  │                      ORCHESTRATOR                             │   │
│  │  IDLE→SCANNING→STRATEGIZING→RISK_CHECK→SIMULATING→EXECUTING  │   │
│  │  →MONITORING→(REBALANCING)→IDLE                              │   │
│  │  SQLite persistence · asyncio event bus · 60s loop           │   │
│  └──────────────────────────────┬────────────────────────────────┘  │
│                                 │                                     │
│  ┌──────────────────────────────▼────────────────────────────────┐  │
│  │                    DASHBOARD                                    │  │
│  │  Flask REST API (/api/*)  ·  Flask-SocketIO (/ws/feed)        │  │
│  │  React UI: Metrics · Portfolio · Agents · Feed · Tables       │  │
│  └────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Agent Pipeline

| Step | Agent | Description |
|------|-------|-------------|
| 1 | **Market Analyst** | Polls DeFiLlama every 30s; filters stablecoin pools; uses Claude to rank by risk-adjusted return → `MarketReport` |
| 2 | **Strategy Agent** | Receives `MarketReport`; uses Claude to generate 3 strategies (Conservative / Balanced / Aggressive) → `StrategyBundle` |
| 3 | **Risk Manager** | Layer 1: deterministic hard rules (max 40% concentration, TVL ≥ $10M, risk score ≤ 8, volatility flag). Layer 2: Claude qualitative review → `RiskAssessment` |
| 4 | **Simulator** | 7-day shadow projection with gas + slippage models; rejects if net return < 0 → `SimulationResult` |
| 5 | **Execution Agent** | Rebalances `MockWallet`; monitors positions every 60s for yield drops >20%, TVL < $5M, or drift >10pp |

---

## Quick Start

```bash
# 1. Clone and enter the project
git clone https://github.com/thewoodfish/Atlas.git
cd Atlas

# 2. Configure environment
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY

# 3. Install dependencies
make install

# 4. Run in demo mode (recommended first run)
make run-demo

# 5. In a separate terminal, start the frontend dev server
make dashboard
# → http://localhost:5173
```

---

## Demo Walkthrough

The demo (`make run-demo` or `python main.py --demo`) seeds a wallet with **1000 USDT** and runs the full autonomous loop:

1. **Cycle 1** — Atlas scans DeFi markets, generates 3 strategies, risk-checks them, simulates outcomes, and executes the best approved strategy.
2. **Cycle 2** — A mid-run market shock is injected: Curve Finance APY drops to 1% and TVL falls to $4M. The position monitor detects the emergency condition and automatically exits the position.
3. The dashboard shows the rebalancing in real time via WebSocket.

---

## Running Tests

```bash
make test
# or with coverage:
make test-coverage
```

76 tests across:
- `tests/test_risk_manager.py` — all hard-rule constraints
- `tests/test_simulator.py` — projection math, gas model, approval logic
- `tests/test_wallet.py` — balance accounting, tx recording
- `tests/test_api.py` — all REST endpoints

---

## Docker

```bash
# Copy and fill in env
cp .env.example .env

# Start full stack (API + React frontend)
docker compose up --build

# API:      http://localhost:5000
# Frontend: http://localhost:3000
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent reasoning | Anthropic SDK (`claude-sonnet-4-6`) |
| Async runtime | Python 3.11+ `asyncio` |
| DeFi data | DeFiLlama REST API + mock fallback |
| Data models | Pydantic v2 |
| HTTP client | aiohttp |
| State persistence | SQLAlchemy + SQLite |
| REST API | Flask 3 + Flask-CORS |
| WebSocket | Flask-SocketIO |
| Frontend | Vite + React + TailwindCSS + Recharts |
| Logging | Loguru |
| Testing | pytest |
| Container | Docker + nginx |

---

## Project Structure

```
atlas/
├── agents/
│   ├── market_analyst.py   # DeFi opportunity scanner + Claude ranking
│   ├── strategy_agent.py   # Claude-powered portfolio strategy generator
│   ├── risk_manager.py     # Two-layer risk validation
│   └── execution_agent.py  # Wallet rebalancer + position monitor
├── core/
│   ├── orchestrator.py     # State machine + agent pipeline + event bus
│   ├── wallet.py           # MockWallet with SQLite tx persistence
│   └── simulator.py        # 7-day shadow portfolio engine
├── data/
│   ├── defi_client.py      # DeFiLlama async client with cache + retry
│   └── models.py           # All Pydantic models
└── dashboard/
    ├── backend/
    │   ├── app.py          # Flask app factory
    │   └── api.py          # REST endpoints + WebSocket feed
    └── frontend/           # React dashboard (Vite)
config.py                   # Centralised config from env vars
main.py                     # Entry point (--demo / --no-dashboard)
```

---

## Configuration

All settings in `.env` (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | **Required.** Your Anthropic API key |
| `WALLET_ADDRESS` | `0x000…` | Mock wallet address |
| `DEFI_LLAMA_BASE_URL` | `https://api.llama.fi` | DeFiLlama base URL |
| `SCAN_INTERVAL_SECONDS` | `30` | How often Market Analyst polls |
| `INITIAL_PORTFOLIO_USDT` | `1000` | Starting capital |
| `MAX_PROTOCOL_ALLOCATION` | `0.40` | Max 40% per protocol |
| `MIN_LIQUIDITY_USD` | `10000000` | Min $10M TVL |
| `DASHBOARD_PORT` | `5000` | Flask dashboard port |
| `LOG_LEVEL` | `INFO` | Logging level |
