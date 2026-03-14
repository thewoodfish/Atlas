"""
Execution Agent for Atlas.

Responsibilities
----------------
1. Receive an approved + simulated strategy from the queue
2. Execute portfolio rebalancing via the Wallet module:
   a. Calculate current vs target allocations
   b. Determine positions to reduce (over-allocated)
   c. Withdraw from over-allocated protocols
   d. Deposit into under-allocated protocols
3. Emit an ExecutionReport to the queue
4. Monitor open positions every 60 s for:
   - Yield drop > 20% → trigger rebalance
   - TVL < $5M        → emergency exit
   - Drift > 10% from target → trigger rebalance

All log lines are prefixed with [EXECUTION AGENT].
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from loguru import logger

from atlas.core.wallet import MockWallet
from atlas.data.models import (
    ExecutionReport,
    OpportunityModel,
    PortfolioSnapshot,
    RiskAssessment,
    SimulationResult,
    StrategyModel,
    TransactionRecord,
)
from config import config

# ── Monitor thresholds ────────────────────────────────────────────────────────

MONITOR_INTERVAL_SECONDS = 60
YIELD_DROP_THRESHOLD     = 0.20   # 20% relative drop triggers rebalance
EMERGENCY_TVL_USD        = 5_000_000
DRIFT_THRESHOLD_PCT      = 10.0   # absolute percentage-point drift

# Gas cost estimate per rebalance transaction (USD)
_GAS_PER_TX_USD = 15.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _allocation_drift(
    current: dict[str, float],   # protocol -> USD deployed
    target_pct: dict[str, float], # protocol -> target %
    total: float,
) -> dict[str, float]:
    """
    Return the drift (in percentage points) of each protocol's current
    allocation vs its target.  Positive = over-allocated.
    """
    drifts: dict[str, float] = {}
    for protocol, target in target_pct.items():
        current_pct = (current.get(protocol, 0.0) / total * 100) if total else 0.0
        drifts[protocol] = round(current_pct - target, 4)
    return drifts


def _rebalance_steps(
    current_usd: dict[str, float],
    target_pct: dict[str, float],
    total: float,
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """
    Compute ordered withdraw / deposit steps to reach target allocations.

    Returns
    -------
    withdrawals : list of (protocol, amount_usd) — over-allocated protocols
    deposits    : list of (protocol, amount_usd) — under-allocated protocols
    """
    withdrawals: list[tuple[str, float]] = []
    deposits:    list[tuple[str, float]] = []

    for protocol, target in target_pct.items():
        target_usd = total * target / 100
        current    = current_usd.get(protocol, 0.0)
        diff       = round(current - target_usd, 4)
        if diff > 0.01:
            withdrawals.append((protocol, diff))
        elif diff < -0.01:
            deposits.append((protocol, abs(diff)))

    # Also withdraw from protocols not in target
    for protocol, amount in current_usd.items():
        if protocol not in target_pct and amount > 0.01:
            withdrawals.append((protocol, amount))

    return withdrawals, deposits


# ── Agent ─────────────────────────────────────────────────────────────────────

class ExecutionAgent:
    """
    Executes approved strategies against the MockWallet and monitors
    positions for drift / yield drops / emergency TVL conditions.

    Parameters
    ----------
    event_queue : asyncio.Queue
        Shared queue. Consumes ``simulation_result`` events
        (which carry the RiskAssessment payload too) and emits
        ``execution_report`` events.
    wallet : MockWallet
        Shared wallet instance (injected by the Orchestrator).
    """

    def __init__(
        self,
        event_queue: asyncio.Queue,
        wallet: MockWallet,
    ) -> None:
        self._queue  = event_queue
        self._wallet = wallet
        self._running = False

        # Latest approved strategy — used by the monitor loop
        self._target_pct: dict[str, float] = {}
        self._strategy_name: str = ""

        # Latest opportunity snapshot — used for TVL / yield checks
        self._opportunities: list[OpportunityModel] = []
        # Baseline APY per protocol (captured at execution time)
        self._baseline_apy: dict[str, float] = {}

    # ── Execution logic ───────────────────────────────────────────────────────

    def _execute_rebalance(
        self,
        target_pct: dict[str, float],
        trigger: str = "scheduled",
    ) -> ExecutionReport:
        """
        Rebalance the wallet to match target_pct allocations.
        Returns an ExecutionReport.
        """
        t_start = time.time()
        txs: list[TransactionRecord] = []
        skipped: list[str] = []

        snap_before = self._wallet.get_portfolio_snapshot()
        total = snap_before.total_value_usd
        current_usd = dict(snap_before.allocations)
        # Include idle USDT in current as "IDLE"
        if snap_before.idle_usdt > 0.01:
            current_usd["__idle__"] = snap_before.idle_usdt

        withdrawals, deposits = _rebalance_steps(current_usd, target_pct, total)

        logger.info(
            f"[EXECUTION AGENT] Rebalancing ({trigger}) — "
            f"{len(withdrawals)} withdrawals, {len(deposits)} deposits"
        )

        # Step 1: Withdrawals (free up capital first)
        for protocol, amount in withdrawals:
            if protocol == "__idle__":
                continue
            try:
                tx = self._wallet.withdraw(protocol, amount)
                txs.append(tx)
                logger.info(
                    f"[EXECUTION AGENT] Withdrew ${amount:,.2f} from {protocol}"
                )
            except Exception as exc:
                logger.warning(
                    f"[EXECUTION AGENT] Withdraw from {protocol} failed: {exc}"
                )
                skipped.append(protocol)

        # Step 2: Deposits
        for protocol, amount in deposits:
            # Check TVL guard before depositing
            tvl = self._tvl_for(protocol)
            if tvl < EMERGENCY_TVL_USD:
                logger.warning(
                    f"[EXECUTION AGENT] Skipping deposit to {protocol} — "
                    f"TVL=${tvl/1e6:.2f}M below emergency threshold"
                )
                skipped.append(protocol)
                continue
            try:
                tx = self._wallet.deposit(protocol, amount)
                txs.append(tx)
                logger.info(
                    f"[EXECUTION AGENT] Deposited ${amount:,.2f} into {protocol}"
                )
            except Exception as exc:
                logger.warning(
                    f"[EXECUTION AGENT] Deposit to {protocol} failed: {exc}"
                )
                skipped.append(protocol)

        snap_after = self._wallet.get_portfolio_snapshot()
        elapsed_ms = round((time.time() - t_start) * 1000, 2)
        gas_used   = round(len(txs) * _GAS_PER_TX_USD, 2)

        report = ExecutionReport(
            strategy_name=self._strategy_name,
            transactions=txs,
            new_portfolio_snapshot=snap_after,
            execution_time_ms=elapsed_ms,
            total_gas_used=gas_used,
            skipped_protocols=list(set(skipped)),
            trigger=trigger,
        )

        logger.info(
            f"[EXECUTION AGENT] Execution complete — "
            f"{len(txs)} txs  gas=${gas_used:.2f}  "
            f"elapsed={elapsed_ms:.0f}ms  "
            f"portfolio=${snap_after.total_value_usd:,.2f}  "
            f"pnl=${snap_after.pnl_usd:+.2f} ({snap_after.pnl_pct:+.2f}%)"
        )
        return report

    # ── Monitor logic ─────────────────────────────────────────────────────────

    def _tvl_for(self, protocol: str) -> float:
        for opp in self._opportunities:
            if opp.protocol == protocol:
                return opp.tvl_usd
        return float("inf")  # unknown → assume safe

    def _current_apy_for(self, protocol: str) -> Optional[float]:
        for opp in self._opportunities:
            if opp.protocol == protocol:
                return opp.apy
        return None

    def _check_thresholds(self) -> Optional[str]:
        """
        Inspect open positions against monitor thresholds.
        Returns a trigger string if action is needed, else None.
        """
        if not self._target_pct:
            return None

        snap = self._wallet.get_portfolio_snapshot()
        total = snap.total_value_usd

        for protocol, deployed_usd in snap.allocations.items():
            # Emergency TVL check
            tvl = self._tvl_for(protocol)
            if tvl < EMERGENCY_TVL_USD:
                logger.warning(
                    f"[EXECUTION AGENT] EMERGENCY: {protocol} TVL=${tvl/1e6:.2f}M — "
                    "triggering exit"
                )
                return "emergency"

            # Yield drop check
            baseline = self._baseline_apy.get(protocol)
            current_apy = self._current_apy_for(protocol)
            if baseline and current_apy is not None:
                drop = (baseline - current_apy) / baseline
                if drop > YIELD_DROP_THRESHOLD:
                    logger.warning(
                        f"[EXECUTION AGENT] Yield drop on {protocol}: "
                        f"{baseline:.1f}% → {current_apy:.1f}% "
                        f"({drop * 100:.0f}% drop)"
                    )
                    return "yield_drop"

        # Drift check
        drifts = _allocation_drift(snap.allocations, self._target_pct, total)
        for protocol, drift in drifts.items():
            if abs(drift) > DRIFT_THRESHOLD_PCT:
                logger.warning(
                    f"[EXECUTION AGENT] Drift on {protocol}: "
                    f"{drift:+.1f}pp vs target"
                )
                return "drift"

        return None

    # ── Public API ────────────────────────────────────────────────────────────

    async def execute(
        self,
        assessment: RiskAssessment,
        simulation: SimulationResult,
        opportunities: list[OpportunityModel] | None = None,
    ) -> ExecutionReport:
        """
        Execute the approved strategy immediately.

        Parameters
        ----------
        assessment  : RiskAssessment with selected_strategy
        simulation  : SimulationResult (must be approved)
        opportunities : latest DeFi opportunity list for TVL/yield tracking
        """
        strategy = assessment.selected_strategy
        self._target_pct = dict(strategy.allocations)
        self._strategy_name = strategy.name
        self._opportunities = opportunities or []
        self._baseline_apy = {
            opp.protocol: opp.apy for opp in self._opportunities
        }

        if not simulation.approved:
            logger.warning(
                f"[EXECUTION AGENT] Simulation not approved for '{strategy.name}' "
                f"— skipping execution"
            )
            snap = self._wallet.get_portfolio_snapshot()
            return ExecutionReport(
                strategy_name=strategy.name,
                new_portfolio_snapshot=snap,
                trigger="skipped",
            )

        logger.info(
            f"[EXECUTION AGENT] Executing strategy '{strategy.name}'  "
            f"allocations={strategy.allocations}"
        )
        return self._execute_rebalance(self._target_pct, trigger="scheduled")

    async def monitor_once(self) -> Optional[ExecutionReport]:
        """
        Run one monitoring check.  Returns an ExecutionReport if a rebalance
        was triggered, else None.
        """
        trigger = self._check_thresholds()
        if trigger is None:
            logger.debug("[EXECUTION AGENT] Monitor check — all positions healthy")
            return None

        logger.info(f"[EXECUTION AGENT] Monitor triggered rebalance: {trigger}")

        # For emergency, withdraw everything to idle
        if trigger == "emergency":
            snap = self._wallet.get_portfolio_snapshot()
            emergency_target = {"__idle__": 100.0}
            # Withdraw all deployed positions
            txs = []
            for protocol, amount in list(snap.allocations.items()):
                if amount > 0.01:
                    try:
                        tx = self._wallet.withdraw(protocol, amount)
                        txs.append(tx)
                    except Exception as exc:
                        logger.error(
                            f"[EXECUTION AGENT] Emergency withdraw from "
                            f"{protocol} failed: {exc}"
                        )
            snap_after = self._wallet.get_portfolio_snapshot()
            report = ExecutionReport(
                strategy_name=self._strategy_name + " [EMERGENCY EXIT]",
                transactions=txs,
                new_portfolio_snapshot=snap_after,
                execution_time_ms=0.0,
                total_gas_used=round(len(txs) * _GAS_PER_TX_USD, 2),
                trigger="emergency",
            )
            self._target_pct = {}  # clear target so monitor quiets down
            return report

        # Drift or yield_drop → rebalance back to target
        return self._execute_rebalance(self._target_pct, trigger=trigger)

    async def run(self) -> None:
        """
        Main loop:
        - Consume ``simulation_result`` events → execute → emit ``execution_report``
        - Periodically run the position monitor
        """
        self._running = True
        logger.info(
            f"[EXECUTION AGENT] Starting — "
            f"monitor_interval={MONITOR_INTERVAL_SECONDS}s"
        )

        last_monitor = time.monotonic()

        while self._running:
            # Check for incoming execution requests (non-blocking)
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                event = None
            except asyncio.CancelledError:
                break

            if event is not None:
                if event.get("type") == "simulation_result":
                    payload = event["payload"]
                    assessment: RiskAssessment   = payload["assessment"]
                    simulation: SimulationResult = payload["simulation"]
                    opps: list[OpportunityModel] = payload.get("opportunities", [])
                    try:
                        report = await self.execute(assessment, simulation, opps)
                        await self._queue.put(
                            {"type": "execution_report", "payload": report}
                        )
                    except Exception as exc:
                        logger.error(f"[EXECUTION AGENT] Execution error: {exc}")
                else:
                    # Not for us — put back
                    await self._queue.put(event)
                    await asyncio.sleep(0)

            # Periodic monitor
            now = time.monotonic()
            if now - last_monitor >= MONITOR_INTERVAL_SECONDS:
                last_monitor = now
                try:
                    monitor_report = await self.monitor_once()
                    if monitor_report is not None:
                        await self._queue.put(
                            {"type": "execution_report", "payload": monitor_report}
                        )
                except Exception as exc:
                    logger.error(f"[EXECUTION AGENT] Monitor error: {exc}")

        logger.info("[EXECUTION AGENT] Stopped")

    def stop(self) -> None:
        self._running = False

    def update_opportunities(self, opportunities: list[OpportunityModel]) -> None:
        """Update the live opportunity list used by the position monitor."""
        self._opportunities = opportunities
