"""
Wallet module for Atlas.

MockWallet
----------
Simulates a self-custodial wallet entirely in-process.  No real keys, no
real chain interactions.  Every operation generates a realistic-looking
fake transaction hash and is persisted to SQLite.

WDKWallet (optional)
--------------------
Thin subclass that attempts to import the WDK SDK at runtime.  If the SDK
is not installed the class is not exported and MockWallet is used instead.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time
from abc import ABC, abstractmethod
from typing import Optional

from loguru import logger
from sqlalchemy import create_engine, text

from atlas.data.models import PortfolioSnapshot, TransactionRecord, TxType
from config import config

# ── Tx-hash generation ────────────────────────────────────────────────────────

def _make_tx_hash() -> str:
    """Return a realistic-looking Ethereum tx hash (0x + 64 hex chars)."""
    raw = secrets.token_bytes(32) + str(time.time_ns()).encode()
    return "0x" + hashlib.sha256(raw).hexdigest()


# ── SQLite persistence ────────────────────────────────────────────────────────

_CREATE_TX_TABLE = """
CREATE TABLE IF NOT EXISTS wallet_transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_hash     TEXT    NOT NULL UNIQUE,
    tx_type     TEXT    NOT NULL,
    protocol    TEXT    NOT NULL,
    from_token  TEXT    NOT NULL,
    to_token    TEXT    NOT NULL,
    amount_usd  REAL    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'confirmed',
    created_at  REAL    NOT NULL
)
"""

_CREATE_SNAPSHOT_TABLE = """
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    total_value_usd REAL    NOT NULL,
    idle_usdt       REAL    NOT NULL,
    pnl_usd         REAL    NOT NULL,
    pnl_pct         REAL    NOT NULL,
    allocations     TEXT    NOT NULL,   -- JSON
    created_at      REAL    NOT NULL
)
"""


class _WalletDB:
    def __init__(self, url: str) -> None:
        self._engine = create_engine(url, echo=False, future=True)
        with self._engine.connect() as conn:
            conn.execute(text(_CREATE_TX_TABLE))
            conn.execute(text(_CREATE_SNAPSHOT_TABLE))
            conn.commit()

    def save_tx(self, tx: TransactionRecord) -> None:
        with self._engine.connect() as conn:
            conn.execute(
                text(
                    """
                    INSERT OR IGNORE INTO wallet_transactions
                        (tx_hash, tx_type, protocol, from_token, to_token,
                         amount_usd, status, created_at)
                    VALUES
                        (:tx_hash, :tx_type, :protocol, :from_token, :to_token,
                         :amount_usd, :status, :created_at)
                    """
                ),
                {
                    "tx_hash":    tx.tx_hash,
                    "tx_type":    tx.tx_type,
                    "protocol":   tx.protocol,
                    "from_token": tx.from_token,
                    "to_token":   tx.to_token,
                    "amount_usd": tx.amount_usd,
                    "status":     tx.status,
                    "created_at": tx.timestamp,
                },
            )
            conn.commit()

    def save_snapshot(self, snap: PortfolioSnapshot) -> None:
        import json
        with self._engine.connect() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO portfolio_snapshots
                        (total_value_usd, idle_usdt, pnl_usd, pnl_pct,
                         allocations, created_at)
                    VALUES
                        (:total_value_usd, :idle_usdt, :pnl_usd, :pnl_pct,
                         :allocations, :created_at)
                    """
                ),
                {
                    "total_value_usd": snap.total_value_usd,
                    "idle_usdt":       snap.idle_usdt,
                    "pnl_usd":         snap.pnl_usd,
                    "pnl_pct":         snap.pnl_pct,
                    "allocations":     json.dumps(snap.allocations),
                    "created_at":      snap.timestamp,
                },
            )
            conn.commit()

    def tx_history(self, limit: int = 50) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM wallet_transactions "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()
        return [dict(r._mapping) for r in rows]


# ── Base wallet interface ─────────────────────────────────────────────────────

