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
                # 000001 is genuinely two instruments; both must stay addressable.
                InstrumentCatalog(
                    market="CN", symbol="000001", name="平安银行", currency="CNY", asset_class="stock"
                ),
                InstrumentCatalog(
                    market="CN", symbol="000001", name="华夏成长混合", currency="CNY", asset_class="fund"
                ),
                # 510300 appears in both the ETF list and the fund list; the fund
                # source also uses the ETF's own name.
                InstrumentCatalog(
                    market="CN",
                    symbol="510300",
                    name="沪深300ETF华泰柏瑞",
                    currency="CNY",
                    asset_class="etf",
                ),
                InstrumentCatalog(
                    market="CN",
                    symbol="510300",
                    name="沪深300ETF华泰柏瑞",
                    currency="CNY",
                    asset_class="fund",
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


def test_cn_stock_falls_back_to_exchange_lists(monkeypatch):
    """A throttled eastmoney endpoint must not leave the A-share list empty."""
    import debrief.catalog as catalog

    calls = []
    row = {
        "market": "CN",
        "symbol": "600000",
        "name": "浦发银行",
        "currency": "CNY",
        "asset_class": "stock",
        "pinyin_alias": None,
    }

    def fake_rows(loader, market, currency, kind, limit, code_col=None, name_col=None, strip_prefix=False):
        calls.append(code_col)
        if code_col is None:
            raise ConnectionResetError("eastmoney reset")
        return [dict(row)]

    monkeypatch.setattr(catalog, "_akshare_rows", fake_rows)
    rows = catalog._cn_stock_rows(100)
    assert calls == [None, "证券代码", "证券代码", "A股代码"]
    assert len(rows) == 3  # SSE 主板 + SSE 科创板 + SZSE


def test_cn_etf_falls_back_to_sina_with_prefixed_codes(monkeypatch):
    import debrief.catalog as catalog

    calls = []

    def fake_rows(loader, market, currency, kind, limit, code_col=None, name_col=None, strip_prefix=False):
        calls.append((code_col, strip_prefix))
        if code_col is None:
            raise RuntimeError("502 from push2")
        return [
            {
                "market": "CN",
                "symbol": "510300",
                "name": "沪深300ETF",
                "currency": "CNY",
                "asset_class": "etf",
                "pinyin_alias": None,
            }
        ]

    monkeypatch.setattr(catalog, "_akshare_rows", fake_rows)
    rows = catalog._cn_etf_rows(100)
    assert calls == [(None, False), ("代码", True)]
    assert rows[0]["symbol"] == "510300"


def test_akshare_rows_strips_exchange_prefixes_and_skips_nan():
    pandas = pytest.importorskip("pandas")
    from debrief.catalog import _akshare_rows

    frame = pandas.DataFrame(
        {
            "代码": ["sh510300", "sz159998", None, "510500"],
            "名称": ["沪深300ETF", "计算机ETF", None, "中证500ETF"],
        }
    )
    rows = _akshare_rows(lambda ak: frame, "CN", "CNY", "etf", 100, "代码", "名称", strip_prefix=True)
    assert [row["symbol"] for row in rows] == ["510300", "159998", "510500"]


def test_ambiguous_code_is_listed_once_per_asset_class(db):
    """000001 must come back as both 平安银行 and 华夏成长混合, addressable apart."""
    with Session(db) as session:
        items, _ = search(session, "CN", "000001")
    by_symbol = {item["symbol"]: item for item in items}
    assert by_symbol["stock:000001"]["name"] == "平安银行"
    assert by_symbol["stock:000001"]["assetClass"] == "stock"
    assert by_symbol["fund:000001"]["name"] == "华夏成长混合"
    assert by_symbol["fund:000001"]["assetClass"] == "fund"


def test_duplicate_listing_of_one_instrument_is_collapsed(db):
    """510300 is in both the ETF and the fund list under the same name."""
    with Session(db) as session:
        items, _ = search(session, "CN", "510300")
    assert len(items) == 1
    assert items[0]["symbol"] == "510300"  # the class the code implies, so no prefix
    assert items[0]["assetClass"] == "etf"


def test_upsert_keeps_one_row_per_asset_class(db):
    from debrief.catalog import _upsert_rows

    base = {"market": "CN", "symbol": "000002", "name": "万  科Ａ", "currency": "CNY", "pinyin_alias": None}
    with Session(db) as session:
        _upsert_rows(session, [{**base, "asset_class": "stock"}])
        _upsert_rows(session, [{**base, "asset_class": "fund", "name": "万科债券"}])
        _upsert_rows(session, [{**base, "asset_class": "stock", "name": "万科A"}])
        rows = session.query(InstrumentCatalog).filter_by(symbol="000002").all()
    assert {(row.asset_class, row.name) for row in rows} == {("stock", "万科A"), ("fund", "万科债券")}


def test_nasdaq_trader_directory_is_parsed():
    from debrief.catalog import _parse_nasdaq_trader

    text = (
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
        "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n"
        "SPY|SPDR S&P 500 ETF Trust|P|N|N|100|Y|N\n"
        "ZZZZ|Test Issue Corp|Q|Y|N|100|N|N\n"
        "BRK.A|Berkshire Hathaway Inc. Class A|Q|N|N|1|N|N\n"
        "File Creation Time: 1114202618:01|" + "|" * 7 + "\n"
    )
    rows = _parse_nasdaq_trader(text, 100)
    assert [row["symbol"] for row in rows] == ["AAPL", "SPY", "BRK-A"]
    assert rows[1]["asset_class"] == "etf"
    assert rows[0]["market"] == "US" and rows[0]["currency"] == "USD"


def test_hkex_securities_sheet_is_parsed():
    pandas = pytest.importorskip("pandas")
    from debrief.catalog import _parse_hkex_frame

    frame = pandas.DataFrame(
        [
            {"Stock Code": 1, "Name of Securities": "CKH HOLDINGS", "Category": "Equity",
             "Sub-Category": "Equity Securities (Main Board)"},
            {"Stock Code": 700, "Name of Securities": "TENCENT", "Category": "Equity",
             "Sub-Category": "Equity Securities (Main Board)"},
            {"Stock Code": 2800, "Name of Securities": "TRACKER FUND", "Category": "Exchange Traded Products",
             "Sub-Category": "Exchange Traded Funds"},
            {"Stock Code": 12345, "Name of Securities": "SOME WARRANT", "Category": "Derivative Warrants",
             "Sub-Category": "Warrants"},
        ]
    )
    rows = _parse_hkex_frame(frame, 100)
    assert [(row["symbol"], row["asset_class"]) for row in rows] == [
        ("00001", "stock"),
        ("00700", "stock"),
        ("02800", "etf"),
    ]
    assert rows[0]["currency"] == "HKD"


def test_us_and_hk_fall_back_to_public_directories(monkeypatch):
    import debrief.catalog as catalog

    class FakeResponse:
        def __init__(self, text="", content=b""):
            self.text = text
            self.content = content

        def raise_for_status(self):
            return None

    nasdaq = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nNVDA|NVIDIA Corporation|Q|N|N|100|N|N\n"
    other = "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\nIBM|International Business Machines|N|IBM|N|100|N|IBM\n"

    def fake_rows(*args, **kwargs):
        raise RuntimeError("eastmoney throttled")

    def fake_get(url, timeout=None):
        if url == catalog.NASDAQ_LISTED_URL:
            return FakeResponse(text=nasdaq)
        if url == catalog.OTHER_LISTED_URL:
            return FakeResponse(text=other)
        raise AssertionError(url)

    monkeypatch.setattr(catalog, "_akshare_rows", fake_rows)
    monkeypatch.setattr(catalog.requests, "get", fake_get)
    rows = catalog._us_stock_rows(100)
    assert [row["symbol"] for row in rows] == ["NVDA", "IBM"]
    assert {row["market"] for row in rows} == {"US"}
