"""
Tests for the Flask REST API endpoints — demo mode (no live orchestrator).
"""
import pytest
from atlas.dashboard.backend.app import create_app


@pytest.fixture
def client():
    app, _ = create_app(orchestrator=None)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def assert_ok(response, code=200):
    assert response.status_code == code
    data = response.get_json()
    assert data["success"] is True
    assert "data" in data
    assert "timestamp" in data
    return data["data"]


class TestHealth:
    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.get_json()["status"] == "ok"


class TestStatusEndpoint:
    def test_returns_success(self, client):
        data = assert_ok(client.get("/api/status"))

    def test_has_system_state(self, client):
        data = assert_ok(client.get("/api/status"))
        assert "system_state" in data

    def test_has_wallet(self, client):
        data = assert_ok(client.get("/api/status"))
        assert "wallet" in data
        assert "total_value_usd" in data["wallet"]


class TestPortfolioEndpoint:
    def test_returns_success(self, client):
        data = assert_ok(client.get("/api/portfolio"))

    def test_has_required_fields(self, client):
        data = assert_ok(client.get("/api/portfolio"))
        for field in ("total_value_usd", "allocations", "idle_usdt", "pnl_usd", "pnl_pct"):
            assert field in data, f"Missing field: {field}"

    def test_allocations_is_dict(self, client):
        data = assert_ok(client.get("/api/portfolio"))
        assert isinstance(data["allocations"], dict)


class TestOpportunitiesEndpoint:
    def test_returns_success(self, client):
        data = assert_ok(client.get("/api/opportunities"))

    def test_has_opportunities_list(self, client):
        data = assert_ok(client.get("/api/opportunities"))
        assert "opportunities" in data
        assert isinstance(data["opportunities"], list)
        assert len(data["opportunities"]) > 0

    def test_opportunity_fields(self, client):
        data = assert_ok(client.get("/api/opportunities"))
        opp = data["opportunities"][0]
        for field in ("protocol", "apy", "tvl_usd", "pool_type"):
            assert field in opp

    def test_has_sentiment(self, client):
        data = assert_ok(client.get("/api/opportunities"))
        assert "sentiment" in data


class TestStrategiesEndpoint:
    def test_returns_success(self, client):
        data = assert_ok(client.get("/api/strategies"))

    def test_has_three_strategies(self, client):
        data = assert_ok(client.get("/api/strategies"))
        assert len(data["strategies"]) == 3

    def test_strategy_fields(self, client):
        data = assert_ok(client.get("/api/strategies"))
        s = data["strategies"][0]
        for field in ("name", "allocations", "expected_yield", "risk_score"):
            assert field in s

    def test_exactly_one_selected(self, client):
        data = assert_ok(client.get("/api/strategies"))
        selected = [s for s in data["strategies"] if s.get("selected")]
        assert len(selected) == 1


class TestTransactionsEndpoint:
    def test_returns_success(self, client):
        data = assert_ok(client.get("/api/transactions"))

    def test_pagination_fields(self, client):
        data = assert_ok(client.get("/api/transactions"))
        for field in ("transactions", "total", "page", "per_page", "pages"):
            assert field in data

    def test_default_page_is_one(self, client):
        data = assert_ok(client.get("/api/transactions"))
        assert data["page"] == 1

    def test_custom_per_page(self, client):
        data = assert_ok(client.get("/api/transactions?per_page=2"))
        assert data["per_page"] == 2


class TestMetricsEndpoint:
    def test_returns_success(self, client):
        data = assert_ok(client.get("/api/metrics"))

    def test_has_required_metrics(self, client):
        data = assert_ok(client.get("/api/metrics"))
        for field in ("current_apy", "pnl_24h_usd", "pnl_7d_usd", "total_return_usd", "total_value_usd"):
            assert field in data

    def test_apy_is_numeric(self, client):
        data = assert_ok(client.get("/api/metrics"))
        assert isinstance(data["current_apy"], (int, float))
