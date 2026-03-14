"""
Pydantic data models for Atlas DeFi data layer.
"""
from __future__ import annotations

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
