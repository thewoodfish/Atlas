"""
Strategy Agent for Atlas.

Responsibilities
----------------
- Receives a MarketReport from the orchestrator queue
- Calls Claude to generate three portfolio strategies:
    Conservative  — max 70% in any one protocol, prefer lending pools
    Balanced      — mix of lending + liquidity pools
    Aggressive    — includes experimental vaults, chases highest yield
- Emits a StrategyBundle to the queue for the Risk Manager to consume

All log lines are prefixed with [STRATEGY AGENT].
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import anthropic
from loguru import logger

from atlas.data.models import (
    MarketReport,
    MarketSentiment,
    StrategyBundle,
    StrategyModel,
)
from config import config

# ── Prompts ──────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are a portfolio strategist for an autonomous DeFi treasury. "
    "Given market opportunities, generate conservative, balanced, and aggressive "
    "allocation strategies. Each allocation must sum to exactly 100%. "
    "Conservative strategies prefer lending protocols with max 70% in any single protocol. "
    "Balanced strategies mix lending and liquidity pools. "
    "Aggressive strategies may include experimental vaults chasing the highest yield. "
    "When market sentiment is 'bearish' or 'volatile', include 'XAUT' (Tether Gold) "
    "as a safe-haven hedge in the conservative strategy (10-20% allocation). "
    "XAUT has 0% yield but preserves value against DeFi volatility. "
    "Use the exact key 'XAUT' in the allocations dict when including gold."
)

def _strategy_schema(description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "description": description,
        "properties": {
            "name": {"type": "string"},
            "allocations": {
                "type": "object",
                "description": "protocol_name -> percentage (all values sum to 100)",
                "additionalProperties": {"type": "number"},
            },
            "expected_yield": {
                "type": "number",
                "description": "Weighted average APY across allocations (%)",
            },
            "risk_score": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "1 = safest, 10 = riskiest",
            },
            "liquidity_requirement": {
                "type": "number",
                "description": "Minimum pool TVL required in USD (e.g. 10000000 for $10M)",
            },
            "rationale": {
                "type": "string",
                "description": "2-3 sentence explanation of the strategy.",
            },
        },
        "required": [
            "name",
            "allocations",
            "expected_yield",
            "risk_score",
            "liquidity_requirement",
            "rationale",
        ],
    }


_STRATEGY_TOOL = {
    "name": "submit_strategies",
    "description": "Submit three portfolio allocation strategies for treasury deployment.",
    "input_schema": {
        "type": "object",
        "properties": {
            "conservative": _strategy_schema(
                "Low-risk strategy: prefer lending, max 70% per protocol, risk_score 1-4"
            ),
            "balanced": _strategy_schema(
                "Medium-risk strategy: mix lending + LPs, risk_score 4-7"
            ),
            "aggressive": _strategy_schema(
                "High-yield strategy: vaults + experimental pools, risk_score 7-10"
            ),
        },
        "required": ["conservative", "balanced", "aggressive"],
    },
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _build_user_message(report: MarketReport) -> str:
    lines = [
        f"Market sentiment: {report.market_sentiment}",
        f"Analyst focus: {report.recommended_focus}",
        "",
        "Top ranked opportunities:",
        f"{'Rank':<5} {'Protocol':<20} {'Symbol':<24} {'APY':>6} {'TVL ($M)':>10} "
        f"{'Vol7d':>7} {'Type':<14} {'Score':>7}",
        "-" * 100,
    ]
    for ro in report.top_opportunities:
        opp = ro.opportunity
        lines.append(
            f"{ro.rank:<5} {opp.protocol:<20} {opp.symbol:<24} "
            f"{opp.apy:>5.1f}% {opp.tvl_usd / 1e6:>9.1f}M "
            f"{opp.volatility_7d * 100:>6.2f}% {opp.pool_type:<14} "
            f"{ro.risk_adjusted_score:>7.1f}"
        )
        if ro.rationale:
            lines.append(f"      ↳ {ro.rationale}")

    lines.append("")
    if report.market_sentiment in ("bearish", "volatile"):
        lines.append(
            "⚠️  Sentiment is bearish/volatile. Include 'XAUT' (Tether Gold, 0% yield) "
            "as a 10-20% safe-haven hedge in the conservative strategy. "
            "Use 'XAUT' as the exact key in the allocations dict."
        )
    lines.append(
        "Generate three strategies (conservative / balanced / aggressive) using ONLY "
        "the protocols listed above (plus 'XAUT' when appropriate). "
        "Allocations must sum to exactly 100."
    )
    return "\n".join(lines)


def _parse_strategy(raw: Any, default_name: str) -> StrategyModel:
    if not isinstance(raw, dict):
        raw = {}
    return StrategyModel(
        name=raw.get("name", default_name),
        allocations=raw.get("allocations", {}),
        expected_yield=float(raw.get("expected_yield", 0.0)),
        risk_score=int(raw.get("risk_score", 5)),
        liquidity_requirement=float(raw.get("liquidity_requirement", 0.0)),
        rationale=raw.get("rationale", ""),
    )


def _fallback_bundle(report: MarketReport) -> StrategyBundle:
    """Rule-based fallback when Claude is unavailable."""
    opps = [ro.opportunity for ro in report.top_opportunities]

    def _build_alloc(candidates: list, n: int, max_pct: float = 40.0) -> dict[str, float]:
        """Pick up to n distinct protocols, cap each at max_pct, equal weight."""
        seen: dict[str, float] = {}
        for o in candidates:
            if o.protocol not in seen and len(seen) < n:
                seen[o.protocol] = 0.0
        if not seen:
            return {}
        pct = min(round(100.0 / len(seen), 1), max_pct)
        return {p: pct for p in seen}

    def _weighted_yield(allocs: dict[str, float], src: list) -> float:
        apy_map = {o.protocol: o.apy for o in src}
        total_pct = sum(allocs.values())
        if total_pct == 0:
            return 0.0
        return sum(apy_map.get(p, 0) * pct / total_pct for p, pct in allocs.items())

    if not opps:
        fallback_alloc = {"Aave V3": 40.0, "Compound": 35.0, "Sky Lending": 25.0}
        return StrategyBundle(
            conservative=StrategyModel(
                name="Capital Preservation — Established Lending",
                allocations=fallback_alloc,
                expected_yield=4.0,
                risk_score=2,
                liquidity_requirement=10_000_000,
                rationale="No live data — default allocation across established money markets.",
            ),
            balanced=StrategyModel(
                name="Balanced Yield — Multi-Protocol",
                allocations=fallback_alloc,
                expected_yield=5.5,
                risk_score=5,
                liquidity_requirement=10_000_000,
                rationale="No live data — balanced multi-protocol allocation.",
            ),
            aggressive=StrategyModel(
                name="Yield Maximiser — High APY",
                allocations=fallback_alloc,
                expected_yield=7.0,
                risk_score=7,
                liquidity_requirement=5_000_000,
                rationale="No live data — yield-focused allocation.",
            ),
            based_on_sentiment=report.market_sentiment,
        )

    by_apy = sorted(opps, key=lambda o: o.apy, reverse=True)
    by_tvl = sorted(opps, key=lambda o: o.tvl_usd, reverse=True)

    # Conservative: top-4 by TVL (safest), capped at 35% each
    c_alloc = _build_alloc(by_tvl, 4, max_pct=35.0)
    # Balanced: top-4 by APY but capped at 30% each for spread
    b_alloc = _build_alloc(by_apy, 4, max_pct=30.0)
    # Aggressive: top-5 by APY, up to 40% each
    a_alloc = _build_alloc(by_apy, 5, max_pct=40.0)

    return StrategyBundle(
        conservative=StrategyModel(
            name="Capital Preservation with Steady Yield",
            allocations=c_alloc,
            expected_yield=round(_weighted_yield(c_alloc, by_tvl), 2),
            risk_score=3,
            liquidity_requirement=10_000_000,
            rationale=(
                "Allocates to the four highest-TVL protocols for maximum liquidity safety. "
                "Equal-weight capped at 35% to avoid concentration risk."
            ),
        ),
        balanced=StrategyModel(
            name="Diversified Institutional Credit",
            allocations=b_alloc,
            expected_yield=round(_weighted_yield(b_alloc, by_apy), 2),
            risk_score=5,
            liquidity_requirement=10_000_000,
            rationale=(
                "Balances yield and risk across four top-APY protocols. "
                "30% cap per protocol ensures no single-protocol concentration."
            ),
        ),
        aggressive=StrategyModel(
            name="Yield Maximiser — High Conviction",
            allocations=a_alloc,
            expected_yield=round(_weighted_yield(a_alloc, by_apy), 2),
            risk_score=7,
            liquidity_requirement=5_000_000,
            rationale=(
                "Concentrates on the top-5 yield opportunities. "
                "Higher APY comes with moderately elevated protocol risk."
            ),
        ),
        based_on_sentiment=report.market_sentiment,
    )


# ── Agent ─────────────────────────────────────────────────────────────────────

class StrategyAgent:
    """
    Async agent that converts a MarketReport into a StrategyBundle.

    Parameters
    ----------
    event_queue:
        Shared asyncio.Queue.  The agent reads ``market_report`` events and
        writes back ``strategy_bundle`` events.
    """

    def __init__(self, event_queue: asyncio.Queue) -> None:
        self._queue = event_queue
        self._anthropic = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
        self._running = False

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _generate(self, report: MarketReport) -> StrategyBundle:
        """Call Claude to produce three allocation strategies."""
        if not report.top_opportunities:
            logger.warning("[STRATEGY AGENT] Empty report — using rule-based fallback")
            return _fallback_bundle(report)

        if config.offline_mode:
            logger.info("[STRATEGY AGENT] Offline mode — using rule-based strategies, skipping Claude")
            return _fallback_bundle(report)

        user_message = _build_user_message(report)
        logger.debug(
            f"[STRATEGY AGENT] Sending {len(report.top_opportunities)} ranked "
            "opportunities to Claude"
        )

        try:
            response = await self._anthropic.messages.create(
                model=config.claude_model,
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                tools=[_STRATEGY_TOOL],
                tool_choice={"type": "tool", "name": "submit_strategies"},
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as exc:
            logger.error(f"[STRATEGY AGENT] Claude API error: {exc} — using fallback")
            return _fallback_bundle(report)

        tool_block = next(
            (b for b in response.content if b.type == "tool_use"), None
        )
        if tool_block is None:
            logger.error("[STRATEGY AGENT] No tool_use block in response — using fallback")
            return _fallback_bundle(report)

        inp: dict[str, Any] = tool_block.input  # type: ignore[union-attr]

        bundle = StrategyBundle(
            conservative=_parse_strategy(inp.get("conservative", {}), "Conservative"),
            balanced=_parse_strategy(inp.get("balanced", {}), "Balanced"),
            aggressive=_parse_strategy(inp.get("aggressive", {}), "Aggressive"),
            based_on_sentiment=report.market_sentiment,
        )
        return bundle

    def _log_bundle(self, bundle: StrategyBundle) -> None:
        for strat in bundle.as_list():
            alloc_str = ", ".join(
                f"{p} {pct:.0f}%" for p, pct in strat.allocations.items()
            )
            logger.info(
                f"[STRATEGY AGENT] {strat.name:<14} "
                f"yield={strat.expected_yield:.1f}%  risk={strat.risk_score}/10  "
                f"alloc=[{alloc_str}]"
            )

    # ── Public API ────────────────────────────────────────────────────────────

    async def process(self, report: MarketReport) -> StrategyBundle:
        """Generate strategies for a single MarketReport and return the bundle."""
        logger.info(
            f"[STRATEGY AGENT] Generating strategies for sentiment="
            f"{report.market_sentiment}, "
            f"opportunities={len(report.top_opportunities)}"
        )
        bundle = await self._generate(report)
        self._log_bundle(bundle)
        logger.info(f"[STRATEGY AGENT] Focus: {report.recommended_focus}")
        return bundle

    async def run(self) -> None:
        """
        Consume ``market_report`` events from the queue and emit
        ``strategy_bundle`` events back.  Runs until ``stop()`` is called.
        """
        self._running = True
        logger.info("[STRATEGY AGENT] Starting — waiting for market reports")

        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            if event.get("type") != "market_report":
                # Put non-matching events back for other consumers
                await self._queue.put(event)
                await asyncio.sleep(0)
                continue

            report: MarketReport = event["payload"]
            try:
                bundle = await self.process(report)
                await self._queue.put({"type": "strategy_bundle", "payload": bundle})
            except Exception as exc:
                logger.error(f"[STRATEGY AGENT] Failed to generate strategies: {exc}")

        logger.info("[STRATEGY AGENT] Stopped")

    def stop(self) -> None:
        self._running = False
