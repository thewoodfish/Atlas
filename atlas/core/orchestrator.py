"""
Orchestrator for Atlas.

Connects all agents in sequence:
    MarketAnalyst → StrategyAgent → RiskManager → Simulator → ExecutionAgent

Architecture
------------
- One shared asyncio.Queue per agent-pair (or a single broadcast bus)
- Clean async state machine with explicit states
- WebSocket-compatible event bus (asyncio.Queue of JSON-serialisable dicts)
- Graceful error handling: failed agent cycle retries after 30 s
- Every loop iteration persisted to SQLite
- get_system_status() for live dashboard queries

States
------
IDLE → SCANNING → STRATEGIZING → RISK_CHECK → SIMULATING → EXECUTING
     → MONITORING → REBALANCING → IDLE (repeat)

All log lines are prefixed with [ORCHESTRATOR].
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from enum import Enum
from typing import Any, Optional

from loguru import logger
from sqlalchemy import create_engine, text

from atlas.agents.execution_agent import ExecutionAgent
from atlas.agents.market_analyst import MarketAnalystAgent
from atlas.agents.risk_manager import RiskManagerAgent
from atlas.agents.strategy_agent import StrategyAgent
from atlas.core.simulator import Simulator
from atlas.core.wallet import WDKWallet
from atlas.data.models import (
    ExecutionReport,
    MarketReport,
    RiskAssessment,
    SimulationResult,
    StrategyBundle,
)
from config import config

# ── State machine ─────────────────────────────────────────────────────────────

class SystemState(str, Enum):
    IDLE         = "IDLE"
    SCANNING     = "SCANNING"
    STRATEGIZING = "STRATEGIZING"
    RISK_CHECK   = "RISK_CHECK"
    SIMULATING   = "SIMULATING"
    EXECUTING    = "EXECUTING"
    MONITORING   = "MONITORING"
    REBALANCING  = "REBALANCING"
    ERROR        = "ERROR"


RETRY_DELAY_SECONDS = 30
LOOP_INTERVAL_SECONDS = 60       # minimum time between full cycles (live mode)
DEMO_LOOP_INTERVAL_SECONDS = 5   # fast loop in demo mode so cycle 2 fires quickly
AGENT_TIMEOUT_SECONDS = 60       # max seconds to wait for any single agent/LLM call

# ── SQLite persistence ────────────────────────────────────────────────────────

_CREATE_LOOP_TABLE = """
CREATE TABLE IF NOT EXISTS orchestrator_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at          REAL    NOT NULL,
    finished_at         REAL,
    state_transitions   TEXT,   -- JSON list
    final_action        TEXT,
    portfolio_value_usd REAL,
    error               TEXT,
    demo                INTEGER DEFAULT 0
)
"""


class _OrchestratorDB:
    def __init__(self, url: str) -> None:
        self._engine = create_engine(url, echo=False, future=True)
        with self._engine.connect() as conn:
            conn.execute(text(_CREATE_LOOP_TABLE))
            conn.commit()

    def save_run(self, run: dict) -> None:
        with self._engine.connect() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO orchestrator_runs
                        (started_at, finished_at, state_transitions,
                         final_action, portfolio_value_usd, error, demo)
                    VALUES
                        (:started_at, :finished_at, :state_transitions,
                         :final_action, :portfolio_value_usd, :error, :demo)
                    """
                ),
                run,
            )
            conn.commit()

    def recent_runs(self, limit: int = 10) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM orchestrator_runs "
                    "ORDER BY started_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()
        return [dict(r._mapping) for r in rows]


# ── Orchestrator ──────────────────────────────────────────────────────────────

