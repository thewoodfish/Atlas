"""
Market Analyst Agent for Atlas.

Responsibilities
----------------
- Poll DeFiClient every 30 seconds for fresh yield opportunities
- Send opportunities to Claude for risk-adjusted ranking and sentiment analysis
- Emit a MarketReport to the shared asyncio Queue consumed by the Orchestrator

All log lines are prefixed with [MARKET ANALYST].
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import anthropic
from loguru import logger

from atlas.data.defi_client import DeFiClient
from atlas.data.models import (
    FetchResult,
    MarketReport,
    MarketSentiment,
    OpportunityModel,
    RankedOpportunity,
)
from config import config

# ── Prompts ──────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are a DeFi market analyst. You MUST rank ALL provided yield opportunities "
    "by risk-adjusted return — do not omit any. Assign each a rank (1 = best) and a "
    "risk_adjusted_score (0–100). Be concise and data-driven."
)

_ANALYSIS_TOOL = {
    "name": "submit_market_report",
    "description": (
        "Submit a structured market analysis report with ranked opportunities, "
        "overall sentiment, and a strategic recommendation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ranked_opportunities": {
                "type": "array",
                "description": "ALL opportunities ranked best → worst. Must include every pool provided — never return an empty list.",
                "items": {
                    "type": "object",
                    "properties": {
                        "pool_id": {"type": "string"},
                        "rank": {"type": "integer"},
                        "risk_adjusted_score": {
                            "type": "number",
                            "description": "Score on a 0-100 scale. Higher = better.",
                        },
                        "rationale": {
                            "type": "string",
                            "description": "One-sentence analyst note.",
                        },
                    },
                    "required": ["pool_id", "rank", "risk_adjusted_score", "rationale"],
                },
            },
            "market_sentiment": {
                "type": "string",
                "enum": ["bullish", "neutral", "bearish", "volatile"],
            },
            "recommended_focus": {
                "type": "string",
                "description": "1-2 sentence strategic recommendation for the treasury.",
            },
        },
        "required": ["ranked_opportunities", "market_sentiment", "recommended_focus"],
    },
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def _build_user_message(fetch: FetchResult) -> str:
    """Format opportunities as a compact table for the LLM prompt."""
    lines = [
        f"Data source: {fetch.source}",
        f"Pools analysed: {len(fetch.opportunities)}",
        "",
        f"{'#':<3} {'pool_id':<45} {'Protocol':<20} {'Symbol':<20} {'APY':>6} {'TVL ($M)':>10} {'Vol7d':>7} {'Type':<14} {'Chain'}",
        "-" * 140,
    ]
    for i, opp in enumerate(fetch.opportunities, 1):
        lines.append(
            f"{i:<3} {opp.pool_id:<45} {opp.protocol:<20} {opp.symbol:<20} "
            f"{opp.apy:>5.1f}% {opp.tvl_usd / 1e6:>9.1f}M "
            f"{opp.volatility_7d * 100:>6.2f}% {opp.pool_type:<14} {opp.chain}"
        )
    lines.append("")
    lines.append(f"Rank ALL {len(fetch.opportunities)} pools above. Use the exact pool_id strings from this table.")
    return "\n".join(lines)


def _assemble_report(
    tool_input: dict[str, Any],
    fetch: FetchResult,
) -> MarketReport:
    """Map Claude's tool call output back to a MarketReport."""
    opp_by_id: dict[str, OpportunityModel] = {o.pool_id: o for o in fetch.opportunities}

    ranked: list[RankedOpportunity] = []
    for item in tool_input.get("ranked_opportunities", []):
        if not isinstance(item, dict):
            continue
        pool_id = item.get("pool_id", "")
        opp = opp_by_id.get(pool_id)
        if opp is None:
            logger.warning(f"[MARKET ANALYST] Unknown pool_id in Claude response: {pool_id!r}")
            continue
        ranked.append(
            RankedOpportunity(
                opportunity=opp,
                rank=item["rank"],
                risk_adjusted_score=item["risk_adjusted_score"],
                rationale=item.get("rationale", ""),
            )
        )

    ranked.sort(key=lambda r: r.rank)

    sentiment_raw: str = tool_input.get("market_sentiment", "neutral")
    try:
        sentiment = MarketSentiment(sentiment_raw)
    except ValueError:
        sentiment = MarketSentiment.NEUTRAL

    return MarketReport(
        top_opportunities=ranked,
        market_sentiment=sentiment,
        recommended_focus=tool_input.get("recommended_focus", ""),
        data_source=fetch.source,
        timestamp=time.time(),
    )


# ── Agent ────────────────────────────────────────────────────────────────────

