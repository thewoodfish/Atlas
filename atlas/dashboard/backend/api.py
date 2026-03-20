"""
Flask REST + WebSocket API for the Atlas dashboard.

Endpoints
---------
GET  /api/status        — full system status
GET  /api/portfolio     — current portfolio snapshot + PnL
GET  /api/opportunities — latest market opportunities
GET  /api/strategies    — last 3 generated strategies
GET  /api/transactions  — paginated transaction history
GET  /api/metrics       — yield metrics (APY, PnL windows, total return)
WS   /ws/feed           — real-time event stream via Flask-SocketIO

All REST responses use the envelope:
    { "success": bool, "data": ..., "timestamp": float }
"""
from __future__ import annotations

import time
import threading
from typing import Any, Optional

from flask import Blueprint, jsonify, request, current_app
from config import config
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from loguru import logger

# ── Response helpers ──────────────────────────────────────────────────────────

def _ok(data: Any) -> tuple:
    return jsonify({"success": True, "data": data, "timestamp": time.time()}), 200


def _err(message: str, code: int = 500) -> tuple:
    return jsonify({"success": False, "error": message, "timestamp": time.time()}), code


# ── Demo seed data ────────────────────────────────────────────────────────────

_DEMO_OPPORTUNITIES = [
    {"protocol": "Aave V3",      "symbol": "USDT",           "apy": 6.2,  "tvl_usd": 450_000_000, "volatility_7d": 0.008, "pool_type": "lending",      "chain": "Ethereum"},
    {"protocol": "Curve Finance","symbol": "3CRV",            "apy": 9.1,  "tvl_usd": 380_000_000, "volatility_7d": 0.012, "pool_type": "stable_swap",  "chain": "Ethereum"},
    {"protocol": "Compound V3",  "symbol": "USDT",           "apy": 5.8,  "tvl_usd": 290_000_000, "volatility_7d": 0.006, "pool_type": "lending",      "chain": "Ethereum"},
    {"protocol": "Yearn Finance","symbol": "USDT Vault",     "apy": 12.8, "tvl_usd":  95_000_000, "volatility_7d": 0.031, "pool_type": "yield_vault",  "chain": "Ethereum"},
    {"protocol": "Aave V3",      "symbol": "USDC",           "apy": 5.9,  "tvl_usd": 620_000_000, "volatility_7d": 0.007, "pool_type": "lending",      "chain": "Ethereum"},
    {"protocol": "Curve Finance","symbol": "FRAX/USDC",      "apy": 8.4,  "tvl_usd": 210_000_000, "volatility_7d": 0.015, "pool_type": "stable_swap",  "chain": "Ethereum"},
]

_DEMO_STRATEGIES = [
    {
        "name": "Conservative",
        "allocations": {"Aave V3": 40.0, "Compound V3": 35.0, "Curve Finance": 25.0},
        "expected_yield": 6.6,
        "risk_score": 3,
        "rationale": "Prioritises capital safety with established lending protocols.",
    },
    {
        "name": "Balanced",
        "allocations": {"Aave V3": 35.0, "Curve Finance": 35.0, "Compound V3": 30.0},
        "expected_yield": 7.1,
        "risk_score": 5,
        "rationale": "Equal-weight lending and stable-swap for yield diversification.",
    },
    {
        "name": "Aggressive",
        "allocations": {"Yearn Finance": 40.0, "Curve Finance": 35.0, "Aave V3": 25.0},
        "expected_yield": 9.8,
        "risk_score": 7,
        "rationale": "Maximises yield via vaults; accepts higher volatility.",
    },
]

_DEMO_TRANSACTIONS = [
    {"tx_type": "deposit",  "protocol": "Aave V3",      "amount_usd": 400.0,  "tx_hash": "0xabc1" + "0" * 60, "status": "confirmed"},
    {"tx_type": "deposit",  "protocol": "Curve Finance", "amount_usd": 350.0,  "tx_hash": "0xabc2" + "0" * 60, "status": "confirmed"},
    {"tx_type": "deposit",  "protocol": "Compound V3",   "amount_usd": 250.0,  "tx_hash": "0xabc3" + "0" * 60, "status": "confirmed"},
    {"tx_type": "withdraw", "protocol": "Curve Finance", "amount_usd": 100.0,  "tx_hash": "0xabc4" + "0" * 60, "status": "confirmed"},
    {"tx_type": "deposit",  "protocol": "Yearn Finance", "amount_usd": 100.0,  "tx_hash": "0xabc5" + "0" * 60, "status": "confirmed"},
]


