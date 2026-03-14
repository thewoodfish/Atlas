claude "Build Atlas - an autonomous multi-agent onchain treasury system. Here's what to implement:

## Project Structure
Create a Python project with this layout:
atlas/
  agents/
    market_analyst.py
    strategy_agent.py
    risk_manager.py
    execution_agent.py
  core/
    orchestrator.py
    wallet.py
    simulator.py
  data/
    defi_client.py
  dashboard/
    app.py (React frontend or simple Flask UI)
  main.py

## Agent Implementations

**Market Analyst Agent** - Polls mock DeFi APIs (or real ones: Aave, Curve, DeFiLlama) every 30s. Returns structured opportunities: {protocol, apy, liquidity, volatility, type}

**Strategy Agent** - Takes opportunities, generates 2-3 portfolio strategies with allocations, expected yield, and risk score. Uses Claude API (claude-sonnet-4-20250514) for reasoning.

**Risk Manager Agent** - Enforces hard constraints: max 40% per protocol, skip pools under \$10M liquidity, flag volatility spikes. Returns approved/rejected strategy with reasoning.

**Execution Agent** - Simulates onchain tx execution (deposit/withdraw/swap/rebalance). Logs signed tx hashes. Integrates with WDK wallet if available, otherwise mock wallet with real address format.

**Orchestrator** - LangGraph or simple async loop connecting all agents. Runs continuously: scan → strategize → risk check → execute → monitor → repeat.

**Simulator** - Before live execution, runs shadow portfolio to estimate returns and validate strategies.

## Dashboard
Simple React or Flask UI showing:
- Live agent activity feed (what each agent is doing)
- Current portfolio allocation (pie chart)
- Yield metrics and PnL
- Transaction log
- Risk status

## Tech Stack
- Python 3.11+
- LangGraph for agent orchestration
- Anthropic SDK for agent reasoning
- aiohttp for async API calls
- Flask + React or Streamlit for dashboard
- SQLite for state persistence

## Demo Scenario
Seed wallet with 1000 USDT. Run full autonomous loop. Simulate market condition change mid-run and show Atlas auto-rebalancing.

Start by creating the project structure, then implement each agent, then wire up the orchestrator, then build the dashboard. Make it production-looking with proper logging and error handling."