class MarketAnalystAgent:
    """
    Async agent that continuously monitors DeFi markets and emits MarketReports.

    Parameters
    ----------
    event_queue:
        Shared asyncio.Queue the orchestrator listens on.
        Each item placed on the queue is a dict:
        ``{"type": "market_report", "payload": MarketReport}``
    poll_interval:
        Seconds between DeFiClient polls (default: from config).
    """

    def __init__(
        self,
        event_queue: asyncio.Queue,
        poll_interval: int | None = None,
    ) -> None:
        self._queue = event_queue
        self._poll_interval = poll_interval or config.scan_interval_seconds
        self._defi_client = DeFiClient()
        self._anthropic = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
        self._running = False

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _analyse(self, fetch: FetchResult) -> MarketReport:
        """Call Claude to rank opportunities and produce a MarketReport."""
        if not fetch.opportunities:
            logger.warning("[MARKET ANALYST] No opportunities to analyse")
            return MarketReport(
                market_sentiment=MarketSentiment.NEUTRAL,
                recommended_focus="No opportunities available.",
                data_source=fetch.source,
            )

        if config.offline_mode:
            logger.info("[MARKET ANALYST] Offline mode — ranking by APY, skipping Claude")
            ranked = sorted(fetch.opportunities, key=lambda o: o.apy, reverse=True)[:15]
            return MarketReport(
                top_opportunities=[
                    RankedOpportunity(
                        opportunity=o,
                        rank=i + 1,
                        risk_adjusted_score=round(o.apy / max(o.volatility_7d + 0.01, 0.01), 2),
                        rationale=f"Top APY {o.apy:.1f}% with TVL ${o.tvl_usd/1e6:.0f}M",
                    )
                    for i, o in enumerate(ranked)
                ],
                market_sentiment=MarketSentiment.BULLISH,
                recommended_focus="High-yield stablecoin lending across established protocols",
                data_source=fetch.source,
                timestamp=time.time(),
            )

        user_message = _build_user_message(fetch)
        logger.debug(f"[MARKET ANALYST] Sending {len(fetch.opportunities)} pools to Claude")

        response = await self._anthropic.messages.create(
            model=config.claude_model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            tools=[_ANALYSIS_TOOL],
            tool_choice={"type": "tool", "name": "submit_market_report"},
            messages=[{"role": "user", "content": user_message}],
        )

        # Extract the tool-use block
        tool_block = next(
            (b for b in response.content if b.type == "tool_use"), None
        )
        if tool_block is None:
            raise RuntimeError("Claude did not return a tool_use block")

        tool_input: dict[str, Any] = tool_block.input  # type: ignore[union-attr]
        report = _assemble_report(tool_input, fetch)
        return report

    async def _run_once(self) -> None:
        """Fetch data, analyse, and emit one MarketReport."""
        logger.info("[MARKET ANALYST] Fetching DeFi opportunities…")
        fetch = await self._defi_client.fetch_opportunities()
        logger.info(
            f"[MARKET ANALYST] Got {len(fetch.opportunities)} opportunities "
            f"(source={fetch.source})"
        )

        report = await self._analyse(fetch)

        sentiment = report.market_sentiment
        top = report.top_opportunities[0] if report.top_opportunities else None
        logger.info(
            f"[MARKET ANALYST] Report ready — sentiment={sentiment}, "
            f"top_pick={top.opportunity.protocol if top else 'n/a'} "
            f"(score={top.risk_adjusted_score:.1f})" if top else
            f"[MARKET ANALYST] Report ready — sentiment={sentiment}, no ranked picks"
        )
        logger.info(f"[MARKET ANALYST] Focus: {report.recommended_focus}")

        await self._queue.put({"type": "market_report", "payload": report})

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """
        Poll DeFi markets in a loop, emitting a MarketReport each cycle.
        Runs until `stop()` is called.
        """
        self._running = True
        logger.info(
            f"[MARKET ANALYST] Starting — poll interval={self._poll_interval}s"
        )

        while self._running:
            try:
                await self._run_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[MARKET ANALYST] Cycle error: {exc}")

            if self._running:
                logger.debug(
                    f"[MARKET ANALYST] Sleeping {self._poll_interval}s until next scan"
                )
                await asyncio.sleep(self._poll_interval)

        logger.info("[MARKET ANALYST] Stopped")

    async def run_once(self) -> MarketReport:
        """Run a single analysis cycle and return the report (useful for testing)."""
        fetch = await self._defi_client.fetch_opportunities()
        report = await self._analyse(fetch)
        return report

    def stop(self) -> None:
        self._running = False

    async def close(self) -> None:
        self.stop()
        await self._defi_client.close()
