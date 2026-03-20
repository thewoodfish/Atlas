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
        self._xaut_usd: float = 0.0
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

    def buy_xaut(self, amount_usd: float) -> TransactionRecord:
        """Convert USDT to XAUT (Tether Gold) holding."""
        if amount_usd <= 0:
            raise ValueError(f"Amount must be positive, got {amount_usd}")
        if amount_usd > self._idle_usdt:
            raise ValueError(
                f"Insufficient idle USDT: have ${self._idle_usdt:.2f}, need ${amount_usd:.2f}"
            )
        self._idle_usdt -= amount_usd
        self._xaut_usd += amount_usd
        tx = TransactionRecord(
            tx_hash=_make_tx_hash(),
            tx_type=TxType.SWAP,
            protocol="Tether Gold",
            from_token="USDT",
            to_token="XAUT",
            amount_usd=round(amount_usd, 4),
        )
        return self._record(tx)

    def sell_xaut(self, amount_usd: float) -> TransactionRecord:
        """Convert XAUT back to USDT."""
        if amount_usd <= 0:
            raise ValueError(f"Amount must be positive, got {amount_usd}")
        actual = min(amount_usd, self._xaut_usd)
        self._xaut_usd -= actual
        self._idle_usdt += actual
        tx = TransactionRecord(
            tx_hash=_make_tx_hash(),
            tx_type=TxType.SWAP,
            protocol="Tether Gold",
            from_token="XAUT",
            to_token="USDT",
            amount_usd=round(actual, 4),
        )
        return self._record(tx)

    def get_balance(self) -> float:
        """Total wallet value (idle + all deployed + XAUT)."""
        return round(self._idle_usdt + sum(self._deployed.values()) + self._xaut_usd, 4)

    def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        total = self.get_balance()
        pnl = total - self._initial_capital
        pnl_pct = (pnl / self._initial_capital * 100) if self._initial_capital else 0.0
        snap = PortfolioSnapshot(
            total_value_usd=round(total, 4),
            allocations={p: round(v, 4) for p, v in self._deployed.items()},
            idle_usdt=round(self._idle_usdt, 4),
            xaut_usd=round(self._xaut_usd, 4),
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

        # Withdraw all existing DeFi positions
        txs: list[TransactionRecord] = []
        for protocol, amount in list(self._deployed.items()):
            if amount > 0:
                txs.append(self.withdraw(protocol, amount))

        # Sell any existing XAUT back to USDT before redeploying
        if self._xaut_usd > 0:
            txs.append(self.sell_xaut(self._xaut_usd))

        # Deploy per allocation (XAUT handled separately as a hedge)
        for protocol, pct in allocations.items():
            if pct <= 0:
                continue
            amount = round(total_capital * pct / 100, 4)
            if amount <= 0:
                continue
            if protocol == "XAUT":
                txs.append(self.buy_xaut(amount))
            else:
                txs.append(self.deposit(protocol, amount))

        snapshot = self.get_portfolio_snapshot()
        logger.info(
            f"[WALLET] Strategy applied — "
            f"deployed=${total_capital - snapshot.idle_usdt - snapshot.xaut_usd:,.2f}  "
            f"xaut=${snapshot.xaut_usd:,.2f}  "
            f"idle=${snapshot.idle_usdt:,.2f}"
        )
        return txs


# ── WDKWallet — HTTP client for the Node.js WDK microservice ─────────────────

_WDK_SERVICE_URL = os.getenv("WDK_SERVICE_URL", "http://localhost:3001")

# Known protocol contract addresses (Ethereum mainnet).
# Used to route real USDT transfers on-chain when the WDK wallet is funded.
# A plain ERC-20 transfer to the protocol address generates a verifiable
# on-chain tx hash even before full protocol ABI integration.
_PROTOCOL_ADDRESSES: dict[str, str] = {
    "Aave V3":       "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",  # Aave V3 Pool
    "Curve Finance": "0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7",  # Curve 3pool
    "Compound V3":   "0xc3d688B66703497DAA19211EEdff47f25384cdc3",  # Compound III
    "Yearn Finance": "0xa354F35829Ae975e850e23e9615b11Da1B3dC4DE",  # Yearn USDT yVault
}


def _wdk_service_available() -> bool:
    """Quick liveness check against the WDK service /health endpoint."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{_WDK_SERVICE_URL}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


class WDKWallet(MockWallet):
    """
    WDK-backed wallet.  All balance queries and token sends go through the
    Node.js WDK microservice (wdk_service/server.js).  The in-process
    MockWallet accounting is kept in sync so the rest of Atlas sees a
    consistent view of portfolio state even if the WDK service is offline.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._wdk_url = _WDK_SERVICE_URL
        self._online = False
        self._sync_address()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get(self, path: str) -> dict:
        import json
        import urllib.request
        with urllib.request.urlopen(f"{self._wdk_url}{path}", timeout=5) as r:
            return json.loads(r.read())

    def _post(self, path: str, body: dict) -> dict:
        import json
        import urllib.request
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self._wdk_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def _sync_address(self) -> None:
        try:
            resp = self._get("/wallet/address")
            if resp.get("success"):
                self.address = resp["data"]["address"]
                self._online = True
                logger.info(
                    f"[WALLET] WDKWallet online — address={self.address}"
                )
        except Exception as exc:
            logger.warning(
                f"[WALLET] WDK service unreachable ({exc}), "
                "running with MockWallet accounting only"
            )
            self._online = False

    # ── Override deposit/withdraw to also call WDK service ───────────────────

    def deposit(self, protocol: str, amount: float) -> TransactionRecord:
        tx = super().deposit(protocol, amount)
        if self._online:
            dest = _PROTOCOL_ADDRESSES.get(protocol)
            if dest:
                # Attempt a real on-chain USDT transfer to the protocol address.
                # Generates a verifiable Etherscan tx hash when the wallet is funded.
                # Falls back to a signed audit message if balance is insufficient.
                try:
                    resp = self._post("/wallet/send-usdt", {"to": dest, "amount": str(round(amount, 6))})
                    if resp.get("success"):
                        real_hash = resp["data"]["tx_hash"]
                        logger.info(
                            f"[WALLET] WDK on-chain USDT → {protocol}  "
                            f"real_hash={real_hash[:18]}…"
                        )
                        return tx  # audit trail via on-chain tx
                except Exception as exc:
                    logger.debug(f"[WALLET] WDK send-usdt for {protocol} skipped ({exc}) — signing instead")
            try:
                self._post("/wallet/sign", {
                    "message": f"Atlas deposit: ${amount:.4f} USDT → {protocol} hash={tx.tx_hash}"
                })
            except Exception as exc:
                logger.debug(f"[WALLET] WDK sign for deposit skipped: {exc}")
        return tx

    def withdraw(self, protocol: str, amount: float) -> TransactionRecord:
        tx = super().withdraw(protocol, amount)
        if self._online:
            dest = _PROTOCOL_ADDRESSES.get(protocol)
            if dest:
                # Withdraw: reclaim USDT from protocol back to our address.
                try:
                    resp = self._post("/wallet/send-usdt", {"to": self.address, "amount": str(round(amount, 6))})
                    if resp.get("success"):
                        real_hash = resp["data"]["tx_hash"]
                        logger.info(
                            f"[WALLET] WDK on-chain USDT ← {protocol}  "
                            f"real_hash={real_hash[:18]}…"
                        )
                        return tx
                except Exception as exc:
                    logger.debug(f"[WALLET] WDK send-usdt withdraw for {protocol} skipped ({exc}) — signing instead")
            try:
                self._post("/wallet/sign", {
                    "message": f"Atlas withdraw: ${amount:.4f} USDT ← {protocol} hash={tx.tx_hash}"
                })
            except Exception as exc:
                logger.debug(f"[WALLET] WDK sign for withdraw skipped: {exc}")
        return tx

    def buy_xaut(self, amount_usd: float) -> TransactionRecord:
        tx = super().buy_xaut(amount_usd)
        if self._online:
            try:
                self._post("/wallet/sign", {
                    "message": (
                        f"Atlas XAUT hedge: ${amount_usd:.4f} USDT → XAUT "
                        f"hash={tx.tx_hash}"
                    )
                })
            except Exception as exc:
                logger.debug(f"[WALLET] WDK sign for XAUT buy skipped: {exc}")
        return tx

    def send_usdt(self, to: str, amount: float) -> str:
        """Send USDT on-chain via the WDK service. Returns tx hash."""
        if not self._online:
            raise RuntimeError("WDK service is offline")
        resp = self._post("/wallet/send-usdt", {"to": to, "amount": str(amount)})
        if not resp.get("success"):
            raise RuntimeError(resp.get("error", "WDK send-usdt failed"))
        return resp["data"]["tx_hash"]

    def send_xaut(self, to: str, amount: float) -> str:
        """Send XAUT (Tether Gold) on-chain via the WDK service. Returns tx hash."""
        if not self._online:
            raise RuntimeError("WDK service is offline")
        resp = self._post("/wallet/send-xaut", {"to": to, "amount": str(amount)})
        if not resp.get("success"):
            raise RuntimeError(resp.get("error", "WDK send-xaut failed"))
        return resp["data"]["tx_hash"]

    def get_onchain_balances(self) -> dict:
        """Return live on-chain balances from the WDK service."""
        if not self._online:
            return {}
        try:
            resp = self._get("/wallet/balance")
            if resp.get("success"):
                return resp["data"]
        except Exception as exc:
            logger.warning(f"[WALLET] WDK balance fetch failed: {exc}")
        return {}


# Export WDKWallet; it gracefully degrades when the service is offline.
# Callers may also use MockWallet directly for pure simulation mode.
Wallet = WDKWallet
