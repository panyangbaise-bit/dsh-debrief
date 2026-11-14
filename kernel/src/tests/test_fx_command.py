"""FX rates command: cross rates, env overrides, provider-failure envelope."""

import pytest

import adapters.fx as fx_module


@pytest.fixture(autouse=True)
def _reset_fx_cache():
    """Each test starts with a cold provider cache."""
    fx_module.reset_cache()
    yield
    fx_module.reset_cache()


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


# Provider (latest/CNY) says: 7.0 CNY per USD, 0.92 CNY per HKD, 7.8 CNY per EUR.
PROVIDER = {
    "result": "success",
    "rates": {
        "CNY": 1.0,
        "USD": 1.0 / 7.0,
        "HKD": 1.0 / 0.92,
        "EUR": 1.0 / 7.8,
    },
}


@pytest.fixture
def fake_fx_transport(monkeypatch):
    def get(url, timeout):
        assert url == "https://open.er-api.com/v6/latest/CNY"
        return FakeResponse(PROVIDER)

    monkeypatch.setattr(fx_module.requests, "get", get)


def test_get_rates_cny_base(fake_fx_transport):
    rates = fx_module.get_rates("CNY")
    assert rates["base"] == "CNY"
    assert rates["source"] == "open.er-api.com"
    assert "asOf" in rates
    assert rates["rates"]["CNY"] == 1.0
    assert rates["rates"]["USD"] == pytest.approx(1 / 7.0)
    assert rates["rates"]["HKD"] == pytest.approx(1 / 0.92)
    assert rates["rates"]["EUR"] == pytest.approx(1 / 7.8)


def test_get_rates_cross_base_converts(fake_fx_transport):
    rates = fx_module.get_rates("USD")
    assert rates["base"] == "USD"
    assert rates["rates"]["USD"] == 1.0
    # HKD per 1 USD = (1/0.92 HKD per CNY) / (1/7.0 USD per CNY).
    assert rates["rates"]["HKD"] == pytest.approx((1 / 0.92) / (1 / 7.0))
    assert rates["rates"]["CNY"] == pytest.approx(7.0)


def test_get_rates_env_override_applies_to_cny_base(fake_fx_transport, monkeypatch):
    monkeypatch.setenv("DEBRIEF_FX_USD", "7.2")
    rates = fx_module.get_rates("CNY")
    assert rates["rates"]["USD"] == pytest.approx(1 / 7.2)
    # Cross base USD back to CNY honours the same override.
    usd_rates = fx_module.get_rates("USD")
    assert usd_rates["rates"]["CNY"] == pytest.approx(7.2)


def test_get_rates_provider_failure_raises(monkeypatch):
    def get(url, timeout):
        raise OSError("provider down")

    monkeypatch.setattr(fx_module.requests, "get", get)
    with pytest.raises(ValueError):
        fx_module.get_rates("CNY")


def test_cli_fx_success_envelope(run_cli, fake_fx_transport):
    code, payload = run_cli(["fx", "--base", "USD", "--json"])
    assert code == 0
    data = payload["data"]
    assert data["base"] == "USD"
    assert data["rates"]["CNY"] == pytest.approx(7.0)


def test_cli_fx_provider_failure_envelope(run_cli, monkeypatch):
    def get(url, timeout):
        raise OSError("provider down")

    monkeypatch.setattr(fx_module.requests, "get", get)
    code, payload = run_cli(["fx", "--json"])
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "DEBRIEF_FX_UNAVAILABLE"
    assert "DEBRIEF_FX_" in payload["error"]["message"]
    assert "connectivity" in payload["error"]["message"]


def test_provider_answer_is_cached_within_the_process(monkeypatch):
    calls = []

    def get(url, timeout):
        calls.append(url)
        return FakeResponse(PROVIDER)

    monkeypatch.setattr(fx_module.requests, "get", get)
    first = fx_module.get_rates("CNY")
    second = fx_module.get_rates("USD")
    assert len(calls) == 1  # one dashboard build, one HTTP call
    assert first["asOf"] == second["asOf"]
    fx_module.reset_cache()
    fx_module.get_rates("CNY")
    assert len(calls) == 2


def test_cny_rates_reuse_the_same_provider_call(monkeypatch):
    calls = []

    def get(url, timeout):
        calls.append(url)
        return FakeResponse(PROVIDER)

    monkeypatch.setattr(fx_module.requests, "get", get)
    rates = fx_module.get_cny_rates(("US", "HK", "CN"))
    assert rates["CN"] == 1.0
    assert rates["US"] == pytest.approx(7.0)
    assert rates["HK"] == pytest.approx(0.92)
    assert len(calls) == 1
