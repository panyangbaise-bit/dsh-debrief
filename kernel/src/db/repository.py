from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import create_engine, desc
from sqlalchemy.orm import Session

from config import config
from db.models import (
    Base,
    FinancialReport,
    Holding,
    JobRun,
    NewsArticle,
    PriceCache,
    TradingDiscipline,
    Transaction,
    UserAction,
)

if TYPE_CHECKING:
    from db.models import WatchlistItem


engine = create_engine(config.DATABASE_URL, echo=False)


def init_db():
    """Create all tables. Call once at startup."""
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)


# ── Holdings ──────────────────────────────────────────────


def create_holding(
    session: Session,
    ticker: str,
    market: str,
    shares: float,
    cost_basis: float,
    position_type: str = "core",
    name: str = None,
) -> Holding:
    holding = Holding(
        ticker=ticker.upper(),
        market=market.upper(),
        shares=shares,
        cost_basis=cost_basis,
        position_type=position_type,
        name=name,
        status="open",
    )
    session.add(holding)
    session.flush()
    if shares and shares > 0 and cost_basis and cost_basis > 0:
        session.add(
            Transaction(
                holding_id=holding.id,
                action="buy",
                shares=shares,
                price=cost_basis,
                notes="opening",
                date=holding.created_at or datetime.now(timezone.utc),
            )
        )
    session.commit()
    return holding


def get_all_holdings(session: Session) -> list[Holding]:
    return session.query(Holding).filter(Holding.status != "archived").all()


def get_open_holdings(session: Session) -> list[Holding]:
    """Active positions only (excludes closed / zero-share rows)."""
    return session.query(Holding).filter(Holding.status == "open").all()


def get_holding_by_ticker(session: Session, ticker: str) -> Optional[Holding]:
    return (
        session.query(Holding)
        .filter(Holding.ticker == ticker.upper(), Holding.status != "archived")
        .first()
    )


def update_holding(session: Session, holding_id: int, **kwargs) -> Optional[Holding]:
    holding = session.query(Holding).filter(Holding.id == holding_id).first()
    if holding:
        for k, v in kwargs.items():
            setattr(holding, k, v)
        holding.updated_at = datetime.now(timezone.utc)
        session.commit()
    return holding


def delete_holding(session: Session, holding_id: int) -> bool:
    holding = session.query(Holding).filter(Holding.id == holding_id).first()
    if holding:
        # Keep the ledger and identity for historical evidence. Archived rows
        # are excluded from current portfolio/return calculations.
        holding.status = "archived"
        session.commit()
        return True
    return False


# ── Transactions ──────────────────────────────────────────


def create_transaction(
    session: Session,
    holding_id: int,
    action: str,
    shares: float,
    price: float,
    notes: str = None,
    date: datetime = None,
) -> Transaction:
    txn = Transaction(
        holding_id=holding_id,
        action=action,
        shares=shares,
        price=price,
        notes=notes,
    )
    if date is not None:
        txn.date = date
    session.add(txn)
    session.commit()
    return txn


def list_transactions(session: Session) -> list[Transaction]:
    """Every trade, oldest first, so ledgers can be replayed in order."""
    return (
        session.query(Transaction)
        .join(Holding)
        .filter(Holding.status != "archived")
        .order_by(Transaction.date, Transaction.id)
        .all()
    )


def get_transactions_for_holding(session: Session, holding_id: int) -> list[Transaction]:
    return (
        session.query(Transaction)
        .filter(Transaction.holding_id == holding_id)
        .order_by(desc(Transaction.date))
        .all()
    )


