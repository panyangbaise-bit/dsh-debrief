"""Shared read-side kernel: portfolio snapshot, prices, FX, dashboard aggregate."""

import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from adapters.fx import get_rates
from db.models import Holding, PriceCache, Transaction, WatchlistItem
from debrief.context import display_now, market_to_output
from debrief.errors import KernelError
from domain.markets import currency_for_market
from domain.valuation import calculate_portfolio_totals

# Env overrides make CNY conversion deterministic/offline-friendly:
#   DEBRIEF_FX_USD=7.2 DEBRIEF_FX_HKD=0.92
FX_ENV_PREFIX = "DEBRIEF_FX_"


def _refresh_result(session, targets, force: bool):
    """Run refresh_stale_prices defensively; never raise out of a read.

    debrief.worker imports apscheduler at module level; in a wheel-only
    (collector-free) install that import fails, so it must live inside the
    guarded block — reads degrade to cached prices instead of erroring.
    """
    try:
        from debrief.worker import refresh_stale_prices

        return refresh_stale_prices(session, targets, force=force)
    except Exception as exc:  # pragma: no cover — defensive
        return {
            "refreshed": 0,
            "failed": [f"refresh:{type(exc).__name__}"],
            "available": False,
        }


def _refresh_meta(refresh, session, targets) -> dict:
    """Top-level refresh metadata: pricesRefreshed + capped priceErrors."""
    if refresh is False:
        return {"pricesRefreshed": False}
    result = _refresh_result(session, targets, force=bool(refresh))
    meta = {"pricesRefreshed": bool(result and result.get("available"))}
    errors = (result or {}).get("failed") or []
    if errors:
        meta["priceErrors"] = errors[:10]
    return meta


def cny_rates(markets: list[str], cross_rates: Optional[dict] = None) -> dict[str, float]:
    """CNY conversion rates (CNY per 1 unit) for the given markets.

    `cross_rates` is a `get_rates()` table (units per 1 CNY) the caller has
    already fetched; reusing it keeps one dashboard build at a single FX HTTP
    call instead of one per consumer.
    """
    rates: dict[str, float] = {}
    missing = []
    for market in sorted({m.upper() for m in markets}):
        base = currency_for_market(market)
        if base == "CNY":
            rates[market] = 1.0
            continue
        env_value = os.environ.get(f"{FX_ENV_PREFIX}{base}", "")
        if env_value:
            try:
                rates[market] = float(env_value)
                continue
            except ValueError:
                pass
        cross = (cross_rates or {}).get(base)
        if cross:
            try:
                rates[market] = 1.0 / float(cross)
                continue
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        missing.append(market)
    if missing:
        from adapters.fx import get_cny_rates

        rates.update(get_cny_rates(tuple(missing)))
    unavailable = [m for m in markets if m.upper() not in rates]
    if unavailable:
        raise KernelError(
            "DEBRIEF_FX_UNAVAILABLE",
            "no CNY rate for market(s) "
            + ", ".join(sorted(unavailable))
            + "; set "
            + " ".join(f"DEBRIEF_FX_{currency_for_market(m)}=" for m in unavailable)
            + "or check connectivity",
        )
    return rates


def _two_closes(session: Session, ticker: str, market: str) -> tuple[Optional[float], Optional[float]]:
    rows = session.scalars(
        select(PriceCache)
        .where(PriceCache.ticker == ticker.upper(), PriceCache.market == market.upper())
        .order_by(desc(PriceCache.date), desc(PriceCache.id))
        .limit(2)
    ).all()
    if not rows:
        return None, None
    last = rows[0].close
    prev = rows[1].close if len(rows) > 1 else None
    return last, prev


def _open_holdings(session: Session, status: Optional[str]) -> list[Holding]:
    # The CLI contract renders the current portfolio: open positions only.
    return session.query(Holding).filter(Holding.status == "open").all()


