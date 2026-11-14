"""Instrument catalog: ranked search, eastmoney suggest, CoinGecko, daily sync.

Ranking (design §5.8): exact code > code prefix > exact name > name prefix >
substring (including pinyin alias). Suggest fallback is rate-limited
(60 calls/minute) and cached for 15 minutes per process; CoinGecko is the
crypto source. Upstream failures always fall back to the local catalog.
"""

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import requests
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from db.models import Holding, InstrumentCatalog
from debrief.context import market_to_output
from domain.instruments import inferred_cn_class, qualify_cn_symbol

logger = logging.getLogger(__name__)

EASTMONEY_SUGGEST_URL = "https://searchapi.eastmoney.com/api/suggest/get"
# Official, unthrottled symbol directories used when eastmoney push2 refuses us.
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
HKEX_SECURITIES_URL = (
    "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx"
)
EASTMONEY_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"  # public web-search token
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
HTTP_TIMEOUT = 5

# 60 calls/minute token bucket + 15-minute result cache (process-local).
_ratelimit = deque(maxlen=60)
_ratelimit_lock = threading.Lock()
_suggest_cache: dict[tuple, tuple[float, list]] = {}
_cache_lock = threading.Lock()
SUGGEST_CACHE_SECONDS = 15 * 60


def _market_db_of(quote_id: str) -> Optional[str]:
    prefix = (quote_id or "").split(".")[0]
    return {
        "0": "CN",  # SZ
        "1": "CN",  # SH
        "116": "HK",
        "105": "US",  # NASDAQ
        "106": "US",  # NYSE
        "107": "US",  # AMEX
        "128": "US",  # OTC
    }.get(prefix)


def _asset_class(security_type_name: str, name: str) -> str:
    label = (security_type_name or "").lower()
    if "基金" in label or "fund" in label or "etf" in (name or "").lower() or "ETF" in (name or ""):
        return "etf"
    if "指数" in label or "index" in label:
        return "index"
    if "债" in label:
        return "bond"
    return "stock"


