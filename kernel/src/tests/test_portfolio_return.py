"""Total return includes closed positions and does not double-count partial sells."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from db.migrate import _backfill_opening_buys
from db.models import Base, Holding
from db.repository import create_holding, get_transactions_for_holding
from domain.valuation import calculate_portfolio_totals


def _txn(txn_id, holding_id, action, shares, price, day):
    return SimpleNamespace(
        id=txn_id,
        holding_id=holding_id,
        action=action,
        shares=shares,
        price=price,
        date=datetime(2026, 1, day, tzinfo=timezone.utc),
    )


def _holding(**kwargs):
    defaults = {
        "id": 1,
        "ticker": "AAPL",
        "market": "US",
        "shares": 0,
        "cost_basis": 100,
        "status": "open",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_partial_sell_is_not_counted_twice():
    holding = _holding(shares=6, cost_basis=80, status="open")
    txns = [
        _txn(1, 1, "buy", 10, 100, 1),
        _txn(2, 1, "sell", 4, 130, 2),
    ]
    totals = calculate_portfolio_totals([holding], {("US", "AAPL"): 100}, {"US": 7.0}, txns)
    assert totals["realized_pnl"] == 840.0
    assert totals["unrealized_pnl"] == 0.0
    assert totals["pnl"] == 840.0
    assert totals["pnl"] != 1680.0


def test_closed_position_remains_in_total_return():
    holding = _holding(shares=0, cost_basis=100, status="closed")
    txns = [
        _txn(1, 1, "buy", 10, 100, 1),
        _txn(2, 1, "sell", 10, 90, 2),
    ]
    totals = calculate_portfolio_totals([holding], {}, {"US": 1.0}, txns)
    assert totals["market_value"] == 0
    assert totals["realized_pnl"] == -100
    assert totals["unrealized_pnl"] == 0
    assert totals["pnl"] == -100


def test_legacy_closed_sells_use_residual_cost_once():
    holding = _holding(ticker="600519", market="CN", shares=0, cost_basis=80, status="closed")
    txns = [
        _txn(1, 1, "sell", 4, 130, 1),
        _txn(2, 1, "sell", 6, 100, 2),
    ]
    totals = calculate_portfolio_totals([holding], {}, {"CN": 1.0}, txns)
    assert round(totals["pnl"], 2) == 120.0
    assert round(totals["cost"], 2) == 1000.0


def test_share_edit_does_not_invent_realized_gain():
    holding = _holding(shares=6, cost_basis=100, status="open")
    txns = [_txn(1, 1, "buy", 10, 100, 1)]
    totals = calculate_portfolio_totals([holding], {("US", "AAPL"): 110}, {"US": 1.0}, txns)
    assert totals["positions"][0]["method"] == "residual_open"
    assert totals["realized_pnl"] == 0
    assert totals["unrealized_pnl"] == 60


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        yield db
    finally:
        db.close()


def test_create_holding_writes_opening_buy(session):
    holding = create_holding(session, "AAPL", "US", shares=10, cost_basis=100.0)
    txns = get_transactions_for_holding(session, holding.id)
    assert len(txns) == 1
    assert txns[0].action == "buy"
    assert txns[0].shares == 10
    assert txns[0].price == 100
    assert txns[0].notes == "opening"


def test_backfill_opening_buy_skips_holdings_that_already_traded():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        empty = Holding(
            ticker="MSFT",
            market="US",
            shares=2,
            cost_basis=50,
            position_type="core",
            status="open",
        )
        traded = Holding(
            ticker="AAPL",
            market="US",
            shares=4,
            cost_basis=80,
            position_type="core",
            status="open",
        )
        db.add_all([empty, traded])
        db.commit()
        from db.models import Transaction

        db.add(
            Transaction(
                holding_id=traded.id,
                action="sell",
                shares=1,
                price=90,
            )
        )
        db.commit()
        empty_id, traded_id = empty.id, traded.id
    finally:
        db.close()

    with engine.connect() as conn:
        _backfill_opening_buys(conn)
        conn.commit()
        rows = conn.execute(
            text("SELECT holding_id, action, notes FROM transactions ORDER BY holding_id")
        ).fetchall()

    by_holding = {}
    for holding_id, action, notes in rows:
        by_holding.setdefault(holding_id, []).append((action, notes))
    assert by_holding[empty_id] == [("buy", "opening")]
    assert by_holding[traded_id] == [("sell", None)]


def test_closed_position_in_another_market_keeps_total_return(tmp_path, monkeypatch):
    """A closed HK position must not blank the total return via a missing rate."""
    monkeypatch.setenv("DEBRIEF_FX_USD", "7.2")
    monkeypatch.setenv("DEBRIEF_FX_HKD", "0.92")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")

    from db.repository import apply_trade, create_holding, upsert_price
    from debrief.context import open_engine
    from debrief.kernel import build_holdings_payload

    engine = open_engine(tmp_path / "totals.db")
    with Session(engine) as session:
        create_holding(session, "AAPL", "US", shares=10, cost_basis=100.0, name="苹果")
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        upsert_price(session, "AAPL", "US", today, close=110.0, source="seed")
        hk = create_holding(session, "00700", "HK", shares=10, cost_basis=300.0, name="腾讯")
        apply_trade(session, hk.id, "sell", 10, 350.0)
        session.commit()
        payload = build_holdings_payload(session, refresh=False)
    engine.dispose()

    # 10 * (110 - 100) * 7.2 unrealized + 10 * (350 - 300) * 0.92 realized.
    assert payload["totalPnl"] == pytest.approx(720 + 460)
    assert payload["totalPnlPct"] != 0