def _prices_as_of(session: Session) -> Optional[str]:
    """Latest quote fetch time across the price cache (UTC ISO-8601), or None.

    Lets the UI state how old the quoted prices are when a read serves cached
    prices instead of refreshing live.
    """
    value = session.scalar(select(func.max(PriceCache.fetched_at)))
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def build_holdings_payload(
    session: Session,
    status: Optional[str] = None,
    *,
    refresh: Optional[bool] = None,
    cross_rates: Optional[dict] = None,
) -> dict:
    holdings = _open_holdings(session, status)
    refresh_meta = _refresh_meta(
        refresh,
        session,
        {(h.market.upper(), h.ticker.upper()) for h in holdings},
    )
    if not holdings:
        return {
            "asOf": display_now(),
            "currency": "CNY",
            "totalMarketValue": 0.0,
            "dayPnl": 0.0,
            "dayPnlPct": 0.0,
            "totalPnl": 0.0,
            "totalPnlPct": 0.0,
            "positions": [],
            **refresh_meta,
        }
    markets = {h.market for h in holdings}
    rates = cny_rates(list(markets), cross_rates=cross_rates)

    positions, native_values, day_pnl = [], [], 0.0
    for holding in holdings:
        market_db = holding.market.upper()
        market = market_to_output(market_db)
        last, prev = _two_closes(session, holding.ticker, market_db)
        price = last if last is not None else float(holding.cost_basis or 0)
        quantity = float(holding.shares or 0)
        market_value = round(quantity * price, 2)
        pnl_pct = round((price - float(holding.cost_basis or 0)) / float(holding.cost_basis or 1) * 100, 2) if holding.cost_basis else 0.0
        native_values.append((holding, market_value, rates[market_db]))
        if last is not None and prev is not None:
            day_pnl += quantity * (last - prev) * rates[market_db]
        positions.append(
            {
                "market": market,
                "symbol": holding.ticker,
                "name": holding.name or holding.ticker,
                "quantity": quantity,
                "cost": round(float(holding.cost_basis or 0), 4),
                "price": round(price, 4),
                "marketValue": market_value,
                "pnlPct": pnl_pct,
                "weight": 0.0,  # filled below
                "currency": currency_for_market(market_db),
            }
        )

    total_market_cny = sum(mv * rate for _, mv, rate in native_values)
    for position, (_, mv, rate) in zip(positions, native_values):
        position["weight"] = round(mv * rate / total_market_cny * 100, 2) if total_market_cny else 0.0

    # Totals from the full ledger (realized + unrealized) in CNY, including
    # realized gains from closed positions.
    prices = {}
    for holding in holdings:
        last, _ = _two_closes(session, holding.ticker, holding.market.upper())
        prices[(holding.market, holding.ticker)] = last
    all_holdings = session.query(Holding).filter(Holding.status != "archived").all()
    totals = calculate_portfolio_totals(
        all_holdings,
        prices,
        rates,
        list(session.query(Transaction).all()),
    )
    total_pnl = round(totals["pnl"], 2) if totals else 0.0
    total_pnl_pct = round(totals["pnl_pct"], 2) if totals else 0.0
    day_value = total_market_cny - day_pnl
    day_pnl_pct = round(day_pnl / day_value * 100, 2) if day_value else 0.0

    return {
        "asOf": display_now(),
        "currency": "CNY",
        "totalMarketValue": round(total_market_cny, 2),
        "dayPnl": round(day_pnl, 2),
        "dayPnlPct": day_pnl_pct,
        "totalPnl": total_pnl,
        "totalPnlPct": total_pnl_pct,
        "positions": positions,
        **refresh_meta,
    }


def build_transactions_payload(
    session: Session, ticker: Optional[str], limit: int, offset: int
) -> dict:
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    query = (
        session.query(Transaction)
        .join(Holding)
        .order_by(desc(Transaction.date), desc(Transaction.id))
    )
    if ticker:
        query = query.filter(Holding.ticker == ticker.upper())
    total = query.count()
    rows = query.limit(limit).offset(offset).all()
    items = []
    for txn in rows:
        holding = session.get(Holding, txn.holding_id)
        market_db = (holding.market if holding else "?").upper()
        items.append(
            {
                "time": _fmt_time(txn.date),
                "side": txn.action,
                "market": market_to_output(market_db),
                "symbol": holding.ticker if holding else "?",
                "name": (holding.name if holding and holding.name else (holding.ticker if holding else "?")),
                "quantity": float(txn.shares),
                "price": round(float(txn.price), 4),
                "amount": round(float(txn.shares) * float(txn.price), 2),
                "status": "filled",
            }
        )
    return {"total": total, "limit": limit, "offset": offset, "items": items}


def build_watchlist_payload(
    session: Session, ticker: Optional[str] = None, *, refresh: Optional[bool] = None
) -> dict:
    query = session.query(WatchlistItem).filter(WatchlistItem.status != "archived")
    if ticker:
        query = query.filter(WatchlistItem.ticker == ticker.upper())
    rows = query.order_by(desc(WatchlistItem.priority), desc(WatchlistItem.created_at)).all()
    refresh_meta = _refresh_meta(
        refresh,
        session,
        {(item.market.upper(), item.ticker.upper()) for item in rows},
    )
    items = []
    for item in rows:
        market_db = item.market.upper()
        last, prev = _two_closes(session, item.ticker, market_db)
        target = item.target_price_low if item.target_price_low is not None else item.target_price_high
        price = round(last, 4) if last is not None else None
        change = None
        if last is not None and prev is not None and prev:
            change = round((last - prev) / prev * 100, 2)
        distance = None
        if price is not None and target:
            distance = round((price - float(target)) / float(target) * 100, 2)
        # alert = the stored toggle AND the price having reached the target zone.
        alert = (
            bool(getattr(item, "alert_enabled", 1))
            and price is not None
            and target is not None
            and price <= float(target)
        )
        items.append(
            {
                "market": market_to_output(market_db),
                "symbol": item.ticker,
                "name": item.name or item.ticker,
                "price": price,
                "changePct": change,
                "targetPrice": float(target) if target is not None else None,
                "distancePct": distance,
                "alert": alert,
                "currency": currency_for_market(market_db),
            }
        )
    return {"count": len(items), "items": items, **refresh_meta}


