"""
Central configuration for Atlas.
All values are loaded from environment variables with sensible defaults.
Import the singleton `config` object throughout the app.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # ── Anthropic ────────────────────────────────────────────────────────────
    anthropic_api_key: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "")
    )
    claude_model: str = field(
        default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    )

    # ── Wallet ───────────────────────────────────────────────────────────────
    wallet_address: str = field(
        default_factory=lambda: os.getenv(
            "WALLET_ADDRESS", "0x0000000000000000000000000000000000000000"
        )
    )
    tether_rpc_url: str = field(
        default_factory=lambda: os.getenv("TETHER_RPC_URL", "")
    )

    # ── DeFi data ────────────────────────────────────────────────────────────
    defi_llama_base_url: str = field(
        default_factory=lambda: os.getenv(
            "DEFI_LLAMA_BASE_URL", "https://api.llama.fi"
        )
    )

    # ── Atlas runtime ────────────────────────────────────────────────────────
    scan_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("SCAN_INTERVAL_SECONDS", "30"))
    )
    initial_portfolio_usdt: float = field(
        default_factory=lambda: float(os.getenv("INITIAL_PORTFOLIO_USDT", "100000.0"))
    )

    # ── Risk constraints ─────────────────────────────────────────────────────
    max_protocol_allocation: float = field(
        default_factory=lambda: float(os.getenv("MAX_PROTOCOL_ALLOCATION", "0.40"))
    )
    min_liquidity_usd: float = field(
        default_factory=lambda: float(os.getenv("MIN_LIQUIDITY_USD", "10_000_000"))
    )
    max_volatility_threshold: float = field(
        default_factory=lambda: float(os.getenv("MAX_VOLATILITY_THRESHOLD", "0.15"))
    )

    # ── Dashboard ────────────────────────────────────────────────────────────
    dashboard_host: str = field(
        default_factory=lambda: os.getenv("DASHBOARD_HOST", "0.0.0.0")
    )
    dashboard_port: int = field(
        default_factory=lambda: int(os.getenv("DASHBOARD_PORT", "5000"))
    )
    dashboard_debug: bool = field(
        default_factory=lambda: os.getenv("DASHBOARD_DEBUG", "false").lower() == "true"
    )

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///atlas.db")
    )

    # ── Logging ──────────────────────────────────────────────────────────────
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )
    log_file: str = field(
        default_factory=lambda: os.getenv("LOG_FILE", "logs/atlas.log")
    )


# Singleton used across the entire application
config = Config()
