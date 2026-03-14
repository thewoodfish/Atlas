"""
Tests for MockWallet — balance accounting, tx recording, and edge cases.
"""
import pytest
from atlas.core.wallet import MockWallet, _make_tx_hash
from atlas.data.models import TxType


@pytest.fixture
def wallet(tmp_path):
    return MockWallet(initial_capital=1000.0, db_url=f"sqlite:///{tmp_path}/w.db")


class TestTxHash:
    def test_format(self):
        h = _make_tx_hash()
        assert h.startswith("0x")
        assert len(h) == 66
        assert all(c in "0123456789abcdef" for c in h[2:])

    def test_unique(self):
        hashes = {_make_tx_hash() for _ in range(100)}
        assert len(hashes) == 100


class TestInitialState:
    def test_initial_balance(self, wallet):
        assert wallet.get_balance() == 1000.0

    def test_no_deployed(self, wallet):
        snap = wallet.get_portfolio_snapshot()
        assert snap.allocations == {}
        assert snap.idle_usdt == 1000.0

    def test_zero_pnl_initially(self, wallet):
        snap = wallet.get_portfolio_snapshot()
        assert snap.pnl_usd == 0.0
        assert snap.pnl_pct == 0.0


class TestDeposit:
    def test_deposit_reduces_idle(self, wallet):
        wallet.deposit("Aave V3", 400.0)
        snap = wallet.get_portfolio_snapshot()
        assert snap.idle_usdt == pytest.approx(600.0)
        assert snap.allocations["Aave V3"] == pytest.approx(400.0)

    def test_total_balance_unchanged(self, wallet):
        wallet.deposit("Aave V3", 400.0)
        assert wallet.get_balance() == pytest.approx(1000.0)

    def test_deposit_tx_recorded(self, wallet):
        tx = wallet.deposit("Aave V3", 400.0)
        assert tx.tx_type == TxType.DEPOSIT
        assert tx.protocol == "Aave V3"
        assert tx.amount_usd == pytest.approx(400.0)

    def test_cannot_overdraft(self, wallet):
        with pytest.raises(ValueError, match="Insufficient idle"):
            wallet.deposit("Aave V3", 1001.0)

    def test_multiple_deposits_accumulate(self, wallet):
        wallet.deposit("Aave V3", 200.0)
        wallet.deposit("Aave V3", 150.0)
        snap = wallet.get_portfolio_snapshot()
        assert snap.allocations["Aave V3"] == pytest.approx(350.0)


class TestWithdraw:
    def test_withdraw_increases_idle(self, wallet):
        wallet.deposit("Aave V3", 400.0)
        wallet.withdraw("Aave V3", 150.0)
        snap = wallet.get_portfolio_snapshot()
        assert snap.idle_usdt == pytest.approx(750.0)
        assert snap.allocations["Aave V3"] == pytest.approx(250.0)

    def test_total_balance_unchanged(self, wallet):
        wallet.deposit("Aave V3", 400.0)
        wallet.withdraw("Aave V3", 400.0)
        assert wallet.get_balance() == pytest.approx(1000.0)

    def test_full_withdrawal_removes_protocol(self, wallet):
        wallet.deposit("Aave V3", 400.0)
        wallet.withdraw("Aave V3", 400.0)
        snap = wallet.get_portfolio_snapshot()
        assert "Aave V3" not in snap.allocations

    def test_cannot_overdraw_protocol(self, wallet):
        wallet.deposit("Aave V3", 400.0)
        with pytest.raises(ValueError, match="Insufficient balance"):
            wallet.withdraw("Aave V3", 401.0)

    def test_cannot_withdraw_from_empty_protocol(self, wallet):
        with pytest.raises(ValueError):
            wallet.withdraw("Nonexistent", 100.0)


class TestApplyStrategy:
    def test_balance_conserved(self, wallet):
        initial = wallet.get_balance()
        wallet.apply_strategy({"Aave V3": 40.0, "Curve Finance": 35.0, "Compound": 25.0})
        assert wallet.get_balance() == pytest.approx(initial, abs=0.01)

    def test_allocations_match_target(self, wallet):
        wallet.apply_strategy({"Aave V3": 50.0, "Curve Finance": 50.0})
        snap = wallet.get_portfolio_snapshot()
        assert snap.allocations["Aave V3"] == pytest.approx(500.0)
        assert snap.allocations["Curve Finance"] == pytest.approx(500.0)

    def test_rebalance_conserves_balance(self, wallet):
        wallet.apply_strategy({"Aave V3": 60.0, "Curve Finance": 40.0})
        before = wallet.get_balance()
        wallet.apply_strategy({"Aave V3": 30.0, "Compound": 40.0, "Curve Finance": 30.0})
        assert wallet.get_balance() == pytest.approx(before, abs=0.01)


class TestYieldAccrual:
    def test_yield_increases_balance(self, wallet):
        wallet.deposit("Aave V3", 500.0)
        wallet.accrue_yield("Aave V3", 1.50)
        assert wallet.get_balance() == pytest.approx(1001.50)

    def test_yield_reflected_in_pnl(self, wallet):
        wallet.deposit("Aave V3", 500.0)
        wallet.accrue_yield("Aave V3", 2.00)
        snap = wallet.get_portfolio_snapshot()
        assert snap.pnl_usd == pytest.approx(2.00)
        assert snap.pnl_pct > 0


class TestTxHistory:
    def test_history_records_all_txs(self, wallet):
        wallet.deposit("Aave V3", 400.0)
        wallet.deposit("Curve Finance", 300.0)
        wallet.withdraw("Aave V3", 100.0)
        assert len(wallet.tx_history()) == 3

    def test_db_history_matches_memory(self, wallet):
        wallet.deposit("Aave V3", 400.0)
        wallet.withdraw("Aave V3", 100.0)
        assert len(wallet.tx_history_db()) == 2