def _fmt_time(dt) -> str:
    from common.time import format_display_time

    if dt is None:
        return "—"
    return format_display_time(dt, fmt="%Y-%m-%d %H:%M")


def build_dashboard_payload(
    session: Session, range_days: int, *, refresh: Optional[bool] = None
) -> dict:
    # One FX fetch feeds both the holdings conversion and the fx panel; the
    # provider answer is itself cached for FX_CACHE_TTL_SECONDS.
    fx = None
    try:
        fx = get_rates("CNY")
    except Exception:
        fx = None
    cross_rates = (fx or {}).get("rates") or {}

    # Inner builders skip their own refresh — the dashboard refreshes the
    # union of holdings + watchlist exactly once and reports it at top level.
    holdings_payload = build_holdings_payload(
        session, status="open", refresh=False, cross_rates=cross_rates
    )
    watchlist_payload = build_watchlist_payload(session, refresh=False)
    open_holdings = session.query(Holding).filter(Holding.status == "open").all()
    rates = cny_rates(list({h.market for h in open_holdings}) or ["CN"], cross_rates=cross_rates)

    refresh_targets = {(h.market.upper(), h.ticker.upper()) for h in open_holdings}
    refresh_targets |= {
        (item.market.upper(), item.ticker.upper())
        for item in session.query(WatchlistItem)
        .filter(WatchlistItem.status != "archived")
        .all()
    }
    refresh_meta = _refresh_meta(refresh, session, refresh_targets)

    # Equity series from daily price_cache snapshots (carry-forward per ticker).
    start_date = (datetime.now(timezone.utc) - timedelta(days=range_days)).date()
    series_rows = session.execute(
        select(PriceCache.date, PriceCache.ticker, PriceCache.market, PriceCache.close)
        .where(PriceCache.date >= datetime(start_date.year, start_date.month, start_date.day))
        .order_by(PriceCache.date, PriceCache.id)
    ).all()
    by_ticker: dict[tuple, list] = defaultdict(list)
    for date, ticker, market, close in series_rows:
        by_ticker[(market, ticker)].append((date.date(), close))

    all_dates = sorted({d.date() for d, _, _, _ in series_rows})
    today = datetime.now(timezone.utc).date()
    total_now = holdings_payload["totalMarketValue"]

    # Daily aggregate points (date, value in CNY). Days without cache rows for
    # a holding contribute 0 for that holding — the series END is pinned to the
    # live portfolio value below, so newly added positions are always included.
    points: list[tuple] = []
    if not all_dates:
        points = [(today, round(total_now, 2))]
    else:
        for day in all_dates:
            value = 0.0
            for holding in open_holdings:
                by_day = by_ticker.get((holding.market.upper(), holding.ticker.upper()), [])
                if not by_day:
                    continue
                close = next((c for d, c in reversed(by_day) if d <= day), by_day[0][1])
                value += float(holding.shares or 0) * close * rates[holding.market.upper()]
            points.append((day, round(value, 2)))
        # Pin the end of the series to the current portfolio value: replace a
        # same-day point, or append today's point when the latest cache date is
        # older (new positions may have no same-day cache row).
        if points[-1][0] >= today:
            points[-1] = (today, round(total_now, 2))
        else:
            points.append((today, round(total_now, 2)))
        # Sample to at most `range_days` points, always keeping both ends.
        if len(points) > range_days:
            keep = {0, len(points) - 1}
            step = (len(points) - 1) / (range_days - 1)
            for i in range(1, range_days - 1):
                keep.add(round(i * step))
            points = [points[i] for i in sorted(keep)]

    equity = [value for _, value in points]
    dates = [date for date, _ in points]
    base = equity[0] or 1.0
    returns = [round((v / base - 1) * 100, 2) for v in equity]

    # Composition = weight of each open holding in CNY.
    composition = [{"name": p["name"], "value": p["weight"]} for p in holdings_payload["positions"]]

    # Annualized return over the (pinned) series, or total-return fallback.
    if len(equity) >= 2 and equity[0] > 0:
        span_days = max(1, (dates[-1] - dates[0]).days)
        annual_pct = round(((equity[-1] / equity[0]) ** (365 / span_days) - 1) * 100, 2)
    else:
        annual_pct = holdings_payload["totalPnlPct"]

    return {
        "kpis": {
            "totalAssets": holdings_payload["totalMarketValue"],
            "currency": "CNY",
            "dayPnl": holdings_payload["dayPnl"],
            "dayPnlPct": holdings_payload["dayPnlPct"],
            "totalPnl": holdings_payload["totalPnl"],
            "totalPnlPct": holdings_payload["totalPnlPct"],
            "annualPct": annual_pct,
        },
        "series": {"range": range_days, "equity": equity, "returns": returns},
        "composition": composition,
        "holdings": holdings_payload["positions"],
        "watchlist": watchlist_payload["items"],
        "fx": fx,
        "pricesAsOf": _prices_as_of(session),
        **refresh_meta,
    }
