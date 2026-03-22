# Atlas — Autonomous Treasury Officer

## What we built

Atlas is a fully autonomous multi-agent AI system that manages onchain DAO treasuries end-to-end — scanning DeFi markets, generating strategies, validating risk, simulating outcomes, executing trades, and paying yield to beneficiaries — without any human intervention.

A five-agent pipeline powered by Anthropic Claude runs continuously, every 30 seconds, making real decisions on a $100,000 USDT portfolio.

---

## The Problem

DAOs and crypto-native funds collectively hold billions in stablecoins sitting idle in multi-sigs. Treasury management is manual — APYs are copied from dashboards, allocations are debated in Discord, and transactions are executed one by one. It's slow, error-prone, and it never sleeps.

No institution manages money this way. Onchain organisations shouldn't either.

---

## The Solution

Atlas replaces the manual treasury process with an autonomous agent pipeline:

### 1. Market Analyst
Fetches and filters 18,000+ live DeFi pools from DeFiLlama every cycle. Claude ranks the top 15 stablecoin opportunities by risk-adjusted return and forms a market sentiment signal (bullish / bearish / neutral / volatile).

### 2. Strategy Agent
Claude generates three philosophically distinct portfolio strategies — conservative, balanced, and aggressive — each with full allocation rationale and expected yield. When sentiment is bearish, a XAUT (Tether Gold) safe-haven hedge is automatically included.

### 3. Risk Manager
Two-layer validation: deterministic hard rules first (max 40% per protocol, TVL ≥ $10M, risk score ≤ 8), then an independent Claude qualitative review. Strategies that fail fall back to capital preservation automatically.

### 4. Simulator
A 7-day shadow projection models compounding yield, per-protocol gas costs, and slippage before any capital moves. If net return is negative, the strategy is rejected — no execution.

### 5. Execution Agent
Deploys capital via the Tether WDK microservice. Monitors every position every 30 seconds. Auto-exits on TVL collapse (< $5M), yield drop (> 20%), or allocation drift (> 10pp) — no human trigger required.

---

## Tether WDK Integration

Atlas ships a dedicated **Node.js microservice** wrapping the Tether Wallet Development Kit:

- Self-custodial EVM wallet initialised from a BIP-39 seed phrase
- Live on-chain balances: ETH, USDT, and **XAUT (Tether Gold)**
- `POST /wallet/send-usdt` — real on-chain USDT transfers
- `POST /wallet/send-xaut` — real on-chain XAUT transfers
- `POST /wallet/sign` — EIP-191 message signing for every rebalance (full audit trail)

Every deposit calls `send_usdt()` to the protocol's mainnet contract address, producing a real Etherscan-verifiable tx hash when the wallet is funded.

---

## Autonomous Yield Payments

The flagship agentic payment feature: when accumulated yield crosses a configurable threshold, Atlas autonomously constructs and sends a USDT payment to the beneficiary address via the WDK — no human trigger, no manual step.

```
Cycle completes → projected yield $95 ≥ threshold $50
  → Orchestrator triggers pay_yield()
  → WDK send_usdt() → real on-chain tx hash
  → yield_payment event → dashboard activity feed
```

This is programmable, agent-driven commerce. The agent earns, decides, and pays.

---

## Live Dashboard

A React + Flask-SocketIO dashboard streams every agent decision in real time:

- **Agent Decision Trace** — Claude's exact reasoning for every agent in the last cycle
- **Autonomous Yield Payments** — 4-step payment lifecycle: projected yield → threshold check → WDK execute → tx hash
- **Guardrails Panel** — all active risk limits and autonomous trigger thresholds
- **Transaction Table** — every deposit, withdrawal, and swap with tx hashes and triggers
- **PAUSE / RESUME / STOP** — operator controls without touching the terminal

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent reasoning | Anthropic Claude Haiku (`claude-haiku-4-5-20251001`) — forced `tool_use` for structured JSON |
| Wallet | Tether WDK (`@tetherto/wdk`, `@tetherto/wdk-wallet-evm`) — Node.js microservice |
| DeFi data | DeFiLlama REST API — 18,000+ pools, live |
| Async runtime | Python 3.11 asyncio — fully async agent pipeline |
| Data validation | Pydantic v2 — strict validation on all agent I/O |
| Persistence | SQLAlchemy + SQLite — every run, simulation, and tx persisted |
| API | Flask 3 + Flask-SocketIO |
| Frontend | Vite + React + TailwindCSS + Recharts |
| Backend hosting | Railway |
| Frontend hosting | Vercel |

---

## Live Deployment

| | URL |
|---|---|
| Dashboard | https://frontend-lyart-six-24.vercel.app |
| API | https://atlas-production-1fef.up.railway.app |
| GitHub | https://github.com/thewoodfish/Atlas |

The Railway backend is running the autonomous agent right now — scanning real DeFiLlama data, selecting strategies, and monitoring positions continuously.

---

## What's Next

- **Full ABI calls** — direct `deposit()` / `supply()` to Aave, Compound, and Sky via encoded calldata
- **Cross-chain** — the WDK supports multiple EVM chains; Arbitrum and Base are the natural next targets
- **Governance hooks** — DAO vote threshold before large rebalances, making Atlas safe for community-governed treasuries
- **Multi-asset** — XAUT is the first non-USDT asset; the pattern extends to wBTC, stETH, USDC