_DEMO_AGENT_TRACES = [
    {"agent": "Market Analyst",  "ts": time.time()-30, "cycle": 1, "decision": "bullish",
     "detail": "Favour established lending protocols with stable TVL.",
     "meta": {"opportunities": 6, "source": "DeFiLlama", "top_protocol": "Aave V3", "top_apy": 6.2}},
    {"agent": "Strategy Agent",  "ts": time.time()-28, "cycle": 1, "decision": "3 strategies generated (sentiment: bullish)",
     "detail": "Prioritises capital safety with established lending protocols.",
     "meta": {"conservative_apy": 6.6, "balanced_apy": 7.1, "aggressive_apy": 9.8, "xaut_hedge": False}},
    {"agent": "Risk Manager",    "ts": time.time()-25, "cycle": 1, "decision": "approved",
     "detail": "Balanced strategy passes all hard rules. Claude qualitative review: diversified across lending and stable-swap with no concentration risk.",
     "meta": {"selected": "Balanced", "flags": [], "capital_preservation": False}},
    {"agent": "Simulator",       "ts": time.time()-22, "cycle": 1, "decision": "approved",
     "detail": "$1,132.00 net return over 7 days | gas: $12.50",
     "meta": {"projected_apy": 7.1, "net_return": 1132.0, "confidence": 0.91, "gas_usd": 12.5}},
    {"agent": "Execution Agent", "ts": time.time()-18, "cycle": 1, "decision": "3 transactions executed",
     "detail": "Trigger: scheduled | gas: $12.50",
     "meta": {"tx_count": 3, "trigger": "scheduled", "gas_usd": 12.5, "portfolio": 100000.0}},
]

_DEMO_YIELD_EVENTS = [
    {"ts": time.time()-15, "cycle": 1, "projected_yield_usd": 95.21, "threshold_usd": 50,
     "to": "0xYourBeneficiary", "tx_hash": "0xpay1" + "0"*59, "status": "confirmed", "trigger": "threshold_crossed"},
]


def _get_orchestrator():
    """Retrieve the shared Orchestrator instance stored on the app."""
    return current_app.config.get("ORCHESTRATOR")


# ── Blueprint ─────────────────────────────────────────────────────────────────

api = Blueprint("api", __name__, url_prefix="/api")


@api.route("/status")
def status():
    try:
        orch = _get_orchestrator()
        if orch is None:
            # Return demo status when orchestrator not running
            return _ok({
                "system_state": "IDLE",
                "cycle_count": 0,
                "demo_mode": True,
                "uptime_seconds": 0,
                "wallet": {
                    "address": "0x0000000000000000000000000000000000000000",
                    "total_value_usd": 1000.0,
                    "idle_usdt": 0.0,
                    "xaut_usd": 150.0,
                    "allocations": {"Aave V3": 350.0, "Curve Finance": 250.0, "Compound V3": 250.0},
                    "pnl_usd": 2.34,
                    "pnl_pct": 0.234,
                },
                "last_market_report": {"sentiment": "bullish", "opportunities": 6, "source": "mock"},
                "last_strategy": _DEMO_STRATEGIES[1],
                "last_simulation": {"approved": True, "projected_apy": 7.1, "net_return": 1.32, "confidence": 0.91},
                "last_execution": {"trigger": "scheduled", "tx_count": 3, "gas_usd": 45.0},
                "agent_errors": {},
                "recent_runs": [],
            })
        data = orch.get_system_status()
        data["uptime_seconds"] = round(time.time() - current_app.config.get("START_TIME", time.time()), 1)
        return _ok(data)
    except Exception as exc:
        logger.error(f"[API] /status error: {exc}")
        return _err(str(exc))


@api.route("/portfolio")
def portfolio():
    try:
        orch = _get_orchestrator()
        if orch is None:
            return _ok({
                "total_value_usd": 1002.34,
                "idle_usdt": 2.34,
                "xaut_usd": 150.0,
                "allocations": {"Aave V3": 350.0, "Curve Finance": 250.0, "Compound V3": 250.0, "Yearn Finance": 0.0},
                "pnl_usd": 2.34,
                "pnl_pct": 0.234,
                "timestamp": time.time(),
            })
        snap = orch._wallet.get_portfolio_snapshot()
        return _ok(snap.model_dump())
    except Exception as exc:
        logger.error(f"[API] /portfolio error: {exc}")
        return _err(str(exc))


