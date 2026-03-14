"""
Pydantic data models for Atlas DeFi data layer.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class PoolType(str, Enum):
    LENDING = "lending"
    STABLE_SWAP = "stable_swap"
    YIELD_VAULT = "yield_vault"
    LIQUIDITY_POOL = "liquidity_pool"
    UNKNOWN = "unknown"


class OpportunityModel(BaseModel):
    """A single yield-bearing opportunity discovered from DeFi protocols."""

    protocol: str = Field(..., description="Protocol name, e.g. 'Aave V3'")
    pool_id: str = Field(..., description="Unique pool identifier")
    apy: float = Field(..., ge=0, description="Annual percentage yield (e.g. 6.2 for 6.2%)")
    tvl_usd: float = Field(..., ge=0, description="Total value locked in USD")
    volatility_7d: float = Field(
        default=0.0, ge=0, description="7-day APY standard deviation as a fraction (e.g. 0.05 = 5%)"
    )
    pool_type: PoolType = Field(default=PoolType.UNKNOWN)
    chain: str = Field(default="Ethereum", description="Chain name")
    symbol: str = Field(default="", description="Pool symbol / asset pair")
    is_stablecoin: bool = Field(default=True)

    @field_validator("apy", "volatility_7d", mode="before")
    @classmethod
    def _coerce_none_to_zero(cls, v):
        return v if v is not None else 0.0

    @field_validator("tvl_usd", mode="before")
    @classmethod
    def _coerce_tvl_none(cls, v):
        return v if v is not None else 0.0

    model_config = {"use_enum_values": True}


class FetchResult(BaseModel):
    """Wrapper returned by DeFiClient.fetch_opportunities()."""

    opportunities: list[OpportunityModel] = Field(default_factory=list)
    source: str = Field(default="live", description="'live' or 'mock'")
    fetched_at: float = Field(default=0.0, description="Unix timestamp of fetch")
    error: Optional[str] = Field(default=None)


class MarketSentiment(str, Enum):
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    VOLATILE = "volatile"


class RankedOpportunity(BaseModel):
    """An opportunity with Claude's risk-adjusted ranking annotation."""

    opportunity: OpportunityModel
    rank: int = Field(..., ge=1, description="1 = best risk-adjusted return")
    risk_adjusted_score: float = Field(
        ..., description="Higher is better; apy discounted by volatility and size"
    )
    rationale: str = Field(default="", description="One-line analyst note")


class MarketReport(BaseModel):
    """Structured output from the Market Analyst Agent."""

    top_opportunities: list[RankedOpportunity] = Field(default_factory=list)
    market_sentiment: MarketSentiment = Field(default=MarketSentiment.NEUTRAL)
    recommended_focus: str = Field(
        default="", description="Short strategic recommendation from Claude"
    )
    data_source: str = Field(default="live", description="'live' or 'mock'")
    timestamp: float = Field(default_factory=time.time)

    model_config = {"use_enum_values": True}


# ── Strategy models ───────────────────────────────────────────────────────────

class StrategyModel(BaseModel):
    """A single portfolio allocation strategy produced by the Strategy Agent."""

    name: str = Field(..., description="e.g. 'Conservative', 'Balanced', 'Aggressive'")
    allocations: dict[str, float] = Field(
        ...,
        description="protocol_name -> allocation percentage (values sum to ~100)",
    )
    expected_yield: float = Field(..., ge=0, description="Weighted expected APY (%)")
    risk_score: int = Field(..., ge=1, le=10, description="1 = safest, 10 = riskiest")
    liquidity_requirement: float = Field(
        default=0.0, ge=0, description="Minimum TVL required across all pools (USD)"
    )
    rationale: str = Field(default="", description="Claude's explanation for the strategy")

    @field_validator("allocations", mode="before")
    @classmethod
    def _coerce_allocations(cls, v):
        if not isinstance(v, dict):
            raise ValueError("allocations must be a dict")
        return {str(k): float(val) for k, val in v.items()}


class StrategyBundle(BaseModel):
    """The three strategies produced in one Strategy Agent cycle."""

    conservative: StrategyModel
    balanced: StrategyModel
    aggressive: StrategyModel
    based_on_sentiment: str = Field(default="neutral")
    timestamp: float = Field(default_factory=time.time)

    def as_list(self) -> list[StrategyModel]:
        return [self.conservative, self.balanced, self.aggressive]
