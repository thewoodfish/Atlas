"""
Tests for the Simulation Engine — projection math and approval logic.
"""
import pytest
from atlas.core.simulator import _daily_rate, _estimate_gas, _estimate_slippage, _run_projection, _confidence_score
from atlas.data.models import OpportunityModel, RiskAssessment, StrategyModel, SimulationResult
from atlas.core.simulator import Simulator


def _strat(allocations=None, yield_=7.0, risk=5):
    return StrategyModel(
        name="Test",
        allocations=allocations or {"Aave V3": 50.0, "Curve Finance": 50.0},
        expected_yield=yield_,
        risk_score=risk,
    )


def _opp(protocol, apy=7.0, pool_type="lending", vol=0.01, tvl=100_000_000):
    return OpportunityModel(protocol=protocol, pool_id=f"{protocol}-id",
                            apy=apy, tvl_usd=tvl, volatility_7d=vol, pool_type=pool_type)


class TestDailyRate:
    def test_zero_apy(self):
        assert _daily_rate(0) == 0.0

    def test_365_apy_approx_doubles(self):
        # (1 + 3.65/100)^365 ≈ 37x; daily rate ≈ 0.01
        rate = _daily_rate(3.65)
        assert abs(rate - 0.0001) < 1e-4

    def test_compounding_over_year(self):
        # 10% APY daily compound for 365 days should give ~10% total
        daily = _daily_rate(10)
        total = (1 + daily) ** 365 - 1
        assert abs(total - 0.10) < 0.001


class TestGasEstimate:
    def test_lending_cheaper_than_vault(self):
        lending_strat  = _strat({"Aave V3": 100.0})
        vault_strat    = _strat({"Yearn Finance": 100.0})
        gas_lending = _estimate_gas(lending_strat,  {"Aave V3": "lending"})
        gas_vault   = _estimate_gas(vault_strat,    {"Yearn Finance": "yield_vault"})
        assert gas_vault > gas_lending

    def test_more_protocols_means_more_gas(self):
        one  = _strat({"Aave V3": 100.0})
        three = _strat({"Aave V3": 40.0, "Curve": 35.0, "Compound": 25.0})
        g1 = _estimate_gas(one,   {"Aave V3": "lending"})
        g3 = _estimate_gas(three, {"Aave V3": "lending", "Curve": "stable_swap", "Compound": "lending"})
        assert g3 > g1


class TestSlippage:
    def test_lending_has_lower_slippage_than_lp(self):
        s = _strat({"Protocol": 100.0})
        lend_slip = _estimate_slippage(s, 10_000, {"Protocol": "lending"})
        lp_slip   = _estimate_slippage(s, 10_000, {"Protocol": "liquidity_pool"})
        assert lp_slip > lend_slip

    def test_larger_principal_higher_slippage(self):
        s = _strat({"Aave V3": 100.0})
        s1 = _estimate_slippage(s, 1_000,   {"Aave V3": "lending"})
        s2 = _estimate_slippage(s, 100_000, {"Aave V3": "lending"})
        assert s2 > s1


class TestProjection:
    def test_seven_snapshots_returned(self):
        s = _strat({"Aave V3": 100.0})
        opps = [_opp("Aave V3")]
        snaps, total = _run_projection(s, 1000.0, opps, days=7)
        assert len(snaps) == 7

    def test_portfolio_value_increases(self):
        s = _strat({"Aave V3": 100.0})
        opps = [_opp("Aave V3", apy=10.0)]
        snaps, _ = _run_projection(s, 1000.0, opps)
        values = [snap.portfolio_value_usd for snap in snaps]
        assert values == sorted(values)

    def test_total_yield_positive_for_positive_apy(self):
        s = _strat({"Aave V3": 100.0})
        opps = [_opp("Aave V3", apy=10.0)]
        _, total_yield = _run_projection(s, 1000.0, opps)
        assert total_yield > 0

    def test_cumulative_yield_matches_final_snapshot(self):
        s = _strat({"Aave V3": 100.0})
        opps = [_opp("Aave V3", apy=6.0)]
        snaps, total = _run_projection(s, 1000.0, opps)
        assert abs(snaps[-1].cumulative_yield_usd - total) < 0.01


class TestConfidenceScore:
    def test_live_data_higher_than_mock(self):
        s = _strat()
        opps = [_opp("Aave V3"), _opp("Curve Finance")]
        live = _confidence_score(s, opps, "live")
        mock = _confidence_score(s, opps, "mock")
        assert live > mock

    def test_high_volatility_penalises_score(self):
        s = _strat()
        low_vol_opps  = [_opp("Aave V3", vol=0.01), _opp("Curve Finance", vol=0.01)]
        high_vol_opps = [_opp("Aave V3", vol=0.25), _opp("Curve Finance", vol=0.25)]
        low  = _confidence_score(s, low_vol_opps,  "live")
        high = _confidence_score(s, high_vol_opps, "live")
        assert high < low

    def test_score_bounded_zero_to_one(self):
        s = _strat(risk=10)
        opps = [_opp("Aave V3", vol=0.5)]
        score = _confidence_score(s, opps, "mock")
        assert 0.0 <= score <= 1.0


class TestSimulatorApproval:
    def test_approved_when_net_positive(self, tmp_path):
        sim = Simulator(principal_usd=1_000_000, db_url=f"sqlite:///{tmp_path}/sim.db")
        s = _strat({"Aave V3": 50.0, "Curve Finance": 50.0}, yield_=20.0)
        assessment = RiskAssessment(approved=True, selected_strategy=s)
        opps = [_opp("Aave V3", apy=20.0), _opp("Curve Finance", apy=20.0)]
        result = sim.run(assessment, opps)
        assert result.approved is True
        assert result.net_return > 0

    def test_rejected_when_gas_exceeds_yield(self, tmp_path):
        # Tiny principal: gas will exceed 7-day yield
        sim = Simulator(principal_usd=100, db_url=f"sqlite:///{tmp_path}/sim2.db")
        s = _strat({"Aave V3": 100.0}, yield_=6.0)
        assessment = RiskAssessment(approved=True, selected_strategy=s)
        opps = [_opp("Aave V3", apy=6.0)]
        result = sim.run(assessment, opps)
        assert result.approved is False
        assert result.net_return < 0
        assert result.rejection_reason is not None

    def test_history_persisted(self, tmp_path):
        sim = Simulator(principal_usd=1_000_000, db_url=f"sqlite:///{tmp_path}/sim3.db")
        s = _strat()
        assessment = RiskAssessment(approved=True, selected_strategy=s)
        sim.run(assessment, [_opp("Aave V3"), _opp("Curve Finance")])
        sim.run(assessment, [_opp("Aave V3"), _opp("Curve Finance")])
        history = sim.history()
        assert len(history) == 2