@api.route("/opportunities")
def opportunities():
    try:
        orch = _get_orchestrator()
        if orch is None or orch._last_market_report is None:
            return _ok({
                "source": "demo",
                "sentiment": "bullish",
                "recommended_focus": "Favour established lending protocols with stable TVL.",
                "opportunities": _DEMO_OPPORTUNITIES,
                "count": len(_DEMO_OPPORTUNITIES),
            })
        report = orch._last_market_report
        opps = [
            {
                "rank":                ro.rank,
                "protocol":           ro.opportunity.protocol,
                "symbol":             ro.opportunity.symbol,
                "apy":                ro.opportunity.apy,
                "tvl_usd":            ro.opportunity.tvl_usd,
                "volatility_7d":      ro.opportunity.volatility_7d,
                "pool_type":          ro.opportunity.pool_type,
                "chain":              ro.opportunity.chain,
                "risk_adjusted_score": ro.risk_adjusted_score,
                "rationale":          ro.rationale,
            }
            for ro in report.top_opportunities
        ]
        return _ok({
            "source":            report.data_source,
            "sentiment":         report.market_sentiment,
            "recommended_focus": report.recommended_focus,
            "opportunities":     opps,
            "count":             len(opps),
        })
    except Exception as exc:
        logger.error(f"[API] /opportunities error: {exc}")
        return _err(str(exc))


@api.route("/strategies")
def strategies():
    try:
        orch = _get_orchestrator()
        if orch is None or orch._last_strategy_bundle is None:
            selected = _DEMO_STRATEGIES[1].copy()
            selected["selected"] = True
            selected["risk_flags"] = []
            return _ok({
                "strategies": [
                    {**s, "selected": s["name"] == "Balanced", "risk_flags": []}
                    for s in _DEMO_STRATEGIES
                ],
                "selected_strategy": selected,
                "sentiment": "bullish",
            })
        bundle = orch._last_strategy_bundle
        assessment = orch._last_risk_assessment
        selected_name = assessment.selected_strategy.name if assessment else None
        flags = assessment.risk_flags if assessment else []

        def _fmt(s):
            return {
                "name":           s.name,
                "allocations":    s.allocations,
                "expected_yield": s.expected_yield,
                "risk_score":     s.risk_score,
                "rationale":      s.rationale,
                "selected":       s.name == selected_name,
                "risk_flags":     flags if s.name == selected_name else [],
            }

        strategies_list = [_fmt(s) for s in bundle.as_list()]
        selected_data = next((s for s in strategies_list if s["selected"]), strategies_list[0])
        return _ok({
            "strategies":        strategies_list,
            "selected_strategy": selected_data,
            "sentiment":         bundle.based_on_sentiment,
        })
    except Exception as exc:
        logger.error(f"[API] /strategies error: {exc}")
        return _err(str(exc))


