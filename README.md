# Atlas

Atlas is autonomous onchain treasury infrastructure — a multi-agent system that continuously scans DeFi markets, generates portfolio strategies, enforces risk constraints, and executes rebalancing transactions without human intervention.

## Architecture

```
atlas/
├── agents/          # Specialized AI agents
│   ├── market_analyst.py   # Polls DeFi APIs for opportunities
│   ├── strategy_agent.py   # Generates portfolio strategies via Claude
│   ├── risk_manager.py     # Enforces risk constraints
│   └── execution_agent.py  # Simulates onchain execution
├── core/            # Orchestration & infrastructure
│   ├── orchestrator.py     # Main agent loop (LangGraph)
│   ├── wallet.py           # Wallet abstraction
│   └── simulator.py        # Shadow portfolio simulator
├── data/            # External data layer
│   └── defi_client.py      # DeFiLlama / Aave / Curve clients
├── dashboard/       # Monitoring UI
│   ├── backend/            # Flask API
│   └── frontend/           # React UI
└── tests/
```

## Agent Loop

1. **Market Analyst** — scans protocols every 30s, returns structured opportunities
2. **Strategy Agent** — uses Claude to generate 2–3 portfolio allocations
3. **Risk Manager** — validates strategies against hard constraints
4. **Execution Agent** — executes approved strategies (simulated or live)
5. **Orchestrator** — ties the loop together, persists state to SQLite

## Quick Start

```bash
cp .env.example .env
# Fill in ANTHROPIC_API_KEY and optional RPC/wallet vars

pip install -r requirements.txt
python main.py
```

## Demo Scenario

Seeds a mock wallet with 1000 USDT, runs the full autonomous loop, and triggers a mid-run market condition change to demonstrate auto-rebalancing.

## Tech Stack

- Python 3.11+
- Anthropic SDK + LangGraph for agent orchestration
- aiohttp for async DeFi API calls
- Flask + React dashboard
- SQLite for state persistence
- Loguru for structured logging
