"""
Tests for the Risk Manager Agent — deterministic hard rules only (no API calls).
"""
import pytest
from atlas.agents.risk_manager import _hard_check, _capital_preservation_strategy
from atlas.data.models import OpportunityModel, StrategyModel, RiskFlag


def _opp(protocol, tvl=450_000_000, pool_type="lending", vol=0.008):
    return OpportunityModel(
        protocol=protocol, pool_id=f"{protocol}-id",
        apy=6.0, tvl_usd=tvl, volatility_7d=vol, pool_type=pool_type,
    )


def _strat(allocations, risk_score=4):
    return StrategyModel(
        name="Test", allocations=allocations,
        expected_yield=6.0, risk_score=risk_score,
    )


class TestConcentrationRule:
    def test_passes_under_limit(self):
        s = _strat({"Aave V3": 40.0, "Curve": 35.0, "Compound": 25.0})
        passed, flags = _hard_check(s, [_opp("Aave V3"), _opp("Curve"), _opp("Compound")])
        assert passed
        assert RiskFlag.CONCENTRATION not in flags

    def test_fails_exactly_at_limit_plus_one(self):
        s = _strat({"Aave V3": 40.01, "Curve": 59.99})
        passed, flags = _hard_check(s, [_opp("Aave V3"), _opp("Curve")])
        assert not passed
        assert RiskFlag.CONCENTRATION in flags

    def test_fails_single_protocol_majority(self):
        s = _strat({"Aave V3": 100.0})
        passed, flags = _hard_check(s, [_opp("Aave V3")])
        assert not passed
        assert RiskFlag.CONCENTRATION in flags

    def test_fails_at_60_pct(self):
        # 60% > 40% limit → should fail
        s = _strat({"Aave V3": 40.0, "Curve": 60.0})
        passed, flags = _hard_check(s, [_opp("Aave V3"), _opp("Curve")])
        assert not passed
        assert RiskFlag.CONCENTRATION in flags


class TestRiskScoreRule:
    def test_passes_at_max(self):
        s = _strat({"Aave V3": 40.0, "Curve": 35.0, "Compound": 25.0}, risk_score=8)
        passed, flags = _hard_check(s, [_opp("Aave V3"), _opp("Curve"), _opp("Compound")])
        assert passed
        assert RiskFlag.HIGH_RISK_SCORE not in flags

    def test_fails_above_max(self):
        s = _strat({"Aave V3": 40.0, "Curve": 35.0, "Compound": 25.0}, risk_score=9)
        passed, flags = _hard_check(s, [_opp("Aave V3"), _opp("Curve"), _opp("Compound")])
        assert not passed
        assert RiskFlag.HIGH_RISK_SCORE in flags

    def test_fails_at_ten(self):
        s = _strat({"Aave V3": 40.0, "Curve": 35.0, "Compound": 25.0}, risk_score=10)
        passed, flags = _hard_check(s, [_opp("Aave V3")])
        assert not passed
        assert RiskFlag.HIGH_RISK_SCORE in flags


class TestLowTVLRule:
    def test_fails_below_minimum(self):
        s = _strat({"SmallPool": 40.0, "Aave V3": 60.0})
        opps = [_opp("SmallPool", tvl=5_000_000), _opp("Aave V3")]
        passed, flags = _hard_check(s, opps)
        assert not passed
        assert RiskFlag.LOW_LIQUIDITY in flags

    def test_passes_above_minimum(self):
        s = _strat({"Aave V3": 40.0, "Curve": 35.0, "Compound": 25.0})
        opps = [_opp("Aave V3", tvl=10_000_001), _opp("Curve", tvl=50_000_000), _opp("Compound")]
        passed, flags = _hard_check(s, opps)
        assert passed
        assert RiskFlag.LOW_LIQUIDITY not in flags

    def test_unknown_protocol_treated_as_infinite_tvl(self):
        # Protocol not in opportunities list → treated as safe (inf TVL)
        # Use valid allocations (no concentration violation)
        s = _strat({"UnknownProtocol": 40.0, "Aave V3": 35.0, "Curve": 25.0})
        opps = [_opp("Aave V3"), _opp("Curve")]
        passed, flags = _hard_check(s, opps)
        assert passed  # unknown treated as safe
        assert RiskFlag.LOW_LIQUIDITY not in flags


class TestVolatilityFlag:
    def test_flags_high_volatility_but_does_not_reject(self):
        s = _strat({"Aave V3": 40.0, "Curve": 35.0, "Compound": 25.0})
        opps = [_opp("Aave V3", vol=0.20), _opp("Curve"), _opp("Compound")]
        passed, flags = _hard_check(s, opps)
        assert passed  # not rejected
        assert RiskFlag.HIGH_VOLATILITY in flags

    def test_no_flag_below_threshold(self):
        s = _strat({"Aave V3": 40.0, "Curve": 35.0, "Compound": 25.0})
        opps = [_opp("Aave V3", vol=0.10), _opp("Curve"), _opp("Compound")]
        passed, flags = _hard_check(s, opps)
        assert RiskFlag.HIGH_VOLATILITY not in flags


class TestCapitalPreservation:
    def test_picks_safest_lending_protocol(self):
        opps = [
            _opp("Aave V3",      tvl=450_000_000, pool_type="lending",   vol=0.008),
            _opp("Yearn Finance", tvl=95_000_000,  pool_type="yield_vault", vol=0.031),
            _opp("Curve Finance", tvl=380_000_000, pool_type="stable_swap", vol=0.012),
        ]
        strat = _capital_preservation_strategy(opps)
        assert strat.allocations == {"Aave V3": 100.0}
        assert strat.risk_score == 1

    def test_fallback_when_no_lending(self):
        opps = [_opp("Yearn Finance", tvl=95_000_000, pool_type="yield_vault", vol=0.031)]
        strat = _capital_preservation_strategy(opps)
        assert "Yearn Finance" in strat.allocations

    def test_fallback_hardcoded_when_no_opps(self):
        strat = _capital_preservation_strategy([])
        assert "Aave V3" in strat.allocations