@api.route("/transactions")
def transactions():
    try:
        page     = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 20))
        offset   = (page - 1) * per_page

        orch = _get_orchestrator()
        if orch is None:
            now = time.time()
            demo_txs = [
                {**tx, "timestamp": now - (i * 300), "from_token": "USDT", "to_token": "USDT"}
                for i, tx in enumerate(_DEMO_TRANSACTIONS)
            ]
            paginated = demo_txs[offset: offset + per_page]
            return _ok({
                "transactions": paginated,
                "total": len(demo_txs),
                "page": page,
                "per_page": per_page,
                "pages": max(1, (len(demo_txs) + per_page - 1) // per_page),
            })

        all_txs = orch._wallet.tx_history_db(limit=500)
        paginated = all_txs[offset: offset + per_page]
        return _ok({
            "transactions": paginated,
            "total":    len(all_txs),
            "page":     page,
            "per_page": per_page,
            "pages":    max(1, (len(all_txs) + per_page - 1) // per_page),
        })
    except Exception as exc:
        logger.error(f"[API] /transactions error: {exc}")
        return _err(str(exc))


@api.route("/guardrails")
def guardrails():
    try:
        return _ok({
            "max_protocol_allocation_pct": config.max_protocol_allocation * 100,
            "min_tvl_usd":                 config.min_liquidity_usd,
            "max_risk_score":              8,
            "max_volatility_pct":          config.max_volatility_threshold * 100,
            "emergency_exit_tvl_usd":      5_000_000,
            "yield_drop_trigger_pct":      20,
            "drift_trigger_pct":           10,
            "yield_payout_address":        config.yield_payout_address or None,
            "yield_payout_threshold_usd":  config.yield_payout_threshold_usd,
            "xaut_hedge":                  "10–20% when sentiment is bearish/volatile",
            "capital_preservation":        "Activated if all strategies fail risk checks",
        })
    except Exception as exc:
        return _err(str(exc))


@api.route("/metrics")
def metrics():
    try:
        orch = _get_orchestrator()

        if orch is None:
            return _ok({
                "current_apy":    7.1,
                "pnl_24h_usd":    0.19,
                "pnl_24h_pct":    0.019,
                "pnl_7d_usd":     1.32,
                "pnl_7d_pct":     0.132,
                "total_return_usd": 2.34,
                "total_return_pct": 0.234,
                "total_value_usd":  1002.34,
                "initial_capital":  1000.0,
                "simulations_run":  1,
                "executions_run":   1,
                "cycle_count":      1,
            })

        snap = orch._wallet.get_portfolio_snapshot()
        sim  = orch._last_simulation
        runs = orch._db.recent_runs(30)

        current_apy = sim.projected_apy if sim else 0.0

        # Derive PnL windows from orchestrator run history
        now = time.time()
        def _pnl_over(seconds: float) -> float:
            cutoff = now - seconds
            relevant = [r for r in runs if r.get("started_at", 0) >= cutoff and r.get("portfolio_value_usd")]
            if not relevant:
                return 0.0
            earliest_val = relevant[-1].get("portfolio_value_usd", snap.total_value_usd)
            return round(snap.total_value_usd - earliest_val, 4)

        pnl_24h = _pnl_over(86_400)
        pnl_7d  = _pnl_over(604_800)
        initial  = orch._wallet._initial_capital

        return _ok({
            "current_apy":        current_apy,
            "pnl_24h_usd":        pnl_24h,
            "pnl_24h_pct":        round(pnl_24h / initial * 100, 4) if initial else 0,
            "pnl_7d_usd":         pnl_7d,
            "pnl_7d_pct":         round(pnl_7d / initial * 100, 4) if initial else 0,
            "total_return_usd":   snap.pnl_usd,
            "total_return_pct":   snap.pnl_pct,
            "total_value_usd":    snap.total_value_usd,
            "initial_capital":    initial,
            "simulations_run":    len(runs),
            "executions_run":     len([r for r in runs if "executed" in (r.get("final_action") or "")]),
            "cycle_count":        orch._cycle_count,
        })
    except Exception as exc:
        logger.error(f"[API] /metrics error: {exc}")
        return _err(str(exc))


@api.route("/agent-traces")
def agent_traces():
    try:
        orch = _get_orchestrator()
        traces = list(reversed(orch._agent_traces[-20:])) if orch else _DEMO_AGENT_TRACES
        return _ok(traces)
    except Exception as exc:
        return _err(str(exc))


@api.route("/yield-events")
def yield_events():
    try:
        orch = _get_orchestrator()
        events = list(reversed(orch._yield_payments)) if orch else _DEMO_YIELD_EVENTS
        return _ok(events)
    except Exception as exc:
        return _err(str(exc))


@api.route("/control", methods=["POST"])
def control():
    try:
        orch = _get_orchestrator()
        action = (request.get_json(silent=True) or {}).get("action", "")
        if orch:
            if action == "pause":
                orch.pause()
            elif action == "resume":
                orch.resume()
            elif action == "stop":
                orch.stop()
        return _ok({"action": action, "applied": orch is not None})
    except Exception as exc:
        return _err(str(exc))


# ── SocketIO WebSocket feed ───────────────────────────────────────────────────

def register_socketio_events(socketio: SocketIO) -> None:
    """Register all SocketIO event handlers."""

    @socketio.on("connect", namespace="/ws/feed")
    def on_connect():
        logger.info("[API] WebSocket client connected")
        orch = _get_orchestrator()
        if orch:
            status_data = orch.get_system_status()
        else:
            status_data = {"system_state": "IDLE", "demo_mode": True}
        emit("connected", {"success": True, "initial_state": status_data})

    @socketio.on("disconnect", namespace="/ws/feed")
    def on_disconnect():
        logger.info("[API] WebSocket client disconnected")

    @socketio.on("ping", namespace="/ws/feed")
    def on_ping():
        emit("pong", {"ts": time.time()})


def start_event_forwarder(socketio: SocketIO, app) -> None:
    """
    Background thread that drains the orchestrator's event bus and
    forwards each event to all connected WebSocket clients.
    """
    def _forward():
        import asyncio

        async def _drain():
            while True:
                try:
                    with app.app_context():
                        orch = app.config.get("ORCHESTRATOR")
                    if orch is None:
                        await asyncio.sleep(1)
                        continue
                    try:
                        event = await asyncio.wait_for(orch.event_bus.get(), timeout=0.5)
                        socketio.emit(
                            event.get("type", "event"),
                            {"payload": event.get("payload"), "ts": event.get("ts")},
                            namespace="/ws/feed",
                        )
                    except asyncio.TimeoutError:
                        pass
                except Exception as exc:
                    logger.debug(f"[API] Event forwarder: {exc}")
                    await asyncio.sleep(1)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_drain())

    t = threading.Thread(target=_forward, daemon=True, name="event-forwarder")
    t.start()
