"""Instrument catalog search: OTC fund coverage, pinyin, LIKE escaping.

Regression guard for the 0.3.0 bug where the CN fund sync was capped at 6 000
codes (akshare returns ~28 000, sorted by code), so every 01xxxx/02xxxx feeder
fund — e.g. 020357 华夏半导体材料设备ETF联接C — was invisible to the picker.
"""

import pytest
from sqlalchemy.orm import Session

from db.models import InstrumentCatalog
from debrief.catalog import FUND_SYNC_LIMIT, _like_pattern, search
from debrief.context import open_engine


@pytest.fixture(autouse=True)
def offline_suggest(monkeypatch):
    """Search must be deterministic: never call live eastmoney in unit tests."""
    import debrief.catalog as catalog

    monkeypatch.setattr(catalog, "eastmoney_suggest", lambda *args, **kwargs: [])


@pytest.fixture
def db(tmp_path):
    """Small catalog with a stock, an ETF and two OTC funds (one with pinyin)."""
    engine = open_engine(tmp_path / "catalog.db")
    with Session(engine) as session:
        session.add_all(
            [
                InstrumentCatalog(
                    market="CN", symbol="600519", name="贵州茅台", currency="CNY", asset_class="stock"
                ),
                InstrumentCatalog(
                    market="CN", symbol="510300", name="沪深300ETF", currency="CNY", asset_class="etf"
                ),
                InstrumentCatalog(
                    market="CN",
                    symbol="020357",
                    name="华夏半导体材料设备ETF联接C",
                    currency="CNY",
                    asset_class="fund",
                    pinyin_alias="HXBDTCLSBETFLJC",
                ),
                InstrumentCatalog(
                    market="CN",
                    symbol="011613",
                    name="华夏科创50ETF联接C",
                    currency="CNY",
                    asset_class="fund",
                    pinyin_alias="HXKC50ETFLJC",
                ),
            ]
        )
        session.commit()
    yield engine
    engine.dispose()


def test_fund_sync_limit_covers_the_whole_open_fund_list():
    # akshare returns ~28k open-end funds; anything lower hides the 02xxxx range.
    assert FUND_SYNC_LIMIT >= 30000


def test_exact_symbol_finds_an_otc_fund(db):
    with Session(db) as session:
        items, _ = search(session, "CN", "020357")
    assert items and items[0]["symbol"] == "020357"
    assert items[0]["assetClass"] == "fund"


def test_name_substring_finds_funds(db):
    with Session(db) as session:
        items, _ = search(session, "CN", "半导体")
    assert [item["symbol"] for item in items] == ["020357"]


def test_pinyin_alias_finds_funds(db):
    with Session(db) as session:
        items, _ = search(session, "CN", "hxbd")
    assert [item["symbol"] for item in items] == ["020357"]


def test_symbol_prefix_ranks_before_name_matches(db):
    with Session(db) as session:
        items, _ = search(session, "CN", "5103")
    assert items[0]["symbol"] == "510300"


def test_wildcards_in_the_query_are_escaped(db):
    with Session(db) as session:
        items, _ = search(session, "CN", "%")
        assert items == []
        items, _ = search(session, "CN", "_")
        assert items == []
    assert _like_pattern("50%_a") == "%50\\%\\_a%"


def test_search_ignores_other_markets(db):
    with Session(db) as session:
        items, _ = search(session, "HK", "020357")
    assert items == []


def test_large_catalog_stays_fast_enough_for_keystrokes(db):
    """28k funds + stocks must not turn each keystroke into a full scan."""
    import time

    with Session(db) as session:
        session.execute(
            InstrumentCatalog.__table__.insert(),
            [
                {
                    "market": "CN",
                    "symbol": f"9{index:05d}",
                    "name": f"测试基金{index}",
                    "currency": "CNY",
                    "asset_class": "fund",
                    "pinyin_alias": None,
                }
                for index in range(20000)
            ],
        )
        session.commit()
        started = time.perf_counter()
        items, _ = search(session, "CN", "测试基金1999")
        elapsed = time.perf_counter() - started
    assert items
    assert elapsed < 1.5, f"catalog search took {elapsed:.2f}s on 20k rows"


def test_exact_symbol_does_not_wait_on_the_live_suggest(db, monkeypatch):
    """Typing a fund code must stay local (~30 ms), never a 1.5 s round-trip."""
    import debrief.catalog as catalog

    calls = []
    monkeypatch.setattr(catalog, "eastmoney_suggest", lambda *args, **kwargs: calls.append(args) or [])
    with Session(db) as session:
        items, _ = search(session, "CN", "020357")
    assert [item["symbol"] for item in items] == ["020357"]
    assert calls == []


def test_name_query_with_few_matches_still_consults_the_suggest(db, monkeypatch):
    import debrief.catalog as catalog

    calls = []
    monkeypatch.setattr(catalog, "eastmoney_suggest", lambda *args, **kwargs: calls.append(args) or [])
    with Session(db) as session:
        search(session, "CN", "科创")
    assert calls  # no exact code match, so the live fallback is still used