class Orchestrator:
    """
    Master coordinator for all Atlas agents.

    Parameters
    ----------
    demo : bool
        If True, triggers a mid-run market condition change to demonstrate
        auto-rebalancing.
    loop_interval : int
        Minimum seconds between full scan→execute cycles.
    """

    def __init__(
        self,
        demo: bool = False,
        loop_interval: int | None = None,
        max_cycles: int | None = None,
    ) -> None:
        self.demo = demo
        self.max_cycles = max_cycles
        self._loop_interval = (
            loop_interval
            if loop_interval is not None
            else (DEMO_LOOP_INTERVAL_SECONDS if demo else LOOP_INTERVAL_SECONDS)
        )

        # Shared state
        self._state = SystemState.IDLE
        self._state_history: list[str] = []
        self._cycle_count = 0
        self._last_market_report: Optional[MarketReport] = None
        self._last_strategy_bundle: Optional[StrategyBundle] = None
        self._last_risk_assessment: Optional[RiskAssessment] = None
        self._last_simulation: Optional[SimulationResult] = None
        self._last_execution_report: Optional[ExecutionReport] = None
        self._agent_errors: dict[str, str] = {}

        # In demo mode, wipe any stale database so the dashboard starts clean
        if demo and config.database_url.startswith("sqlite:///"):
            db_path = config.database_url.replace("sqlite:///", "", 1)
            if os.path.exists(db_path):
                os.remove(db_path)
                logger.info(f"[ORCHESTRATOR] Demo mode: removed stale database {db_path!r}")

        # Infrastructure — WDKWallet connects to the Node.js WDK microservice
        # and degrades gracefully to MockWallet accounting if the service is offline
        self._wallet = WDKWallet()
        self._simulator = Simulator()
        self._db = _OrchestratorDB(config.database_url)

        # Event bus — broadcast to dashboard / WebSocket subscribers
        self._event_bus: asyncio.Queue = asyncio.Queue(maxsize=500)

        # Per-agent queues (not used for direct calls below, but available
        # for running agents in concurrent mode)
        self._main_queue: asyncio.Queue = asyncio.Queue()

        # Agent instances (share the wallet and event bus)
        self._market_analyst = MarketAnalystAgent(
            event_queue=self._main_queue,
            poll_interval=config.scan_interval_seconds,
        )
        self._strategy_agent = StrategyAgent(event_queue=self._main_queue)
        self._risk_manager   = RiskManagerAgent(event_queue=self._main_queue)
        self._execution_agent = ExecutionAgent(
            event_queue=self._main_queue,
            wallet=self._wallet,
        )

        self._running = False

    # ── State helpers ─────────────────────────────────────────────────────────

    def _set_state(self, state: SystemState) -> None:
        self._state = state
        self._state_history.append(state.value)
        logger.info(f"[ORCHESTRATOR] ── {state.value}")
        self._emit_event("state_change", {"state": state.value})

    def _emit_event(self, event_type: str, payload: Any = None) -> None:
        """Put a JSON-serialisable event on the broadcast bus (non-blocking)."""
        event = {
            "type": event_type,
            "payload": payload,
            "ts": time.time(),
        }
        try:
            self._event_bus.put_nowait(event)
        except asyncio.QueueFull:
            # Drop oldest event to make room
            try:
                self._event_bus.get_nowait()
                self._event_bus.put_nowait(event)
            except Exception:
                pass

    # ── Agent steps (direct calls, not queue-mediated) ────────────────────────

    async def _step_scan(self) -> MarketReport:
        self._set_state(SystemState.SCANNING)
        report = await asyncio.wait_for(
            self._market_analyst.run_once(), timeout=AGENT_TIMEOUT_SECONDS
        )
        self._last_market_report = report
        self._risk_manager.market_report = report
        # Keep execution agent's opportunity list fresh
        opps = [ro.opportunity for ro in report.top_opportunities]
        self._execution_agent.update_opportunities(opps)
        self._emit_event("market_report", {
            "sentiment": report.market_sentiment,
            "opportunities": len(report.top_opportunities),
            "source": report.data_source,
        })
        return report

    async def _step_strategize(self, report: MarketReport) -> StrategyBundle:
        self._set_state(SystemState.STRATEGIZING)
        bundle = await asyncio.wait_for(
            self._strategy_agent.process(report), timeout=AGENT_TIMEOUT_SECONDS
        )
        self._last_strategy_bundle = bundle
        self._emit_event("strategy_bundle", {
            "conservative_yield": bundle.conservative.expected_yield,
            "balanced_yield":     bundle.balanced.expected_yield,
            "aggressive_yield":   bundle.aggressive.expected_yield,
        })
        return bundle

    async def _step_risk_check(self, bundle: StrategyBundle) -> RiskAssessment:
        self._set_state(SystemState.RISK_CHECK)
        assessment = await asyncio.wait_for(
            self._risk_manager.process(bundle), timeout=AGENT_TIMEOUT_SECONDS
        )
        self._last_risk_assessment = assessment
        self._emit_event("risk_assessment", {
            "approved":             assessment.approved,
            "selected_strategy":    assessment.selected_strategy.name,
            "risk_flags":           assessment.risk_flags,
            "is_capital_preservation": assessment.is_capital_preservation,
        })
        return assessment

    async def _step_simulate(
        self,
        assessment: RiskAssessment,
        report: MarketReport,
    ) -> SimulationResult:
        self._set_state(SystemState.SIMULATING)
        opps = [ro.opportunity for ro in report.top_opportunities]
        simulation = self._simulator.run(
            assessment,
            opportunities=opps,
            data_source=report.data_source,
        )
        self._last_simulation = simulation
        self._emit_event("simulation_result", {
            "approved":        simulation.approved,
            "net_return":      simulation.net_return,
            "projected_apy":   simulation.projected_apy,
            "confidence":      simulation.confidence_score,
        })
        return simulation

    async def _step_execute(
        self,
        assessment: RiskAssessment,
        simulation: SimulationResult,
        report: MarketReport,
    ) -> ExecutionReport:
        self._set_state(SystemState.EXECUTING)
        opps = [ro.opportunity for ro in report.top_opportunities]
        exec_report = await asyncio.wait_for(
            self._execution_agent.execute(assessment, simulation, opps),
            timeout=AGENT_TIMEOUT_SECONDS,
        )
        self._last_execution_report = exec_report
        snap = exec_report.new_portfolio_snapshot
        self._emit_event("execution_report", {
            "trigger":        exec_report.trigger,
            "tx_count":       len(exec_report.transactions),
            "gas_usd":        exec_report.total_gas_used,
            "portfolio_value": snap.total_value_usd if snap else None,
            "pnl_usd":        snap.pnl_usd if snap else None,
            "pnl_pct":        snap.pnl_pct if snap else None,
        })
        return exec_report

    # ── Yield payout ───────────────────────────────────────────────────────────

    async def _step_pay_yield(self, projected_yield_usd: float) -> None:
        """
        If projected yield exceeds the configured threshold, autonomously pay
        it out to the beneficiary address via WDK send_usdt.
        This demonstrates agent-driven conditional payment logic.
        """
        payout_address = config.yield_payout_address
        threshold = config.yield_payout_threshold_usd

        if not payout_address:
            return  # no beneficiary configured

        if projected_yield_usd < threshold:
            logger.debug(
                f"[ORCHESTRATOR] Projected yield ${projected_yield_usd:.2f} "
                f"below payout threshold ${threshold:.2f} — no payment"
            )
            return

        logger.info(
            f"[ORCHESTRATOR] Yield threshold crossed: "
            f"${projected_yield_usd:.2f} ≥ ${threshold:.2f} — "
            f"paying out to {payout_address}"
        )
        try:
            tx = self._wallet.pay_yield(payout_address, round(projected_yield_usd, 2))
            self._emit_event("yield_payment", {
                "amount_usd":  round(projected_yield_usd, 2),
                "to":          payout_address,
                "tx_hash":     tx.tx_hash,
                "trigger":     "threshold_crossed",
                "threshold":   threshold,
            })
            logger.info(
                f"[ORCHESTRATOR] Yield payment sent — "
                f"${projected_yield_usd:.2f} USDT → {payout_address}  "
                f"hash={tx.tx_hash[:18]}…"
            )
        except Exception as exc:
            logger.error(f"[ORCHESTRATOR] Yield payment failed: {exc}")

    # ── Demo scenario ──────────────────────────────────────────────────────────

    async def _inject_demo_shock(self) -> None:
        """
        Simulate a market condition change mid-run:
        Drops Curve Finance APY to 1% and TVL to $4M to trigger both
        a yield-drop and an emergency exit on the next monitor cycle.
        """
        logger.warning(
            "[ORCHESTRATOR] DEMO: injecting market shock — "
            "Curve Finance APY → 1%, TVL → $4M"
        )
        if self._last_market_report:
            for ro in self._last_market_report.top_opportunities:
                if "curve" in ro.opportunity.protocol.lower():
                    object.__setattr__(ro.opportunity, "apy", 1.0)
                    object.__setattr__(ro.opportunity, "tvl_usd", 4_000_000)
            opps = [ro.opportunity for ro in self._last_market_report.top_opportunities]
            self._execution_agent.update_opportunities(opps)
            self._emit_event("demo_shock", {
                "protocol": "Curve Finance",
                "new_apy": 1.0,
                "new_tvl_usd": 4_000_000,
            })

    # ── Full cycle ─────────────────────────────────────────────────────────────

    async def _run_cycle(self) -> dict:
        """Execute one full scan → execute cycle. Returns run metadata."""
        started_at = time.time()
        self._cycle_count += 1
        self._state_history = []
        final_action = "none"
        error_msg = None
        portfolio_value = self._wallet.get_balance()

        logger.info(
            f"[ORCHESTRATOR] ══ Cycle #{self._cycle_count} starting "
            f"(demo={self.demo}) ══"
        )

        try:
            # 1. Scan
            report = await self._step_scan()

            # 2. Strategize
            bundle = await self._step_strategize(report)

            # 3. Risk check
            assessment = await self._step_risk_check(bundle)

            # 4. Simulate
            simulation = await self._step_simulate(assessment, report)

            if not simulation.approved:
                logger.warning(
                    f"[ORCHESTRATOR] Simulation rejected for "
                    f"'{assessment.selected_strategy.name}' — skipping execution"
                )
                final_action = "simulation_rejected"
            else:
                # 5. Execute
                exec_report = await self._step_execute(assessment, simulation, report)
                snap = exec_report.new_portfolio_snapshot
                portfolio_value = snap.total_value_usd if snap else portfolio_value
                final_action = f"executed:{exec_report.trigger}"

                # 6. Autonomous yield payout (agent-driven conditional payment)
                await self._step_pay_yield(simulation.projected_7d_yield)

            # 8. Monitor state
            self._set_state(SystemState.MONITORING)

            # Demo: inject shock on cycle 2
            if self.demo and self._cycle_count == 2:
                await self._inject_demo_shock()
                monitor_report = await self._execution_agent.monitor_once()
                if monitor_report:
                    self._set_state(SystemState.REBALANCING)
                    self._last_execution_report = monitor_report
                    snap = monitor_report.new_portfolio_snapshot
                    portfolio_value = snap.total_value_usd if snap else portfolio_value
                    final_action = f"rebalanced:{monitor_report.trigger}"
                    self._emit_event("execution_report", {
                        "trigger":        monitor_report.trigger,
                        "tx_count":       len(monitor_report.transactions),
                        "gas_usd":        monitor_report.total_gas_used,
                        "portfolio_value": portfolio_value,
                    })

        except Exception as exc:
            error_msg = str(exc)
            logger.error(f"[ORCHESTRATOR] Cycle #{self._cycle_count} error: {exc}")
            self._set_state(SystemState.ERROR)
            self._emit_event("error", {"message": error_msg, "cycle": self._cycle_count})

        finished_at = time.time()
        run = {
            "started_at":          started_at,
            "finished_at":         finished_at,
            "state_transitions":   json.dumps(self._state_history),
            "final_action":        final_action,
            "portfolio_value_usd": portfolio_value,
            "error":               error_msg,
            "demo":                int(self.demo),
        }
        self._db.save_run(run)

        elapsed = round(finished_at - started_at, 2)
        logger.info(
            f"[ORCHESTRATOR] ══ Cycle #{self._cycle_count} complete in {elapsed}s "
            f"— action={final_action} portfolio=${portfolio_value:,.2f} ══"
        )
        self._set_state(SystemState.IDLE)
        return run

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Run the orchestration loop continuously until stopped."""
        self._running = True
        logger.info(
            f"[ORCHESTRATOR] Starting — loop_interval={self._loop_interval}s  "
            f"demo={self.demo}"
        )
        self._emit_event("system_start", {
            "wallet": self._wallet.address,
            "capital": self._wallet.get_balance(),
            "demo": self.demo,
        })

        while self._running:
            if self.max_cycles and self._cycle_count >= self.max_cycles:
                logger.info(f"[ORCHESTRATOR] Reached max_cycles={self.max_cycles} — stopping.")
                break

            cycle_start = time.monotonic()
            retry_count = 0

            while True:
                try:
                    await self._run_cycle()
                    break  # success
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    retry_count += 1
                    logger.error(
                        f"[ORCHESTRATOR] Unhandled cycle error (attempt {retry_count}): "
                        f"{exc} — retrying in {RETRY_DELAY_SECONDS}s"
                    )
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                    if retry_count >= 3:
                        logger.error(
                            "[ORCHESTRATOR] 3 consecutive failures — "
                            "waiting full interval before next cycle"
                        )
                        break

            # Sleep remaining time in the loop interval
            elapsed = time.monotonic() - cycle_start
            sleep_for = max(0.0, self._loop_interval - elapsed)
            if sleep_for > 0 and self._running:
                logger.info(
                    f"[ORCHESTRATOR] Sleeping {sleep_for:.0f}s until next cycle"
                )
                await asyncio.sleep(sleep_for)

        logger.info("[ORCHESTRATOR] Stopped")
        self._emit_event("system_stop", {})

    def stop(self) -> None:
        self._running = False

    def get_system_status(self) -> dict:
        """
        Return a JSON-serialisable snapshot of the entire system state.
        Safe to call from any thread (e.g. the Flask dashboard).
        """
        snap = self._wallet.get_portfolio_snapshot()

        last_report_info = None
        if self._last_market_report:
            r = self._last_market_report
            last_report_info = {
                "sentiment":      r.market_sentiment,
                "opportunities":  len(r.top_opportunities),
                "source":         r.data_source,
                "timestamp":      r.timestamp,
            }

        last_strategy_info = None
        if self._last_risk_assessment:
            s = self._last_risk_assessment.selected_strategy
            last_strategy_info = {
                "name":            s.name,
                "allocations":     s.allocations,
                "expected_yield":  s.expected_yield,
                "risk_score":      s.risk_score,
                "risk_flags":      self._last_risk_assessment.risk_flags,
                "capital_preservation": self._last_risk_assessment.is_capital_preservation,
            }

        last_sim_info = None
        if self._last_simulation:
            sim = self._last_simulation
            last_sim_info = {
                "approved":       sim.approved,
                "projected_apy":  sim.projected_apy,
                "net_return":     sim.net_return,
                "confidence":     sim.confidence_score,
            }

        last_exec_info = None
        if self._last_execution_report:
            ex = self._last_execution_report
            last_exec_info = {
                "trigger":   ex.trigger,
                "tx_count":  len(ex.transactions),
                "gas_usd":   ex.total_gas_used,
                "timestamp": ex.timestamp,
            }

        # Fetch live on-chain balances from WDK service (best-effort)
        onchain = {}
        try:
            onchain = self._wallet.get_onchain_balances()
        except Exception:
            pass

        return {
            "system_state":      self._state.value,
            "cycle_count":       self._cycle_count,
            "demo_mode":         self.demo,
            "wallet": {
                "address":         self._wallet.address,
                "total_value_usd": snap.total_value_usd,
                "idle_usdt":       snap.idle_usdt,
                "xaut_usd":        snap.xaut_usd,
                "allocations":     snap.allocations,
                "pnl_usd":         snap.pnl_usd,
                "pnl_pct":         snap.pnl_pct,
                "onchain_balances": onchain,  # live ETH/USDT/XAUT from WDK
            },
            "last_market_report":    last_report_info,
            "last_strategy":         last_strategy_info,
            "last_simulation":       last_sim_info,
            "last_execution":        last_exec_info,
            "agent_errors":          self._agent_errors,
            "recent_runs":           self._db.recent_runs(5),
        }

    @property
    def event_bus(self) -> asyncio.Queue:
        """Dashboard/WebSocket consumers subscribe to this queue."""
        return self._event_bus
