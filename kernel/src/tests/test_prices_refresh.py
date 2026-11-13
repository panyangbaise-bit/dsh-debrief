"""On-read price refresh: stale detection, force, skip, missing adapters."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import PriceCache
from db.repository import create_holding, create_watchlist_item, upsert_price
from debrief.context import open_engine
from debrief.kernel import (
    build_dashboard_payload,
    build_holdings_payload,
    build_watchlist_payload,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBRIEF_FX_USD", "7.2")
    monkeypatch.setenv("DEBRIEF_FX_HKD", "0.92")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    engine = open_engine(tmp_path / "refresh.db")
    yield engine
    engine.dispose()


class FakeAdapter:
    def __init__(self, price):
        self.price = price

    def get_price(self, ticker):
        return {"ticker": ticker, "price": self.price, "currency": "CNY", "source": "fake"}


def _fake_registry():
    from adapters.base import AdapterRegistry

    registry = AdapterRegistry()
    registry.register("CN", FakeAdapter(99.5))
    registry.register("US", FakeAdapter(199.5))
    registry.register("HK", FakeAdapter(399.5))
    registry.register("CRYPTO", FakeAdapter(599.5))
    return registry


@pytest.fixture
def fake_adapters(monkeypatch):
    import debrief.worker as worker

    monkeypatch.setattr(worker, "_adapters_registered", False)
    monkeypatch.setattr(worker, "_registry", None)
    monkeypatch.setattr("debrief.worker._register_adapters", _fake_registry)


def _today():
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _naive_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _stale():
    return _naive_now() - timedelta(hours=1)


def _seed_holding(session, fetched_at):
    create_holding(session, "600519", "CN", shares=100, cost_basis=1400.0, name="贵州茅台")
    upsert_price(
        session, "600519", "CN", _today(), close=1412.0, source="seed", fetched_at=fetched_at
    )


def _row(session):
    return session.scalars(select(PriceCache)).one()


def test_auto_refresh_refreshes_stale_row(db, fake_adapters):
    stale = _stale()
    with Session(db) as session:
        _seed_holding(session, fetched_at=stale)
        payload = build_holdings_payload(session)
    assert payload["pricesRefreshed"] is True
    assert "priceErrors" not in payload
    assert payload["positions"][0]["price"] == 99.5
    assert payload["positions"][0]["currency"] == "CNY"
    with Session(db) as session:
        row = _row(session)
        assert row.close == 99.5
        assert row.fetched_at > stale


def test_recent_row_skipped_but_refresh_reported(db, fake_adapters):
    fresh = _naive_now()
    with Session(db) as session:
        _seed_holding(session, fetched_at=fresh)
        payload = build_holdings_payload(session)
    assert payload["pricesRefreshed"] is True  # refresh ran, 0 refreshed
    assert payload["positions"][0]["price"] == 1412.0
    with Session(db) as session:
        assert _row(session).close == 1412.0
        assert _row(session).fetched_at == fresh  # untouched


def test_holding_without_price_rows_is_refreshed(db, fake_adapters):
    # A freshly added holding has no price_cache row: the first read must
    # fetch its live quote instead of falling back to the cost basis.
    with Session(db) as session:
        create_holding(session, "600519", "CN", shares=100, cost_basis=1400.0, name="贵州茅台")
        payload = build_holdings_payload(session)
    assert payload["pricesRefreshed"] is True
    assert payload["positions"][0]["price"] == 99.5
    with Session(db) as session:
        assert _row(session).close == 99.5


def test_no_refresh_skips_entirely(db, fake_adapters):
    stale = _stale()
    with Session(db) as session:
        _seed_holding(session, fetched_at=stale)
        payload = build_holdings_payload(session, refresh=False)
    assert payload["pricesRefreshed"] is False
    assert "priceErrors" not in payload
    assert payload["positions"][0]["price"] == 1412.0


def test_force_refresh_ignores_freshness(db, fake_adapters):
    with Session(db) as session:
        _seed_holding(session, fetched_at=_naive_now())
        payload = build_holdings_payload(session, refresh=True)
    assert payload["pricesRefreshed"] is True
    assert payload["positions"][0]["price"] == 99.5


def test_watchlist_payload_refresh_and_currency(db, fake_adapters):
    stale = _stale()
    with Session(db) as session:
        create_watchlist_item(session, "00700", "HK", name="腾讯控股", target_price_low=380.0)
        upsert_price(
            session, "00700", "HK", _today(), close=370.0, source="seed", fetched_at=stale
        )
        payload = build_watchlist_payload(session)
    assert payload["pricesRefreshed"] is True
    assert payload["items"][0]["price"] == 399.5
    assert payload["items"][0]["currency"] == "HKD"


def test_dashboard_refresh_covers_holdings_watchlist_union(db, fake_adapters):
    stale = _stale()
    with Session(db) as session:
        _seed_holding(session, fetched_at=stale)
        create_watchlist_item(session, "00700", "HK", name="腾讯控股")
        upsert_price(
            session, "00700", "HK", _today(), close=370.0, source="seed", fetched_at=stale
        )
        payload = build_dashboard_payload(session, 30)
    assert payload["pricesRefreshed"] is True
    assert payload["fx"]["base"] == "CNY"  # offline fixture provides the fx block
    with Session(db) as session:
        rows = session.scalars(select(PriceCache)).all()
        assert any(r.ticker == "00700" and r.close == 399.5 for r in rows)
        assert any(r.ticker == "600519" and r.close == 99.5 for r in rows)


def test_missing_adapters_degrades_to_cached(db, monkeypatch):
    import debrief.worker as worker

    monkeypatch.setattr(worker, "_adapters_registered", False)
    monkeypatch.setattr(worker, "_registry", None)

    def no_collectors():
        raise ModuleNotFoundError("No module named 'yfinance'")

    monkeypatch.setattr("debrief.worker._register_adapters", no_collectors)
    stale = _stale()
    with Session(db) as session:
        _seed_holding(session, fetched_at=stale)
        payload = build_holdings_payload(session)
    assert payload["pricesRefreshed"] is False  # adapters unavailable
    assert "priceErrors" not in payload
    assert payload["positions"][0]["price"] == 1412.0


def test_adapter_failure_reported_as_price_errors(db, monkeypatch):
    import debrief.worker as worker

    class BrokenAdapter:
        def get_price(self, ticker):
            raise ConnectionError("upstream down")

    def broken_registry():
        from adapters.base import AdapterRegistry

        registry = AdapterRegistry()
        for market in ("CN", "US", "HK", "CRYPTO"):
            registry.register(market, BrokenAdapter())
        return registry

    monkeypatch.setattr(worker, "_adapters_registered", False)
    monkeypatch.setattr(worker, "_registry", None)
    monkeypatch.setattr("debrief.worker._register_adapters", broken_registry)
    stale = _stale()
    with Session(db) as session:
        _seed_holding(session, fetched_at=stale)
        payload = build_holdings_payload(session)
    assert payload["pricesRefreshed"] is True
    assert payload["priceErrors"] == ["CN:600519:ConnectionError"]
    assert payload["positions"][0]["price"] == 1412.0  # cached price retained
