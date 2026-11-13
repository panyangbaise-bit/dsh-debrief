"""Worker tests: schedule, fault tolerance, ledger error codes (no network)."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from debrief.worker import (
    SCHEDULE,
    build_scheduler,
    check_reminders,
    collect_catalog,
    collect_prices,
)


@pytest.fixture
def engine(tmp_path):
    from debrief.context import open_engine

    engine = open_engine(tmp_path / "worker.db")
    yield engine
    engine.dispose()


class FakeAdapter:
    def __init__(self, fail=False):
        self.fail = fail

    def get_price(self, ticker):
        if self.fail:
            raise ConnectionError("upstream down")
        return {"ticker": ticker, "price": 123.45, "currency": "USD", "source": "fake"}


def seed_holding(session, ticker="AAPL", market="US"):
    from db.repository import create_holding

    return create_holding(session, ticker, market, shares=10, cost_basis=100.0)


def test_dry_run_schedule_table(tmp_path, monkeypatch):
    import importlib

    import debrief.worker as worker

    monkeypatch.setattr("scheduler.settings.SETTINGS_PATH", tmp_path / "s.json")
    monkeypatch.setattr("scheduler.settings.config.DEFAULT_PRICES_CRONTAB", "*/30 * * * *")
    module = importlib.reload(worker)
    table = module.schedule_table()
    assert table["timezone"]
    assert {job["id"] for job in table["jobs"]} == {job_id for job_id, *_ in SCHEDULE}
    assert len(table["jobs"]) == 5
    prices = next(job for job in table["jobs"] if job["id"] == "prices")
    # All-market coverage: every 30 minutes around the clock (Asia/Shanghai).
    assert prices["crontab"] == "*/30 * * * *"


def test_prices_crontab_follows_persisted_settings(tmp_path, monkeypatch):
    """The worker resolves the prices cadence from scheduler settings."""
    import importlib

    import debrief.worker as worker

    monkeypatch.setattr(
        "scheduler.settings.SETTINGS_PATH", tmp_path / "scheduler_settings.json"
    )
    monkeypatch.setattr(
        "scheduler.settings.config.DEFAULT_PRICES_CRONTAB", "*/30 * * * *"
    )
    module = importlib.reload(worker)
    assert module._prices_crontab() == "*/30 * * * *"

    from scheduler.settings import set_prices_crontab

    set_prices_crontab("*/15 1-5 * * *")
    module = importlib.reload(worker)
    assert module._prices_crontab() == "*/15 1-5 * * *"
    prices = next(entry for entry in module.SCHEDULE if entry[0] == "prices")
    assert prices[2] == "*/15 1-5 * * *"


def test_build_scheduler_registers_all_jobs(engine):
    scheduler = build_scheduler(engine)
    try:
        scheduler.start()
        jobs = scheduler.get_jobs()
        assert {job.id for job in jobs} == {job_id for job_id, *_ in SCHEDULE}
    finally:
        scheduler.shutdown(wait=False)


def test_collect_prices_upserts_and_tolerates_failure(engine, monkeypatch):
    from debrief import worker

    monkeypatch.setattr(worker, "_adapters_registered", False)
    monkeypatch.setattr(worker, "_registry", None)
    monkeypatch.setattr(
        "debrief.worker._register_adapters",
        lambda: _fake_registry(),
    )

    with Session(engine) as session:
        seed_holding(session, "AAPL", "US")
        seed_holding(session, "NVDA", "US")
        result = collect_prices(session)
    assert result["saved"] == 2
    assert result["failed"] == []

    from db.models import PriceCache

    with Session(engine) as session:
        rows = session.scalars(select(PriceCache)).all()
        assert len(rows) == 2
        assert all(row.close == 123.45 for row in rows)


def _fake_registry():
    from adapters.base import AdapterRegistry

    registry = AdapterRegistry()
    registry.register("US", FakeAdapter())
    registry.register("CN", FakeAdapter(fail=True))
    registry.register("HK", FakeAdapter(fail=True))
    registry.register("CRYPTO", FakeAdapter())
    return registry


def test_collect_prices_failure_never_raises(engine, monkeypatch):
    from debrief import worker

    monkeypatch.setattr(worker, "_adapters_registered", False)
    monkeypatch.setattr(worker, "_registry", None)
    monkeypatch.setattr("debrief.worker._register_adapters", _fake_registry)

    with Session(engine) as session:
        seed_holding(session, "600519", "CN")
        result = collect_prices(session)
    assert result["saved"] == 0
    assert any("600519" in failure for failure in result["failed"])


def test_ledger_records_error_code_on_failure(engine, monkeypatch):
    from debrief.worker import _ledger

    def boom(session):
        raise RuntimeError("upstream timeout")

    with Session(engine) as session:
        seed_holding(session)
    wrapped = _ledger(engine, "prices", "价格采集", "DEBRIEF_UPSTREAM_PRICE", boom)
    wrapped()  # never raises

    from db.models import JobRun

    with Session(engine) as session:
        run = session.scalars(select(JobRun)).one()
        assert run.status == "failed"
        assert run.error_code == "DEBRIEF_UPSTREAM_PRICE"
        assert "upstream timeout" in run.details


def test_ledger_records_success_details(engine):
    from debrief.worker import _ledger

    def fine(session):
        return {"saved": 3, "failed": []}

    wrapped = _ledger(engine, "catalog-sync", "目录同步", "DEBRIEF_UPSTREAM_CATALOG", fine)
    wrapped()

    from db.models import JobRun

    with Session(engine) as session:
        run = session.scalars(select(JobRun)).one()
        assert run.status == "succeeded"
        assert '"saved": 3' in run.details


def test_catalog_sync_falls_back_partially(engine, monkeypatch):
    from debrief import catalog

    monkeypatch.setattr(catalog, "_akshare_rows", lambda *a, **k: [])
    monkeypatch.setattr(
        catalog,
        "sync_coin_list",
        lambda session, limit=2000: catalog._upsert_rows(
            session,
            [
                {"market": "CC", "symbol": "BTC", "name": "Bitcoin", "currency": "USD", "asset_class": "crypto", "pinyin_alias": None},
                {"market": "CC", "symbol": "ETH", "name": "Ethereum", "currency": "USD", "asset_class": "crypto", "pinyin_alias": None},
            ],
        ),
    )
    with Session(engine) as session:
        stats = collect_catalog(session)
    assert stats["crypto"] == 2
    assert isinstance(stats["cn_stock"], int)

    from debrief.catalog import catalog_counts

    with Session(engine) as session:
        assert catalog_counts(session)["CC"] == 2


def test_check_reminders_compares_targets(engine):
    from db.repository import create_watchlist_item, upsert_price

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    with Session(engine) as session:
        create_watchlist_item(session, "00700", "HK", name="腾讯控股", target_price_low=380.0)
        upsert_price(session, "00700", "HK", today, close=370.0, source="seed")
        result = check_reminders(session)
    assert result["alerts"] == 1
    assert any("00700" in detail or "腾讯" in detail for detail in result["details"])
