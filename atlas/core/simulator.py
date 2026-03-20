"""
Simulation Engine for Atlas.

Runs a 7-day shadow portfolio projection for an approved strategy before
any real transactions are executed.  All values are virtual.

Features
--------
- Deposit amount modelling per protocol based on allocation percentages
- Daily compound yield with per-protocol APY
- Gas cost estimation (Ethereum mainnet model)
- Slippage estimation based on pool type and allocation size
- Confidence score derived from volatility and data source
- Rejects strategy if projected net return (yield - gas) is negative
- Persists every SimulationResult to SQLite via SQLAlchemy

All log lines are prefixed with [SIMULATOR].
"""
from __future__ import annotations

import json
import math
import time
from typing import Optional

from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from atlas.data.models import (
    DailySnapshot,
    OpportunityModel,
    RiskAssessment,
    SimulationResult,
    StrategyModel,
)
from config import config

# ── Gas model constants (L2/multi-chain estimates, USD) ──────────────────────
# Approximate gas costs at ~0.05 gwei on Arbitrum/Base/Polygon, ETH ~$3 000

_GAS_COST_PER_TX: dict[str, float] = {
    "lending":        1.50,   # deposit/withdraw to Aave/Compound on L2
    "stable_swap":    2.00,   # Curve add/remove liquidity on L2
    "yield_vault":    2.50,   # Yearn vault deposit/withdrawal on L2
    "liquidity_pool": 3.00,   # Uniswap/Sushi add liquidity on L2
    "xaut_hedge":     1.50,   # USDT→XAUT swap on L2
    "unknown":        2.00,
}
_TXS_PER_PROTOCOL = 2          # one deposit + one approve (worst-case)
_REBALANCE_TXS    = 1          # future rebalance per cycle

# ── Slippage model ────────────────────────────────────────────────────────────

_SLIPPAGE_BPS: dict[str, float] = {
    "lending":        2.0,    # basis points; near-zero for lending
    "stable_swap":    4.0,
    "yield_vault":    5.0,
    "liquidity_pool": 8.0,
    "unknown":        5.0,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _daily_rate(apy_pct: float) -> float:
    """Convert annual percentage yield to daily compounding rate."""
    return (1 + apy_pct / 100) ** (1 / 365) - 1


def _estimate_gas(
    strategy: StrategyModel,
    pool_types: dict[str, str],
) -> float:
    """Estimate total gas cost in USD for entering the strategy."""
    total = 0.0
    for protocol, pct in strategy.allocations.items():
        if protocol == "XAUT":
            total += _GAS_COST_PER_TX["xaut_hedge"] * _TXS_PER_PROTOCOL
            continue
        ptype = pool_types.get(protocol, "unknown")
        per_tx = _GAS_COST_PER_TX.get(ptype, 15.0)
        total += per_tx * _TXS_PER_PROTOCOL
    total += _GAS_COST_PER_TX["unknown"] * _REBALANCE_TXS
    return round(total, 2)


def _estimate_slippage(
    strategy: StrategyModel,
    principal: float,
    pool_types: dict[str, str],
) -> float:
    """Estimate slippage cost in USD across all deposits."""
    total = 0.0
    for protocol, pct in strategy.allocations.items():
        amount = principal * pct / 100
        ptype = pool_types.get(protocol, "unknown")
        bps = _SLIPPAGE_BPS.get(ptype, 5.0)
        total += amount * bps / 10_000
    return round(total, 2)


def _confidence_score(
    strategy: StrategyModel,
    opportunities: list[OpportunityModel],
    data_source: str,
) -> float:
    """
    0–1 confidence score.
    Penalised by: mock data, high volatility, high risk_score.
    """
    score = 1.0

    # Penalise mock data
    if data_source == "mock":
        score -= 0.10

    # Penalise for each high-volatility protocol
    vol_by_protocol = {o.protocol: o.volatility_7d for o in opportunities}
    for protocol in strategy.allocations:
        vol = vol_by_protocol.get(protocol, 0.0)
        if vol > 0.10:
            score -= 0.05
        if vol > 0.20:
            score -= 0.10

    # Penalise risk score above 5
    if strategy.risk_score > 5:
        score -= (strategy.risk_score - 5) * 0.04

    return max(0.0, min(1.0, round(score, 3)))


def _run_projection(
    strategy: StrategyModel,
    principal: float,
    opportunities: list[OpportunityModel],
    days: int = 7,
) -> tuple[list[DailySnapshot], float]:
    """
    Simulate daily compounding yield for `days` days.
    Returns (daily_snapshots, total_yield_usd).
    """
    apy_by_protocol = {o.protocol: o.apy for o in opportunities}
    # Weighted blended daily rate across all allocations
    # XAUT is a store-of-value hedge with 0% yield
    blended_daily = sum(
        (strategy.allocations.get(proto, 0.0) / 100.0)
        * _daily_rate(0.0 if proto == "XAUT" else apy_by_protocol.get(proto, strategy.expected_yield))
        for proto in strategy.allocations
    )

    snapshots: list[DailySnapshot] = []
    portfolio_value = principal
    cumulative_yield = 0.0

    for day in range(1, days + 1):
        day_yield = portfolio_value * blended_daily
        portfolio_value += day_yield
        cumulative_yield += day_yield
        snapshots.append(
            DailySnapshot(
                day=day,
                portfolio_value_usd=round(portfolio_value, 4),
                yield_earned_usd=round(day_yield, 4),
                cumulative_yield_usd=round(cumulative_yield, 4),
            )
        )

    return snapshots, round(cumulative_yield, 4)


# ── SQLAlchemy persistence ────────────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS simulation_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name   TEXT    NOT NULL,
    principal_usd   REAL    NOT NULL,
    projected_7d_yield  REAL,
    projected_apy   REAL,
    estimated_gas_usd   REAL,
    net_return      REAL,
    confidence_score    REAL,
    approved        INTEGER,
    rejection_reason    TEXT,
    daily_snapshots TEXT,   -- JSON
    created_at      REAL    NOT NULL
)
"""


class _DB:
    def __init__(self, url: str) -> None:
        self._engine = create_engine(url, echo=False, future=True)
        with self._engine.connect() as conn:
            conn.execute(text(_CREATE_TABLE))
            conn.commit()

    def save(self, result: SimulationResult) -> None:
        snapshots_json = json.dumps(
            [s.model_dump() for s in result.daily_snapshots]
        )
        with self._engine.connect() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO simulation_history
                        (strategy_name, principal_usd, projected_7d_yield,
                         projected_apy, estimated_gas_usd, net_return,
                         confidence_score, approved, rejection_reason,
                         daily_snapshots, created_at)
                    VALUES
                        (:strategy_name, :principal_usd, :projected_7d_yield,
                         :projected_apy, :estimated_gas_usd, :net_return,
                         :confidence_score, :approved, :rejection_reason,
                         :daily_snapshots, :created_at)
                    """
                ),
                {
                    "strategy_name":       result.strategy_name,
                    "principal_usd":       result.principal_usd,
                    "projected_7d_yield":  result.projected_7d_yield,
                    "projected_apy":       result.projected_apy,
                    "estimated_gas_usd":   result.estimated_gas_usd,
                    "net_return":          result.net_return,
                    "confidence_score":    result.confidence_score,
                    "approved":            int(result.approved),
                    "rejection_reason":    result.rejection_reason,
                    "daily_snapshots":     snapshots_json,
                    "created_at":          result.timestamp,
                },
            )
            conn.commit()

    def recent(self, limit: int = 20) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM simulation_history "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()
        return [dict(r._mapping) for r in rows]