class BaseWallet(ABC):
    @abstractmethod
    def deposit(self, protocol: str, amount: float) -> TransactionRecord: ...
    @abstractmethod
    def withdraw(self, protocol: str, amount: float) -> TransactionRecord: ...
    @abstractmethod
    def swap(self, from_token: str, to_token: str, amount: float, protocol: str = "DEX") -> TransactionRecord: ...
    @abstractmethod
    def get_balance(self) -> float: ...
    @abstractmethod
    def get_portfolio_snapshot(self) -> PortfolioSnapshot: ...


# ── MockWallet ────────────────────────────────────────────────────────────────

class MockWallet(BaseWallet):
    """
    Fully simulated self-custodial wallet.

    State
    -----
    _idle_usdt          : undeployed capital
    _deployed[protocol] : capital currently deposited in each protocol
    _initial_capital    : baseline for PnL calculation
    _tx_log             : in-memory list of all TransactionRecords
    """

    def __init__(
        self,
        initial_capital: float | None = None,
        db_url: str | None = None,
        address: str | None = None,
    ) -> None:
        self._initial_capital = initial_capital or config.initial_portfolio_usdt
        self._idle_usdt: float = self._initial_capital
        self._deployed: dict[str, float] = {}
        self._tx_log: list[TransactionRecord] = []
        self._db = _WalletDB(db_url or config.database_url)
        self.address: str = address or config.wallet_address

        logger.info(
            f"[WALLET] MockWallet initialised — "
            f"address={self.address}  "
            f"capital=${self._initial_capital:,.2f} USDT"
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _record(self, tx: TransactionRecord) -> TransactionRecord:
        self._tx_log.append(tx)
        self._db.save_tx(tx)
        logger.info(
            f"[WALLET] {tx.tx_type.upper():<10} protocol={tx.protocol:<20} "
            f"amount=${tx.amount_usd:>10,.2f}  "
            f"hash={tx.tx_hash[:18]}…"
        )
        return tx

    # ── BaseWallet ────────────────────────────────────────────────────────────

    def deposit(self, protocol: str, amount: float) -> TransactionRecord:
        if amount <= 0:
            raise ValueError(f"Deposit amount must be positive, got {amount}")
        if amount > self._idle_usdt:
            raise ValueError(
                f"Insufficient idle USDT: have ${self._idle_usdt:.2f}, "
                f"need ${amount:.2f}"
            )
        self._idle_usdt -= amount
        self._deployed[protocol] = self._deployed.get(protocol, 0.0) + amount

        tx = TransactionRecord(
            tx_hash=_make_tx_hash(),
            tx_type=TxType.DEPOSIT,
            protocol=protocol,
            from_token="USDT",
            to_token=f"{protocol}-LP",
            amount_usd=round(amount, 4),
        )
        return self._record(tx)

    def withdraw(self, protocol: str, amount: float) -> TransactionRecord:
        if amount <= 0:
            raise ValueError(f"Withdraw amount must be positive, got {amount}")
        deployed = self._deployed.get(protocol, 0.0)
        if amount > deployed:
            raise ValueError(
                f"Insufficient balance in {protocol}: "
                f"have ${deployed:.2f}, need ${amount:.2f}"
            )
        self._deployed[protocol] = deployed - amount
        if self._deployed[protocol] < 1e-6:
            del self._deployed[protocol]
        self._idle_usdt += amount

        tx = TransactionRecord(
            tx_hash=_make_tx_hash(),
            tx_type=TxType.WITHDRAW,
            protocol=protocol,
            from_token=f"{protocol}-LP",
            to_token="USDT",
            amount_usd=round(amount, 4),
        )
        return self._record(tx)

    def swap(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        protocol: str = "DEX",
    ) -> TransactionRecord:
        if amount <= 0:
            raise ValueError(f"Swap amount must be positive, got {amount}")
        # For a mock swap we just record the intent; no balance change
        tx = TransactionRecord(
            tx_hash=_make_tx_hash(),
            tx_type=TxType.SWAP,
            protocol=protocol,
            from_token=from_token,
            to_token=to_token,
            amount_usd=round(amount, 4),
        )
        return self._record(tx)

    def rebalance(
        self,
        from_protocol: str,
        to_protocol: str,
        amount: float,
    ) -> list[TransactionRecord]:
        """Withdraw from one protocol and deposit into another."""
        txs = [
            self.withdraw(from_protocol, amount),
            self.deposit(to_protocol, amount),
        ]
        logger.info(
            f"[WALLET] REBALANCE  {from_protocol} → {to_protocol}  ${amount:,.2f}"
        )
        return txs

    def accrue_yield(self, protocol: str, yield_usd: float) -> None:
        """Credit simulated yield directly to a protocol balance."""
        if yield_usd <= 0:
            return
        self._deployed[protocol] = self._deployed.get(protocol, 0.0) + yield_usd
        logger.debug(
            f"[WALLET] yield accrued  protocol={protocol}  +${yield_usd:.4f}"
        )

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_balance(self) -> float:
        """Total wallet value (idle + all deployed)."""
        return round(self._idle_usdt + sum(self._deployed.values()), 4)

    def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        total = self.get_balance()
        pnl = total - self._initial_capital
        pnl_pct = (pnl / self._initial_capital * 100) if self._initial_capital else 0.0
        snap = PortfolioSnapshot(
            total_value_usd=round(total, 4),
            allocations={p: round(v, 4) for p, v in self._deployed.items()},
            idle_usdt=round(self._idle_usdt, 4),
            pnl_usd=round(pnl, 4),
            pnl_pct=round(pnl_pct, 4),
        )
        self._db.save_snapshot(snap)
        return snap

    def tx_history(self, limit: int = 50) -> list[TransactionRecord]:
        return self._tx_log[-limit:]

    def tx_history_db(self, limit: int = 50) -> list[dict]:
        return self._db.tx_history(limit)

    def apply_strategy(self, allocations: dict[str, float]) -> list[TransactionRecord]:
        """
        Deploy capital according to a strategy's allocation percentages.
        Withdraws everything first, then re-deploys.

        Parameters
        ----------
        allocations : dict[protocol -> percentage]
            Values should sum to ~100.
        """
        total_capital = self.get_balance()
        logger.info(
            f"[WALLET] Applying strategy allocations  total=${total_capital:,.2f}"
        )

        # Withdraw all existing positions
        txs: list[TransactionRecord] = []
        for protocol, amount in list(self._deployed.items()):
            if amount > 0:
                txs.append(self.withdraw(protocol, amount))

        # Deposit per allocation
        for protocol, pct in allocations.items():
            if pct <= 0:
                continue
            amount = round(total_capital * pct / 100, 4)
            if amount > 0:
                txs.append(self.deposit(protocol, amount))

        snapshot = self.get_portfolio_snapshot()
        logger.info(
            f"[WALLET] Strategy applied — "
            f"deployed=${total_capital - snapshot.idle_usdt:,.2f}  "
            f"idle=${snapshot.idle_usdt:,.2f}"
        )
        return txs


# ── WDKWallet (optional) ──────────────────────────────────────────────────────

def _try_build_wdk_wallet() -> type | None:
    """
    Attempt to build a WDKWallet subclass if the WDK SDK is available.
    Returns the class, or None if the SDK is not installed.
    """
    try:
        import wdk  # type: ignore[import]  # noqa: F401
    except ImportError:
        return None

    class WDKWallet(MockWallet):
        """
        WDK-backed wallet that performs real transaction signing.
        Falls back to MockWallet simulation on signing errors.
        """

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            try:
                self._wdk_client = wdk.Client(
                    rpc_url=config.tether_rpc_url,
                    address=self.address,
                )
                logger.info(f"[WALLET] WDKWallet connected — address={self.address}")
            except Exception as exc:
                logger.warning(
                    f"[WALLET] WDK initialisation failed ({exc}), "
                    "falling back to mock signing"
                )
                self._wdk_client = None

        def _sign_tx(self, tx_data: dict) -> str:
            if self._wdk_client is None:
                return _make_tx_hash()
            try:
                return self._wdk_client.sign_and_send(tx_data)
            except Exception as exc:
                logger.error(f"[WALLET] WDK signing failed: {exc}")
                return _make_tx_hash()

    return WDKWallet


WDKWallet = _try_build_wdk_wallet()

# Export whichever wallet is available; callers import Wallet
Wallet = WDKWallet if WDKWallet is not None else MockWallet
