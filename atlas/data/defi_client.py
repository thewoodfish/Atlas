"""
Async DeFi data client for Atlas.

Fetches yield opportunities from DeFiLlama's /pools endpoint, filters for
stablecoin/USDT pools, and returns structured OpportunityModel instances.

Features
--------
- Exponential-backoff retry on transient errors
- 30-second in-memory result cache to avoid rate limits
- Automatic fallback to realistic mock data when the API is unreachable
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import aiohttp
from loguru import logger

from atlas.data.models import FetchResult, OpportunityModel, PoolType
from config import config

# ── Constants ────────────────────────────────────────────────────────────────

YIELDS_URL = "https://yields.llama.fi/pools"
CACHE_TTL_SECONDS = 30
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.0  # doubles on each retry

# Stablecoin and gold-backed tokens we accept (case-insensitive match against pool symbol)
_STABLECOIN_TOKENS = {
    "usdt", "usdc", "dai", "frax", "tusd", "busd", "lusd", "gusd",
    "usdd", "susd", "usdp", "fei", "mim", "rai", "crvusd", "pyusd",
    # Tether Gold
    "xaut",
}

# ── Mock data ─────────────────────────────────────────────────────────────────

_MOCK_OPPORTUNITIES: list[dict[str, Any]] = [
    {
        "protocol": "Aave V3",
        "pool_id": "mock-aave-usdt",
        "apy": 6.2,
        "tvl_usd": 450_000_000,
        "volatility_7d": 0.008,
        "pool_type": PoolType.LENDING,
        "chain": "Ethereum",
        "symbol": "USDT",
    },
    {
        "protocol": "Curve Finance",
        "pool_id": "mock-curve-3pool",
        "apy": 9.1,
        "tvl_usd": 380_000_000,
        "volatility_7d": 0.012,
        "pool_type": PoolType.STABLE_SWAP,
        "chain": "Ethereum",
        "symbol": "3CRV (DAI/USDC/USDT)",
    },
    {
        "protocol": "Compound V3",
        "pool_id": "mock-compound-usdt",
        "apy": 5.8,
        "tvl_usd": 290_000_000,
        "volatility_7d": 0.006,
        "pool_type": PoolType.LENDING,
        "chain": "Ethereum",
        "symbol": "USDT",
    },
    {
        "protocol": "Yearn Finance",
        "pool_id": "mock-yearn-usdt",
        "apy": 12.8,
        "tvl_usd": 95_000_000,
        "volatility_7d": 0.031,
        "pool_type": PoolType.YIELD_VAULT,
        "chain": "Ethereum",
        "symbol": "USDT",
    },
    {
        "protocol": "Aave V3",
        "pool_id": "mock-aave-usdc",
        "apy": 5.9,
        "tvl_usd": 620_000_000,
        "volatility_7d": 0.007,
        "pool_type": PoolType.LENDING,
        "chain": "Ethereum",
        "symbol": "USDC",
    },
    {
        "protocol": "Curve Finance",
        "pool_id": "mock-curve-frax",
        "apy": 8.4,
        "tvl_usd": 210_000_000,
        "volatility_7d": 0.015,
        "pool_type": PoolType.STABLE_SWAP,
        "chain": "Ethereum",
        "symbol": "FRAX/USDC",
    },
    # Tether Gold (XAUT) pools
    {
        "protocol": "Curve Finance",
        "pool_id": "mock-curve-xaut-usdt",
        "apy": 4.8,
        "tvl_usd": 85_000_000,
        "volatility_7d": 0.018,
        "pool_type": PoolType.STABLE_SWAP,
        "chain": "Ethereum",
        "symbol": "XAUT/USDT",
    },
    {
        "protocol": "Aave V3",
        "pool_id": "mock-aave-xaut",
        "apy": 3.2,
        "tvl_usd": 42_000_000,
        "volatility_7d": 0.022,
        "pool_type": PoolType.LENDING,
        "chain": "Ethereum",
        "symbol": "XAUT",
    },
]


def _mock_opportunities() -> list[OpportunityModel]:
    return [OpportunityModel(is_stablecoin=True, **d) for d in _MOCK_OPPORTUNITIES]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_stablecoin_pool(symbol: str) -> bool:
    """Return True if at least one token in the pool symbol is a stablecoin."""
    sym_lower = symbol.lower()
    return any(token in sym_lower for token in _STABLECOIN_TOKENS)


def _infer_pool_type(project: str) -> PoolType:
    p = project.lower()
    if any(k in p for k in ("aave", "compound", "morpho", "euler", "spark")):
        return PoolType.LENDING
    if any(k in p for k in ("curve", "balancer", "saddle", "platypus")):
        return PoolType.STABLE_SWAP
    if any(k in p for k in ("yearn", "beefy", "convex", "harvest", "idle")):
        return PoolType.YIELD_VAULT
    if any(k in p for k in ("uniswap", "sushiswap", "pancake", "camelot")):
        return PoolType.LIQUIDITY_POOL
    return PoolType.UNKNOWN


def _parse_pool(raw: dict[str, Any]) -> OpportunityModel | None:
    """Parse a single DeFiLlama pool dict into an OpportunityModel, or None."""
    try:
        symbol: str = raw.get("symbol", "") or ""
        if not _is_stablecoin_pool(symbol):
            return None

        project: str = raw.get("project", "Unknown")
        pool_id: str = raw.get("pool", project + "-" + symbol)
        apy: float = raw.get("apy") or 0.0
        tvl: float = raw.get("tvlUsd") or 0.0
        vol_7d: float = (raw.get("apyPct7D") or 0.0) / 100.0  # convert % → fraction
        chain: str = raw.get("chain", "Unknown")

        # Skip dust pools
        if tvl < 1_000:
            return None

        return OpportunityModel(
            protocol=project,
            pool_id=pool_id,
            apy=apy,
            tvl_usd=tvl,
            volatility_7d=abs(vol_7d),
            pool_type=_infer_pool_type(project),
            chain=chain,
            symbol=symbol,
            is_stablecoin=True,
        )
    except Exception as exc:
        logger.debug(f"Skipping pool due to parse error: {exc}")
        return None


# ── Client ───────────────────────────────────────────────────────────────────

class DeFiClient:
    """Async client for fetching DeFi yield opportunities."""

    def __init__(self) -> None:
        self._cache: FetchResult | None = None
        self._cache_ts: float = 0.0
        self._session: aiohttp.ClientSession | None = None

    # ── Session lifecycle ────────────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": "Atlas-Treasury-Bot/1.0"},
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Core fetch with retry ────────────────────────────────────────────────

    async def _fetch_raw(self) -> list[dict[str, Any]]:
        """Fetch raw pool list from DeFiLlama with exponential-backoff retry."""
        session = await self._get_session()
        last_exc: Exception = RuntimeError("No attempts made")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.debug(f"DeFiLlama fetch attempt {attempt}/{MAX_RETRIES}")
                async with session.get(YIELDS_URL) as resp:
                    resp.raise_for_status()
                    payload = await resp.json()
                    pools: list[dict] = payload.get("data", [])
                    logger.info(f"DeFiLlama returned {len(pools)} pools")
                    return pools
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    backoff = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        f"DeFiLlama request failed ({exc}), "
                        f"retrying in {backoff:.1f}s…"
                    )
                    await asyncio.sleep(backoff)

        raise last_exc

    # ── Public API ───────────────────────────────────────────────────────────

    async def fetch_opportunities(self) -> FetchResult:
        """
        Return filtered stablecoin yield opportunities.

        Uses a 30-second cache. Falls back to mock data on API failure.
        """
        now = time.monotonic()

        # Return cached result if still fresh
        if self._cache is not None and (now - self._cache_ts) < CACHE_TTL_SECONDS:
            logger.debug("Returning cached DeFi opportunities")
            return self._cache

        # Try live fetch
        try:
            raw_pools = await self._fetch_raw()
            opportunities: list[OpportunityModel] = []
            for raw in raw_pools:
                opp = _parse_pool(raw)
                if opp is not None:
                    opportunities.append(opp)

            # Sort by APY descending for convenience
            opportunities.sort(key=lambda o: o.apy, reverse=True)

            logger.info(
                f"Fetched {len(opportunities)} stablecoin opportunities from DeFiLlama"
            )
            result = FetchResult(
                opportunities=opportunities,
                source="live",
                fetched_at=time.time(),
            )

        except Exception as exc:
            logger.warning(
                f"DeFiLlama unavailable ({exc}), falling back to mock data"
            )
            result = FetchResult(
                opportunities=_mock_opportunities(),
                source="mock",
                fetched_at=time.time(),
                error=str(exc),
            )

        self._cache = result
        self._cache_ts = now
        return result

    async def force_refresh(self) -> FetchResult:
        """Bypass cache and force a fresh fetch."""
        self._cache = None
        self._cache_ts = 0.0
        return await self.fetch_opportunities()