# ── Simulator ─────────────────────────────────────────────────────────────────

class Simulator:
    """
    Shadow-executes an approved strategy and returns a SimulationResult.

    Parameters
    ----------
    principal_usd:
        Total capital to simulate deploying (default from config).
    db_url:
        SQLAlchemy database URL (default from config).
    """

    def __init__(
        self,
        principal_usd: float | None = None,
        db_url: str | None = None,
    ) -> None:
        self._principal = principal_usd or config.initial_portfolio_usdt
        self._db = _DB(db_url or config.database_url)

    # ── Public API ────────────────────────────────────────────────────────────

    def run(
        self,
        assessment: RiskAssessment,
        opportunities: list[OpportunityModel] | None = None,
        data_source: str = "live",
    ) -> SimulationResult:
        """
        Run a 7-day shadow simulation for the approved strategy.

        Parameters
        ----------
        assessment:
            The RiskAssessment containing the selected strategy.
        opportunities:
            Live opportunity list for APY / pool-type lookups.
            Falls back to strategy.expected_yield if empty.
        data_source:
            'live' or 'mock' — affects confidence score.
        """
        strategy = assessment.selected_strategy
        opps = opportunities or []

        logger.info(
            f"[SIMULATOR] Running shadow simulation for '{strategy.name}' "
            f"principal=${self._principal:,.2f}"
        )

        # Build lookup dicts
        pool_types: dict[str, str] = {o.protocol: o.pool_type for o in opps}

        # Gas & slippage
        gas_usd = _estimate_gas(strategy, pool_types)
        slippage_usd = _estimate_slippage(strategy, self._principal, pool_types)
        total_cost_usd = gas_usd + slippage_usd
        logger.debug(
            f"[SIMULATOR] gas=${gas_usd:.2f}  slippage=${slippage_usd:.2f}  "
            f"total_cost=${total_cost_usd:.2f}"
        )

        # 7-day projection
        snapshots, yield_7d = _run_projection(strategy, self._principal, opps)
        net_return = round(yield_7d - total_cost_usd, 4)

        # Annualise
        projected_apy = round((yield_7d / self._principal) * (365 / 7) * 100, 4)

        # Confidence
        confidence = _confidence_score(strategy, opps, data_source)

        # Approve/reject
        approved = net_return > 0
        rejection_reason: Optional[str] = None
        if not approved:
            rejection_reason = (
                f"Net return ${net_return:.2f} is negative after gas "
                f"(${gas_usd:.2f}) and slippage (${slippage_usd:.2f})."
            )
            logger.warning(f"[SIMULATOR] REJECTED — {rejection_reason}")
        else:
            logger.info(
                f"[SIMULATOR] APPROVED — 7d yield=${yield_7d:.2f}  "
                f"net=${net_return:.2f}  APY={projected_apy:.2f}%  "
                f"confidence={confidence:.2f}"
            )

        # Log day-by-day
        for snap in snapshots:
            logger.debug(
                f"[SIMULATOR]   Day {snap.day:>2}: "
                f"value=${snap.portfolio_value_usd:,.2f}  "
                f"yield=${snap.yield_earned_usd:.4f}"
            )

        result = SimulationResult(
            strategy_name=strategy.name,
            principal_usd=self._principal,
            projected_7d_yield=yield_7d,
            projected_apy=projected_apy,
            estimated_gas_usd=total_cost_usd,
            net_return=net_return,
            confidence_score=confidence,
            approved=approved,
            rejection_reason=rejection_reason,
            daily_snapshots=snapshots,
        )

        self._db.save(result)
        logger.info(f"[SIMULATOR] Result persisted to database")
        return result

    def history(self, limit: int = 20) -> list[dict]:
        """Return recent simulation history from SQLite."""
        return self._db.recent(limit)