def get_recent_transactions(session: Session, days: int = 30) -> list[Transaction]:
    """Transactions from the last N days, newest first (holding eagerly usable)."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return (
        session.query(Transaction)
        .filter(Transaction.date >= cutoff)
        .order_by(desc(Transaction.date))
        .all()
    )


def apply_trade(
    session: Session,
    holding_id: int,
    action: str,
    shares: float,
    price: float,
    notes: str = None,
    trade_date: datetime = None,
) -> Transaction:
    """Apply a buy/sell using broker-style average cost.

    Buy: new_cost = (old_shares * old_cost + shares * price) / new_shares;
    reopen closed positions.
    Sell: remaining_cost = (old_shares * old_cost - shares * price) / remaining;
    (matches common CN/HK broker 成本价; selling at a loss raises remaining cost).
    Full exit → shares=0, status=closed.
    """
    action = (action or "").lower().strip()
    if action not in ("buy", "sell"):
        raise ValueError(f"Invalid action: {action}")
    if shares is None or shares <= 0:
        raise ValueError("Shares must be positive")
    if price is None or price <= 0:
        raise ValueError("Price must be positive")

    holding = session.query(Holding).filter(Holding.id == holding_id).first()
    if not holding or holding.status == "archived":
        raise ValueError(f"Holding not found: {holding_id}")

    if action == "buy":
        old_shares = float(holding.shares or 0)
        if holding.status == "closed" or old_shares <= 0:
            old_shares = 0.0
        old_cost = float(holding.cost_basis or 0)
        new_shares = old_shares + shares
        if old_shares <= 0:
            new_cost = price
        else:
            new_cost = (old_shares * old_cost + shares * price) / new_shares
        holding.shares = new_shares
        holding.cost_basis = new_cost
        holding.status = "open"
    else:
        old_shares = float(holding.shares or 0)
        old_cost = float(holding.cost_basis or 0)
        if shares > old_shares + 1e-12:
            raise ValueError(f"Cannot sell {shares} shares; only {old_shares} available")
        remaining = old_shares - shares
        if remaining < 1e-12:
            remaining = 0.0
            holding.shares = 0.0
            holding.status = "closed"
        else:
            # Broker-style: subtract sale proceeds from total cost, then re-average.
            remaining_total = old_shares * old_cost - shares * price
            holding.shares = remaining
            holding.cost_basis = remaining_total / remaining

    holding.updated_at = datetime.now(timezone.utc)

    txn = Transaction(
        holding_id=holding.id,
        action=action,
        shares=shares,
        price=price,
        notes=notes,
    )
    if trade_date is not None:
        txn.date = trade_date
    session.add(txn)
    session.commit()
    return txn


# ── Price Cache ───────────────────────────────────────────


def upsert_price(
    session: Session,
    ticker: str,
    market: str,
    date: datetime,
    close: float,
    open_price: float = None,
    high: float = None,
    low: float = None,
    volume: float = None,
    source: str = "",
) -> PriceCache:
    existing = (
        session.query(PriceCache)
        .filter(
            PriceCache.ticker == ticker.upper(),
            PriceCache.date == date,
        )
        .first()
    )
    if existing:
        existing.close = close
        existing.open_price = open_price
        existing.high = high
        existing.low = low
        existing.volume = volume
        existing.source = source
        session.commit()
        return existing
    entry = PriceCache(
        ticker=ticker.upper(),
        market=market.upper(),
        date=date,
        open_price=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source=source,
    )
    session.add(entry)
    session.commit()
    return entry


def get_price_history(session: Session, ticker: str, limit: int = 100) -> list[PriceCache]:
    return (
        session.query(PriceCache)
        .filter(PriceCache.ticker == ticker.upper())
        .order_by(desc(PriceCache.date))
        .limit(limit)
        .all()
    )


def get_latest_prices(session: Session, holdings: list) -> dict:
    """Return the latest persisted closing price for each holding."""
    prices = {}
    for holding in holdings:
        entry = (
            session.query(PriceCache)
            .filter(
                PriceCache.ticker == holding.ticker.upper(),
                PriceCache.market == holding.market.upper(),
            )
            .order_by(desc(PriceCache.date))
            .first()
        )
        prices[(holding.market, holding.ticker)] = entry.close if entry else None
    return prices


# ── News ──────────────────────────────────────────────────


def save_news_article(
    session: Session,
    headline: str,
    source: str = "wallstreetcn",
    ticker: str = None,
    url: str = None,
    published_at: datetime = None,
    summary: str = None,
) -> NewsArticle:
    article = NewsArticle(
        ticker=ticker.upper() if ticker else None,
        headline=headline,
        source=source,
        url=url,
        published_at=published_at,
        summary=summary,
    )
    session.add(article)
    session.commit()
    return article


def get_recent_news(session: Session, ticker: str = None, limit: int = 50) -> list[NewsArticle]:
    q = session.query(NewsArticle)
    if ticker:
        q = q.filter(NewsArticle.ticker == ticker.upper())
    return q.order_by(desc(NewsArticle.published_at)).limit(limit).all()


# ── Financial Reports (company statements) ────────────────


def save_financial_report(
    session: Session,
    ticker: str,
    market: str,
    report_date: datetime,
    report_type: str,
    revenue: float = None,
    eps: float = None,
    key_metrics: dict = None,
) -> FinancialReport:
    report = FinancialReport(
        ticker=ticker.upper(),
        market=market.upper(),
        report_date=report_date,
        report_type=report_type,
        revenue=revenue,
        eps=eps,
        key_metrics=key_metrics,
    )
    session.add(report)
    session.commit()
    return report


# ── Job runs (kernel task ledger) ─────────────────────────


def create_job_run(
    session: Session, job_id: str, job_name: str, status: str = "running"
) -> JobRun:
    """Record that a scheduled/kernel job has started."""
    run = JobRun(job_id=job_id, job_name=job_name, status=status)
    session.add(run)
    session.commit()
    return run


def finish_job_run(
    session: Session,
    run_id: int,
    status: str,
    details: str = None,
    error_code: str = None,
    report_id: str = None,
):
    """Store a terminal job outcome (done/failed/skipped/...)."""
    run = session.query(JobRun).filter(JobRun.id == run_id).first()
    if run:
        run.status = status
        run.details = details
        run.error_code = error_code
        if report_id is not None:
            run.report_id = report_id
        run.ended_at = datetime.now(timezone.utc)
        session.commit()


def get_job_run(session: Session, run_id: int) -> Optional[JobRun]:
    return session.query(JobRun).filter(JobRun.id == run_id).first()


def list_job_runs(
    session: Session, limit: int = 50, job_id: Optional[str] = None, status: Optional[str] = None
) -> list[JobRun]:
    """Filter before limiting so older failures remain discoverable."""
    query = session.query(JobRun)
    if job_id:
        query = query.filter(JobRun.job_id == job_id)
    if status:
        query = query.filter(JobRun.status == status)
    return query.order_by(desc(JobRun.started_at), desc(JobRun.id)).limit(limit).all()


# ── Audit (user_actions — permanent business audit) ───────


def record_user_action(
    session: Session,
    action: str,
    target_type: str = None,
    target_id: str = None,
    notes: str = None,
    payload: dict = None,
) -> UserAction:
    """Append one business-audit row (kernel white-list writes use this).

    ``payload`` stores the full request JSON verbatim (v2 write commands).
    """
    entry = UserAction(
        action=action,
        target_type=target_type,
        target_id=target_id,
        notes=notes,
        payload=payload,
    )
    session.add(entry)
    session.commit()
    return entry


# ── Watchlist ─────────────────────────────────────────────


def create_watchlist_item(
    session: Session,
    ticker: str,
    market: str,
    name: str = None,
    watch_reason: str = None,
    target_price_low: float = None,
    target_price_high: float = None,
    priority: str = "medium",
) -> "WatchlistItem":
    from db.models import WatchlistItem

    item = WatchlistItem(
        ticker=ticker.upper(),
        market=market.upper(),
        name=name,
        watch_reason=watch_reason,
        target_price_low=target_price_low,
        target_price_high=target_price_high,
        status="watching",
        priority=priority,
    )
    session.add(item)
    session.commit()
    return item


def get_watchlist_items(session: Session, status: str = None) -> list:
    """Return watchlist items, optionally filtered by status."""
    from db.models import WatchlistItem

    q = session.query(WatchlistItem).filter(WatchlistItem.status != "archived")
    if status:
        q = q.filter(WatchlistItem.status == status)
    return q.order_by(WatchlistItem.priority.desc(), WatchlistItem.created_at.desc()).all()


def get_watchlist_by_ticker(session: Session, ticker: str):
    """Return a watchlist item by ticker, or None."""
    from db.models import WatchlistItem

    return (
        session.query(WatchlistItem)
        .filter(WatchlistItem.ticker == ticker.upper(), WatchlistItem.status != "archived")
        .first()
    )


def update_watchlist_item(session: Session, item_id: int, **kwargs):
    """Update watchlist item fields. Returns the updated item or None."""
    from datetime import datetime, timezone

    from db.models import WatchlistItem

    item = session.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
    if item:
        for k, v in kwargs.items():
            if hasattr(item, k):
                setattr(item, k, v)
        item.updated_at = datetime.now(timezone.utc)
        session.commit()
    return item


def delete_watchlist_item(session: Session, item_id: int) -> bool:
    """Archive a watchlist item while preserving its identity and history."""
    from db.models import WatchlistItem

    item = session.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
    if item:
        item.status = "archived"
        session.commit()
        return True
    return False


# ── Dashboard memo ────────────────────────────────────────


def get_trading_discipline(session: Session) -> Optional[TradingDiscipline]:
    return session.get(TradingDiscipline, 1)


def save_trading_discipline(session: Session, content: str) -> TradingDiscipline:
    memo = get_trading_discipline(session)
    if memo is None:
        memo = TradingDiscipline(id=1, content=content.strip())
        session.add(memo)
    else:
        memo.content = content.strip()
        memo.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(memo)
    return memo
