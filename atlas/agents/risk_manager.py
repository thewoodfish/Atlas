"""
Risk Manager Agent for Atlas.

Two-layer validation
--------------------
Layer 1 — Deterministic hard rules (no AI):
  • Max 40% allocation to any single protocol
  • Skip pools with TVL under $10M
  • Reject strategies with risk_score > 8
  • Flag volatility_7d > 15%

Layer 2 — Claude qualitative review:
  • Hidden / tail risks
  • Correlation risks across protocols
  • Market condition sensitivity

If all three strategies fail Layer 1, a capital-preservation fallback
(100% in the safest available lending protocol) is used automatically.

All log lines are prefixed with [RISK MANAGER].
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import anthropic
from loguru import logger

from atlas.data.models import (
    MarketReport,
    OpportunityModel,
    RiskAssessment,
    RiskFlag,
    StrategyBundle,
    StrategyModel,
)
from config import config

# ── Hard-rule thresholds ──────────────────────────────────────────────────────

MAX_SINGLE_PROTOCOL_PCT = 40.0   # %
MIN_TVL_USD              = 10_000_000
MAX_RISK_SCORE           = 8
VOLATILITY_FLAG_THRESHOLD = 0.15  # fraction (15 %)

# ── Prompts ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are a risk manager for an autonomous DeFi treasury. "
    "Review the proposed strategy for hidden risks, correlation risks, and "
    "market condition risks. Be concise and objective."
)

_REVIEW_TOOL = {
    "name": "submit_risk_review",
    "description": "Submit a qualitative risk review of the proposed strategy.",
    "input_schema": {
        "type": "object",
        "properties": {
            "approved": {
                "type": "boolean",
                "description": "True if the strategy is safe to execute as-is or with minor adjustments.",
            },
            "risk_flags": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [f.value for f in RiskFlag],
                },
                "description": "Any qualitative risk flags identified.",
            },
            "adjustments": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific allocation adjustment suggestions (may be empty).",
            },
            "reasoning": {
                "type": "string",
                "description": "2-4 sentence qualitative risk reasoning.",
            },
        },
        "required": ["approved", "risk_flags", "adjustments", "reasoning"],
    },
}


# ── Layer 1: deterministic rules ──────────────────────────────────────────────

def _hard_check(
    strategy: StrategyModel,
    opportunities: list[OpportunityModel],
) -> tuple[bool, list[RiskFlag]]:
    """
    Apply deterministic hard rules.

    Returns (passed, flags_list).
    A strategy *fails* if concentration or risk_score rules are violated.
    Volatility is flagged but does not cause outright rejection.
    """
    flags: list[RiskFlag] = []
    failed = False

    # 1. Concentration: max 40% per protocol (XAUT exempt — it's a hedge, not a DeFi pool)
    for protocol, pct in strategy.allocations.items():
        if protocol == "XAUT":
            continue
        if pct > MAX_SINGLE_PROTOCOL_PCT:
            logger.warning(
                f"[RISK MANAGER] FAIL concentration: {protocol} = {pct:.1f}% "
                f"(max {MAX_SINGLE_PROTOCOL_PCT}%)"
            )
            flags.append(RiskFlag.CONCENTRATION)
            failed = True
            break

    # 2. Risk score
    if strategy.risk_score > MAX_RISK_SCORE:
        logger.warning(
            f"[RISK MANAGER] FAIL risk_score={strategy.risk_score} > {MAX_RISK_SCORE}"
        )
        flags.append(RiskFlag.HIGH_RISK_SCORE)
        failed = True

    # 3. Low-TVL pools (check against opportunity data by protocol name)
    tvl_by_protocol: dict[str, float] = {}
    for opp in opportunities:
        if opp.protocol not in tvl_by_protocol or opp.tvl_usd > tvl_by_protocol[opp.protocol]:
            tvl_by_protocol[opp.protocol] = opp.tvl_usd

    for protocol in strategy.allocations:
        if protocol == "XAUT":
            continue  # Tether Gold is not a DeFi pool — no TVL check
        tvl = tvl_by_protocol.get(protocol, float("inf"))
        if tvl < MIN_TVL_USD:
            logger.warning(
                f"[RISK MANAGER] FAIL low_liquidity: {protocol} TVL=${tvl/1e6:.1f}M "
                f"(min ${MIN_TVL_USD/1e6:.0f}M)"
            )
            flags.append(RiskFlag.LOW_LIQUIDITY)
            failed = True
            break

    # 4. Volatility flag (warn only, does not reject)
    for opp in opportunities:
        if (
            opp.protocol in strategy.allocations
            and opp.volatility_7d > VOLATILITY_FLAG_THRESHOLD
        ):
            logger.warning(
                f"[RISK MANAGER] FLAG high_volatility: {opp.protocol} "
                f"vol7d={opp.volatility_7d * 100:.1f}%"
            )
            if RiskFlag.HIGH_VOLATILITY not in flags:
                flags.append(RiskFlag.HIGH_VOLATILITY)

    return not failed, flags


# ── Layer 2: Claude qualitative review ───────────────────────────────────────

def _build_review_message(
    strategy: StrategyModel,
    hard_flags: list[RiskFlag],
) -> str:
    alloc_lines = "\n".join(
        f"  {proto:<25} {pct:.1f}%"
        for proto, pct in strategy.allocations.items()
    )
    flag_str = ", ".join(f.value for f in hard_flags) if hard_flags else "none"
    return (
        f"Strategy: {strategy.name}\n"
        f"Expected yield: {strategy.expected_yield:.1f}%\n"
        f"Risk score: {strategy.risk_score}/10\n"
        f"Liquidity requirement: ${strategy.liquidity_requirement/1e6:.0f}M\n"
        f"Hard-rule flags already raised: {flag_str}\n\n"
        f"Allocations:\n{alloc_lines}\n\n"
        f"Rationale from strategy agent:\n{strategy.rationale}\n\n"
        "Please identify any hidden, correlation, or market-condition risks."
    )


# ── Capital-preservation fallback ─────────────────────────────────────────────

def _capital_preservation_strategy(
    opportunities: list[OpportunityModel],
) -> StrategyModel:
    """100% in the safest (lowest volatility, lending) protocol available."""
    lending = [
        o for o in opportunities
        if o.pool_type in ("lending",) and o.tvl_usd >= MIN_TVL_USD
    ]
    candidates = lending or [o for o in opportunities if o.tvl_usd >= MIN_TVL_USD]

    if candidates:
        safest = min(candidates, key=lambda o: o.volatility_7d)
        protocol = safest.protocol
        apy = safest.apy
    else:
        protocol = "Aave V3"
        apy = 5.0

    logger.warning(
        f"[RISK MANAGER] Capital preservation fallback → 100% {protocol}"
    )
    return StrategyModel(
        name="Capital Preservation",
        allocations={protocol: 100.0},
        expected_yield=apy,
        risk_score=1,
        liquidity_requirement=MIN_TVL_USD,
        rationale=(
            "All generated strategies were rejected by risk rules. "
            f"Deploying 100% to {protocol} for capital preservation."
        ),
    )


# ── Agent ─────────────────────────────────────────────────────────────────────

class RiskManagerAgent:
    """
    Two-layer risk filter: deterministic hard rules + Claude qualitative review.

    Parameters
    ----------
    event_queue:
        Shared asyncio.Queue.  Consumes ``strategy_bundle`` events and
        emits ``risk_assessment`` events.
    market_report:
        Latest MarketReport, used to look up TVL/volatility by protocol.
        Update this reference each cycle before calling process().
    """

    def __init__(
        self,
        event_queue: asyncio.Queue,
        market_report: MarketReport | None = None,
    ) -> None:
        self._queue = event_queue
        self.market_report = market_report
        self._anthropic = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
        self._running = False

    # ── Internal ──────────────────────────────────────────────────────────────

    def _opportunities(self) -> list[OpportunityModel]:
        if self.market_report:
            return [ro.opportunity for ro in self.market_report.top_opportunities]
        return []

    async def _qualitative_review(
        self,
        strategy: StrategyModel,
        hard_flags: list[RiskFlag],
    ) -> tuple[bool, list[RiskFlag], list[str], str]:
        """
        Ask Claude for a qualitative risk review.
        Returns (approved, extra_flags, adjustments, reasoning).
        """
        user_msg = _build_review_message(strategy, hard_flags)
        try:
            response = await self._anthropic.messages.create(
                model=config.claude_model,
                max_tokens=512,
                system=_SYSTEM_PROMPT,
                tools=[_REVIEW_TOOL],
                tool_choice={"type": "tool", "name": "submit_risk_review"},
                messages=[{"role": "user", "content": user_msg}],
            )
        except Exception as exc:
            logger.error(f"[RISK MANAGER] Claude API error during review: {exc}")
            return True, [], [], "Qualitative review unavailable — defaulting to approved."

        tool_block = next(
            (b for b in response.content if b.type == "tool_use"), None
        )
        if tool_block is None:
            return True, [], [], "No Claude response — defaulting to approved."

        inp: dict[str, Any] = tool_block.input  # type: ignore[union-attr]
        approved: bool = bool(inp.get("approved", True))
        extra_flags: list[RiskFlag] = []
        for f in inp.get("risk_flags", []):
            try:
                extra_flags.append(RiskFlag(f))
            except ValueError:
                extra_flags.append(RiskFlag.OTHER)
        adjustments: list[str] = inp.get("adjustments", [])
        reasoning: str = inp.get("reasoning", "")
        return approved, extra_flags, adjustments, reasoning

    async def _evaluate(
        self, strategy: StrategyModel
    ) -> tuple[bool, list[RiskFlag], list[str], str]:
        """Full two-layer evaluation of a single strategy."""
        opps = self._opportunities()

        # Layer 1
        passed_hard, hard_flags = _hard_check(strategy, opps)
        if not passed_hard:
            logger.info(
                f"[RISK MANAGER] {strategy.name} REJECTED by hard rules: "
                + ", ".join(f.value for f in hard_flags)
            )
            return False, hard_flags, [], "Failed deterministic hard rules."

        logger.info(
            f"[RISK MANAGER] {strategy.name} passed hard rules "
            f"(flags={[f.value for f in hard_flags] or 'none'}), "
            "sending to Claude for qualitative review…"
        )

        # Layer 2
        approved, extra_flags, adjustments, reasoning = await self._qualitative_review(
            strategy, hard_flags
        )
        all_flags = list(dict.fromkeys(hard_flags + extra_flags))  # deduplicate, preserve order

        status = "APPROVED" if approved else "REJECTED (qualitative)"
        logger.info(f"[RISK MANAGER] {strategy.name} {status} — {reasoning[:80]}…")
        if adjustments:
            for adj in adjustments:
                logger.info(f"[RISK MANAGER]   adjustment: {adj}")

        return approved, all_flags, adjustments, reasoning

    # ── Public API ────────────────────────────────────────────────────────────

    async def process(self, bundle: StrategyBundle) -> RiskAssessment:
        """
        Evaluate all three strategies and return a RiskAssessment for the
        best approved one.  Falls back to capital preservation if all fail.
        """
        logger.info("[RISK MANAGER] Evaluating strategy bundle…")
        opps = self._opportunities()

        # Evaluate in order: conservative first (prefer lowest risk)
        for strategy in bundle.as_list():
            approved, flags, adjustments, reasoning = await self._evaluate(strategy)
            if approved:
                return RiskAssessment(
                    approved=True,
                    selected_strategy=strategy,
                    risk_flags=flags,
                    adjustments=adjustments,
                    reasoning=reasoning,
                    is_capital_preservation=False,
                )

        # All rejected → capital preservation
        logger.warning(
            "[RISK MANAGER] All strategies rejected — activating capital preservation"
        )
        fallback = _capital_preservation_strategy(opps)
        return RiskAssessment(
            approved=True,
            selected_strategy=fallback,
            risk_flags=[],
            adjustments=[],
            reasoning="All generated strategies failed risk checks. Capital preservation activated.",
            is_capital_preservation=True,
        )

    async def run(self) -> None:
        """
        Consume ``strategy_bundle`` events from the queue and emit
        ``risk_assessment`` events.  Runs until ``stop()`` is called.
        """
        self._running = True
        logger.info("[RISK MANAGER] Starting — waiting for strategy bundles")

        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            if event.get("type") != "strategy_bundle":
                await self._queue.put(event)
                await asyncio.sleep(0)
                continue

            bundle: StrategyBundle = event["payload"]
            try:
                assessment = await self.process(bundle)
                await self._queue.put({"type": "risk_assessment", "payload": assessment})
            except Exception as exc:
                logger.error(f"[RISK MANAGER] Evaluation error: {exc}")

        logger.info("[RISK MANAGER] Stopped")

    def stop(self) -> None:
        self._running = False
