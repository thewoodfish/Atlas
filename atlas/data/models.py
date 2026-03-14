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


# ── Risk models ───────────────────────────────────────────────────────────────

class RiskFlag(str, Enum):
    CONCENTRATION = "concentration"       # >40% in one protocol
    LOW_LIQUIDITY = "low_liquidity"       # TVL < $10M
    HIGH_RISK_SCORE = "high_risk_score"   # risk_score > 8
    HIGH_VOLATILITY = "high_volatility"   # volatility_7d > 15%
    CORRELATION = "correlation"           # qualitative: Claude-identified
    MARKET_CONDITIONS = "market_conditions"
    OTHER = "other"


class RiskAssessment(BaseModel):
    """Output from the Risk Manager Agent."""

    approved: bool = Field(..., description="Whether the selected strategy is approved")
    selected_strategy: StrategyModel = Field(..., description="The strategy to execute")
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    adjustments: list[str] = Field(
        default_factory=list,
        description="Suggested allocation adjustments from Claude",
    )
    reasoning: str = Field(default="", description="Full qualitative reasoning")
    is_capital_preservation: bool = Field(
        default=False,
        description="True if all strategies were rejected and fallback was used",
    )
    timestamp: float = Field(default_factory=time.time)

    model_config = {"use_enum_values": True}


# ── Simulation models ─────────────────────────────────────────────────────────

class DailySnapshot(BaseModel):
    """Portfolio value at end of one simulated day."""

    day: int = Field(..., ge=0)
    portfolio_value_usd: float
    yield_earned_usd: float
    cumulative_yield_usd: float


class SimulationResult(BaseModel):
    """Output from the Simulator for one approved strategy."""

    strategy_name: str
    principal_usd: float
    projected_7d_yield: float = Field(description="Total yield over 7 days in USD")
    projected_apy: float = Field(description="Annualised yield (%)")
    estimated_gas_usd: float = Field(description="Estimated total gas cost in USD")
    net_return: float = Field(description="projected_7d_yield minus estimated_gas_usd")
    confidence_score: float = Field(ge=0.0, le=1.0, description="0-1 confidence in projection")
    approved: bool = Field(description="False if net_return is negative")
    rejection_reason: Optional[str] = Field(default=None)
    daily_snapshots: list[DailySnapshot] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)


# ── Wallet models ─────────────────────────────────────────────────────────────

class TxType(str, Enum):
    DEPOSIT  = "deposit"
    WITHDRAW = "withdraw"
    SWAP     = "swap"
    REBALANCE = "rebalance"


class TransactionRecord(BaseModel):
    """An immutable record of a simulated (or real) wallet transaction."""

    tx_hash: str
    tx_type: TxType
    protocol: str
    from_token: str = Field(default="USDT")
    to_token: str   = Field(default="USDT")
    amount_usd: float
    timestamp: float = Field(default_factory=time.time)
    status: str = Field(default="confirmed")

    model_config = {"use_enum_values": True}


class PortfolioSnapshot(BaseModel):
    """Point-in-time view of the wallet's portfolio."""

    total_value_usd: float
    allocations: dict[str, float] = Field(
        description="protocol -> USD amount currently deployed"
    )
    idle_usdt: float = Field(description="Undeployed USDT balance")
    pnl_usd: float   = Field(description="Profit/loss vs initial capital in USD")
    pnl_pct: float   = Field(description="Profit/loss as a percentage")
    timestamp: float = Field(default_factory=time.time)