def eastmoney_suggest(query: str, market_db: str, limit: int = 10) -> list[dict]:
    """Live suggest fallback for stocks/ETFs (CN/HK/US) with rate limiting."""
    now = time.time()
    with _cache_lock:
        cached = _suggest_cache.get((market_db, query))
        if cached and now - cached[0] < SUGGEST_CACHE_SECONDS:
            return cached[1]
    with _ratelimit_lock:
        while _ratelimit and now - _ratelimit[0] > 60:
            _ratelimit.popleft()
        if len(_ratelimit) >= 60:
            logger.warning("eastmoney suggest rate limit reached; local catalog only")
            return []
        _ratelimit.append(now)
    try:
        resp = requests.get(
            EASTMONEY_SUGGEST_URL,
            params={
                "input": query,
                "type": "14",
                "token": EASTMONEY_TOKEN,
                "count": max(limit, 10),
            },
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        rows = (resp.json().get("QuotationCodeTable") or {}).get("Data") or []
    except Exception as exc:
        logger.warning("eastmoney suggest failed: %s", exc)
        return []
    items = []
    for row in rows:
        market = _market_db_of(row.get("QuoteID"))
        if market != market_db:
            continue
        symbol = str(row.get("Code") or "").split(".")[0]
        if not symbol:
            continue
        name = row.get("Name") or symbol
        items.append(
            {
                "market": market_to_output(market),
                "symbol": symbol,
                "name": name,
                "currency": {"CN": "CNY", "HK": "HKD", "US": "USD"}.get(market, ""),
                "assetClass": _asset_class(row.get("SecurityTypeName"), name),
                "pinyin": (row.get("PinYin") or "").lower(),
            }
        )
        if len(items) >= limit:
            break
    with _cache_lock:
        _suggest_cache[(market_db, query)] = (now, items)
    return items


def coingecko_search(query: str, limit: int = 10) -> list[dict]:
    """Live crypto search fallback (public /search endpoint, no key)."""
    try:
        resp = requests.get(
            f"{COINGECKO_BASE}/search", params={"query": query}, timeout=HTTP_TIMEOUT
        )
        resp.raise_for_status()
        coins = (resp.json().get("coins") or [])[:limit]
    except Exception as exc:
        logger.warning("coingecko search failed: %s", exc)
        return []
    items = []
    for coin in coins:
        symbol = str(coin.get("symbol") or "").upper()
        if not symbol:
            continue
        items.append(
            {
                "market": "CC",
                "symbol": symbol,
                "name": coin.get("name") or symbol,
                "currency": "USD",
                "assetClass": "crypto",
                "pinyin": "",
            }
        )
    return items


def _class_tiebreak(row: InstrumentCatalog) -> int:
    """Prefer the asset class a bare CN code actually implies (510300 is an ETF
    even though the fund list also carries it)."""
    if row.market != "CN":
        return 0
    return 0 if inferred_cn_class(row.symbol) == row.asset_class else 1


def _dedupe_same_instrument(rows: list) -> list:
    """Drop the same instrument seen from two sources (ETF list + fund list)."""
    kept: dict = {}
    for row in rows:
        key = (row.market, row.symbol, row.name)
        current = kept.get(key)
        if current is None or _class_tiebreak(row) < _class_tiebreak(current):
            kept[key] = row
    return list(kept.values())


def _like_pattern(value: str) -> str:
    """Lower-cased substring LIKE pattern with metacharacters escaped."""
    escaped = (
        (value or "").lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped}%"


def _rank(query: str, row: InstrumentCatalog) -> tuple[int, str]:
    q = query.lower()
    symbol = (row.symbol or "").lower()
    name = (row.name or "").lower()
    pinyin = (row.pinyin_alias or "").lower()
    if symbol == q:
        return (0, symbol)
    if symbol.startswith(q):
        return (1, symbol)
    if name == q:
        return (2, symbol)
    if name.startswith(q):
        return (3, symbol)
    if q in name or (pinyin and q in pinyin):
        return (4, symbol)
    return (9, symbol)


def search(
    session: Session, market_db: str, query: str, limit: int = 20
) -> tuple[list[dict], str]:
    """Ranked catalog search with live suggest fallback; never fails hard."""
    # SQL prefilter keeps the per-keystroke cost flat now that the CN catalog
    # holds ~28k open-end funds on top of stocks/ETFs; ranking stays in Python
    # so the exact > prefix > name > substring ordering is unchanged.
    pattern = _like_pattern(query)
    rows = session.scalars(
        select(InstrumentCatalog).where(
            InstrumentCatalog.market == market_db,
            or_(
                func.lower(InstrumentCatalog.symbol).like(pattern, escape="\\"),
                func.lower(InstrumentCatalog.name).like(pattern, escape="\\"),
                func.lower(func.coalesce(InstrumentCatalog.pinyin_alias, "")).like(pattern, escape="\\"),
            ),
        )
    ).all()
    ranked = sorted(
        ((_rank(query, r), r) for r in rows if _rank(query, r)[0] < 9),
        key=lambda pair: (pair[0], _class_tiebreak(pair[1])),
    )
    matched = _dedupe_same_instrument([row for _, row in ranked])
    # An exact symbol hit is authoritative (a fund code must never wait on the
    # live suggest round-trip, which is throttled and costs ~1.5 s).
    exact_symbol_hit = bool(ranked) and ranked[0][0][0] == 0
    items = []
    # One (market, symbol) may legitimately map to several asset classes; only
    # the live-suggest extras are deduped against it by bare code.
    seen = {(row.market, row.symbol) for row in matched}
    for row in matched:
        symbol = qualify_cn_symbol(row.symbol, row.asset_class) if row.market == "CN" else row.symbol
        items.append(
            {
                "market": market_to_output(row.market),
                "symbol": symbol,
                "name": row.name,
                "currency": row.currency,
                "assetClass": row.asset_class,
            }
        )
        if len(items) >= limit:
            break

    source = (
        "CoinGecko /coins/list (daily sync) + local search"
        if market_db == "CRYPTO"
        else "akshare catalog (daily sync) + eastmoney suggest fallback"
    )
    # Live fallback is best-effort: ANY upstream failure degrades to the local
    # catalog (design §2.2 "上游不可用回退本地目录") — never an envelope error.
    try:
        if market_db == "CRYPTO":
            extras = coingecko_search(query, limit) if not items else []
        else:
            extras = (
                eastmoney_suggest(query, market_db, limit=10)
                if len(items) < 5 and not exact_symbol_hit
                else []
            )
    except Exception as exc:  # defensive: unforeseen upstream errors must not surface
        logger.warning("instrument suggest fallback failed: %s", exc)
        extras = []
    for extra in extras:
        key = (extra["market"], extra["symbol"])
        if key not in seen:
            seen.add(key)
            items.append(extra)
        if len(items) >= limit:
            break
    return items[:limit], source


def lookup_exact(session: Session, market_code: str, symbol: str) -> Optional[dict]:
    """Exact catalog row for a market+symbol (no live fallback).

    ``market_code`` uses the JSON-side code (US/CN/HK/CC). Returns
    {name, currency} or None.
    """
    row = session.scalars(
        select(InstrumentCatalog).where(
            InstrumentCatalog.market == market_code,
            InstrumentCatalog.symbol == symbol.upper(),
        )
    ).first()
    if row is None:
        return None
    return {"name": row.name, "currency": row.currency}


def held_symbols(session: Session, market_db: str) -> set[str]:
    return {
        h.ticker.upper()
        for h in session.scalars(
            select(Holding).where(
                Holding.status == "open", Holding.market == market_db
            )
        )
    }


def _upsert_rows(session: Session, rows: list[dict]) -> int:
    if not rows:
        return 0
    now = datetime.now(timezone.utc)
    session.execute(
        text(
            """
            INSERT INTO instrument_catalog (market, symbol, name, currency, asset_class, pinyin_alias, updated_at)
            VALUES (:market, :symbol, :name, :currency, :asset_class, :pinyin_alias, :updated_at)
            ON CONFLICT(market, symbol, asset_class) DO UPDATE SET
                name = excluded.name,
                currency = excluded.currency,
                pinyin_alias = excluded.pinyin_alias,
                updated_at = excluded.updated_at
            """
        ),
        [
            {
                "market": row["market"],
                "symbol": row["symbol"],
                "name": row["name"],
                "currency": row["currency"],
                "asset_class": row["asset_class"],
                "pinyin_alias": row.get("pinyin_alias") or None,
                "updated_at": now,
            }
            for row in rows
        ],
    )
    session.commit()
    return len(rows)


def sync_coin_list(session: Session, limit: int = 2000) -> int:
    try:
        resp = requests.get(
            f"{COINGECKO_BASE}/coins/list",
            params={"include_platform": "false"},
            timeout=20,
            headers={"User-Agent": "debrief-kernel/1.0"},
        )
        resp.raise_for_status()
        coins = (resp.json() or [])[:limit]
    except Exception as exc:
        raise RuntimeError(f"CoinGecko /coins/list failed: {exc}") from exc
    rows = [
        {
            "market": "CC",
            "symbol": str(coin.get("symbol") or "").upper(),
            "name": coin.get("name") or coin.get("symbol") or "",
            "currency": "USD",
            "asset_class": "crypto",
            "pinyin_alias": None,
        }
        for coin in coins
        if coin.get("symbol")
    ]
    return _upsert_rows(session, rows)


def _akshare_rows(
    loader,
    market: str,
    currency: str,
    kind: str,
    limit: int,
    code_col: Optional[str] = None,
    name_col: Optional[str] = None,
    strip_prefix: bool = False,
):
    """Normalize one akshare frame into catalog rows.

    `code_col`/`name_col` cover sources whose headers differ (exchange-published
    lists use 证券代码/证券简称, 深交所 uses A股代码/A股简称, sina prefixes ETF
    codes with sh/sz). Anything unparsable is skipped rather than stored.
    """
    import akshare as ak

    df = loader(ak)
    if df is None or getattr(df, "empty", True):
        return []
    rows = []
    for _, rec in df.head(limit).iterrows():
        values = rec.to_dict()
        if code_col is not None:
            code = str(values.get(code_col) or "").strip()
        else:
            code = str(values.get("代码") or values.get("code") or values.get("基金代码") or "").strip()
        if name_col is not None:
            name = str(values.get(name_col) or "").strip()
        else:
            name = str(values.get("名称") or values.get("name") or values.get("基金简称") or "").strip()
        if strip_prefix and len(code) > 6 and code[:2].lower() in {"sh", "sz", "bj"}:
            code = code[2:]
        if not code or not name or code.lower() == "nan" or name.lower() == "nan":
            continue
        alias = ""
        for key in ("拼音缩写", "拼音简称", "拼音"):
            if values.get(key):
                alias = str(values[key]).strip()[:60]
                break
        rows.append(
            {
                "market": market,
                "symbol": code,
                "name": name[:200],
                "currency": currency,
                "asset_class": kind,
                "pinyin_alias": alias or None,
            }
        )
    return rows


def _parse_nasdaq_trader(text: str, limit: int) -> list[dict]:
    """Parse one Nasdaq Trader symbol-directory file into catalog rows.

    Pipe-delimited, one header line, one "File Creation Time: ..." trailer.
    Class shares use dots upstream ("BRK.A") but quote providers expect the
    dash form, so the symbol is normalized on the way in.
    """
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    header = lines[0].split("|")
    try:
        symbol_col = header.index("Symbol") if "Symbol" in header else header.index("ACT Symbol")
        name_col = header.index("Security Name")
        test_col = header.index("Test Issue")
    except ValueError:
        return []
    etf_col = header.index("ETF") if "ETF" in header else -1
    rows = []
    for line in lines[1:]:
        parts = line.split("|")
        if len(parts) != len(header):  # skips the File Creation Time trailer
            continue
        if parts[test_col].strip().upper() == "Y":
            continue
        symbol = parts[symbol_col].strip().upper().replace(".", "-")
        name = parts[name_col].strip()
        if not symbol or not name:
            continue
        rows.append(
            {
                "market": "US",
                "symbol": symbol,
                "name": name[:200],
                "currency": "USD",
                "asset_class": "etf" if etf_col >= 0 and parts[etf_col].strip().upper() == "Y" else "stock",
                "pinyin_alias": None,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _parse_hkex_frame(frame, limit: int) -> list[dict]:
    """Catalog rows from the HKEX "List of Securities" sheet.

    Only Category == Equity is kept (the file also carries warrants, debt and
    trading-only lines); ETFs are Equity rows whose sub-category says so.
    """
    if frame is None or getattr(frame, "empty", True):
        return []
    # Warrants / CBBCs / debt dominate the file and are not investable here.
    wanted = {"Equity", "Exchange Traded Products", "Real Estate Investment Trusts"}
    rows = []
    for _, rec in frame.iterrows():
        values = rec.to_dict()
        category = str(values.get("Category") or "").strip()
        if category not in wanted:
            continue
        raw_code = values.get("Stock Code")
        try:  # the sheet stores codes as numbers, so 00001 arrives as 1
            code = f"{int(raw_code):05d}"
        except (TypeError, ValueError):
            code = str(raw_code or "").strip()
        name = str(values.get("Name of Securities") or "").strip()
        if not code.isdigit() or len(code) != 5 or not name or name.lower() == "nan":
            continue
        sub = str(values.get("Sub-Category") or "")
        is_etf = category == "Exchange Traded Products" or "Exchange Traded" in sub
        rows.append(
            {
                "market": "HK",
                "symbol": code,
                "name": name[:200],
                "currency": "HKD",
                "asset_class": "etf" if is_etf else "stock",
                "pinyin_alias": None,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _us_stock_rows(limit: int) -> list[dict]:
    """US list: eastmoney push2, then the Nasdaq Trader symbol directories."""
    try:
        rows = _akshare_rows(lambda ak: ak.stock_us_spot_em(), "US", "USD", "stock", limit)
        if rows:
            return rows
        logger.warning("catalog: eastmoney US list returned no rows; using Nasdaq Trader")
    except Exception as exc:
        logger.warning("catalog: eastmoney US list failed (%s); using Nasdaq Trader", exc)
    rows: list[dict] = []
    for url in (NASDAQ_LISTED_URL, OTHER_LISTED_URL):
        try:
            response = requests.get(url, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            rows.extend(_parse_nasdaq_trader(response.text, limit - len(rows)))
        except Exception as exc:
            logger.warning("catalog: Nasdaq Trader file failed (%s): %s", url, exc)
        if len(rows) >= limit:
            break
    return rows[:limit]


def _hk_stock_rows(limit: int) -> list[dict]:
    """HK list: eastmoney push2, then the HKEX published securities list."""
    try:
        rows = _akshare_rows(lambda ak: ak.stock_hk_spot_em(), "HK", "HKD", "stock", limit)
        if rows:
            return rows
        logger.warning("catalog: eastmoney HK list returned no rows; using HKEX")
    except Exception as exc:
        logger.warning("catalog: eastmoney HK list failed (%s); using HKEX", exc)
    try:
        import io

        import pandas as pd

        response = requests.get(HKEX_SECURITIES_URL, timeout=30)
        response.raise_for_status()
        frame = pd.read_excel(io.BytesIO(response.content), sheet_name=0, header=2, dtype=str)
    except Exception as exc:
        logger.warning("catalog: HKEX securities list failed: %s", exc)
        return []
    return _parse_hkex_frame(frame, limit)


def _cn_stock_rows(limit: int) -> list[dict]:
    """A-share list: eastmoney, then the exchange-published lists.

    eastern money's full-board endpoint (`stock_info_a_code_name`) is the
    richest source but is routinely reset/throttled from a cloud IP; the SSE
    and SZSE sites serve the same codes from different hosts, so a throttled
    eastmoney leaves the catalog empty unless we fall back.
    """
    try:
        rows = _akshare_rows(lambda ak: ak.stock_info_a_code_name(), "CN", "CNY", "stock", limit)
        if rows:
            return rows
        logger.warning("catalog: eastmoney A-share list returned no rows; using exchange lists")
    except Exception as exc:
        logger.warning("catalog: eastmoney A-share list failed (%s); using exchange lists", exc)
    rows: list[dict] = []
    for label, loader, code_col, name_col in (
        ("SSE 主板", lambda ak: ak.stock_info_sh_name_code(symbol="主板A股"), "证券代码", "证券简称"),
        ("SSE 科创板", lambda ak: ak.stock_info_sh_name_code(symbol="科创板"), "证券代码", "证券简称"),
        ("SZSE A股", lambda ak: ak.stock_info_sz_name_code(symbol="A股列表"), "A股代码", "A股简称"),
    ):
        try:
            rows.extend(_akshare_rows(loader, "CN", "CNY", "stock", limit, code_col, name_col))
        except Exception as exc:
            logger.warning("catalog: %s list failed: %s", label, exc)
    return rows


def _cn_etf_rows(limit: int) -> list[dict]:
    """Exchange-traded fund list: eastmoney push2, then sina's ETF board."""
    try:
        rows = _akshare_rows(lambda ak: ak.fund_etf_spot_em(), "CN", "CNY", "etf", limit)
        if rows:
            return rows
        logger.warning("catalog: eastmoney ETF list returned no rows; using sina")
    except Exception as exc:
        logger.warning("catalog: eastmoney ETF list failed (%s); using sina", exc)
    try:
        return _akshare_rows(
            lambda ak: ak.fund_etf_category_sina(symbol="ETF基金"),
            "CN",
            "CNY",
            "etf",
            limit,
            "代码",
            "名称",
            strip_prefix=True,
        )
    except Exception as exc:
        logger.warning("catalog: sina ETF list failed: %s", exc)
        return []


# Open-end funds (场外基金) are ~28k codes today and akshare returns them
# sorted by code, so any cap below that silently hides every 01xxxx/02xxxx
# fund — including most ETF feeder funds launched after 2024.
FUND_SYNC_LIMIT = 40000


def sync_stock_catalog(session: Session) -> dict:
    """Daily full sync: CN A股 + CN ETF/基金 + HK + US (best-effort per source)."""
    stats = {}
    sources = (
        ("cn_stock", lambda: _cn_stock_rows(6000)),
        ("cn_etf", lambda: _cn_etf_rows(2000)),
        ("cn_fund", lambda: _akshare_rows(lambda ak: ak.fund_name_em(), "CN", "CNY", "fund", FUND_SYNC_LIMIT)),
        ("hk_stock", lambda: _hk_stock_rows(4000)),
        ("us_stock", lambda: _us_stock_rows(20000)),
    )
    for name, loader in sources:
        try:
            stats[name] = _upsert_rows(session, loader())
        except Exception as exc:
            logger.warning("catalog sync %s failed: %s", name, exc)
            stats[name] = f"error: {type(exc).__name__}"
    try:
        stats["crypto"] = sync_coin_list(session)
    except Exception as exc:
        logger.warning("catalog sync crypto failed: %s", exc)
        stats["crypto"] = f"error: {type(exc).__name__}"
    return stats


def catalog_counts(session: Session) -> dict:
    rows = session.execute(
        text("SELECT market, count(*) FROM instrument_catalog GROUP BY market")
    ).all()
    return {market: count for market, count in rows}
