"""Dashboard equity series: last point pinned to current total assets."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from db.repository import create_holding, upsert_price
from debrief.context import open_engine
from debrief.kernel import build_dashboard_payload


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBRIEF_FX_USD", "7.2")
    monkeypatch.setenv("DEBRIEF_FX_HKD", "0.92")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    engine = open_engine(tmp_path / "dashboard.db")
    yield engine
    engine.dispose()


def _today():
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _seed_cn_holding(session, with_dates=("yesterday", "today"), closes=(1000.0, 1050.0)):
    holding = create_holding(session, "600519", "CN", shares=100, cost_basis=1000.0, name="贵州茅台")
    if "yesterday" in with_dates:
        upsert_price(session, "600519", "CN", _today() - timedelta(days=1), close=closes[0], source="seed")
    if "today" in with_dates:
        upsert_price(session, "600519", "CN", _today(), close=closes[1], source="seed")
    return holding


def _add_us_holding_without_cache(session):
    from debrief import commands

    return commands.cmd_holdings_add(
        session,
        {"market": "us", "symbol": "NVDA", "name": "英伟达", "quantity": 10, "cost": 100.0},
    )


def test_new_holding_pins_last_point_to_total_assets(db):
    """A position added without same-day cache rows must appear at the end."""
    with Session(db) as session:
        _seed_cn_holding(session)
        _add_us_holding_without_cache(session)
    with Session(db) as session:
        dashboard = build_dashboard_payload(session, 30)
    total = dashboard["kpis"]["totalAssets"]
    equity = dashboard["series"]["equity"]
    assert equity[-1] == total
    # Without the fix the last point would only contain the CN position.
    assert total > 100 * 1050.0


def test_no_price_rows_single_point(db):
    with Session(db) as session:
        create_holding(session, "600519", "CN", shares=100, cost_basis=1000.0, name="贵州茅台")
    with Session(db) as session:
        dashboard = build_dashboard_payload(session, 30)
    equity, returns = dashboard["series"]["equity"], dashboard["series"]["returns"]
    assert equity == [dashboard["kpis"]["totalAssets"]]
    assert returns == [0.0]


def test_same_day_last_date_is_replaced_not_appended(db):
    """Last cache date == today → replace the point, keep the length."""
    with Session(db) as session:
        _seed_cn_holding(session, with_dates=("today",), closes=(1050.0, 1050.0))
        _add_us_holding_without_cache(session)
    with Session(db) as session:
        dashboard = build_dashboard_payload(session, 30)
    equity = dashboard["series"]["equity"]
    assert len(equity) == 1  # single date + pinned (no extra append)
    assert equity[-1] == dashboard["kpis"]["totalAssets"]
    assert equity[-1] == round(100 * 1050.0 + 10 * 100.0 * 7.2, 2)


def test_stale_last_date_appends_today_point(db):
    with Session(db) as session:
        _seed_cn_holding(session, with_dates=("yesterday",), closes=(1000.0,))
        _add_us_holding_without_cache(session)
    with Session(db) as session:
        dashboard = build_dashboard_payload(session, 30)
    equity = dashboard["series"]["equity"]
    assert len(equity) == 2  # yesterday + appended today
    assert equity[-1] == dashboard["kpis"]["totalAssets"]


def test_returns_recomputed_from_pinned_equity(db):
    with Session(db) as session:
        _seed_cn_holding(session, with_dates=("yesterday",), closes=(1000.0,))
        _add_us_holding_without_cache(session)
    with Session(db) as session:
        dashboard = build_dashboard_payload(session, 30)
    equity, returns = dashboard["series"]["equity"], dashboard["series"]["returns"]
    assert len(returns) == len(equity)
    assert returns[0] == 0.0
    base = equity[0]
    assert returns == [round((v / base - 1) * 100, 2) for v in equity]


def test_sampling_caps_points_and_keeps_both_ends(db):
    with Session(db) as session:
        create_holding(session, "600519", "CN", shares=100, cost_basis=1000.0, name="贵州茅台")
        # 45 distinct cache dates inside the 30-day window.
        for i in range(45):
            upsert_price(
                session,
                "600519",
                "CN",
                _today() - timedelta(days=44 - i),
                close=1000.0 + i,
                source="seed",
            )
    with Session(db) as session:
        dashboard = build_dashboard_payload(session, 30)
    equity = dashboard["series"]["equity"]
    assert len(equity) <= 30
    # Both ends preserved. The window starts 30 days back: close = 1000 + 14.
    assert equity[0] == round(100 * (1000.0 + 14), 2)
    assert equity[-1] == dashboard["kpis"]["totalAssets"]
    assert len(dashboard["series"]["returns"]) == len(equity)


def test_annual_pct_uses_pinned_series(db):
    with Session(db) as session:
        _seed_cn_holding(session, with_dates=("yesterday",), closes=(1000.0,))
    with Session(db) as session:
        dashboard = build_dashboard_payload(session, 30)
    equity = dashboard["series"]["equity"]
    expected = round(((equity[-1] / equity[0]) ** (365 / 1) - 1) * 100, 2)
    assert dashboard["kpis"]["annualPct"] == expected
