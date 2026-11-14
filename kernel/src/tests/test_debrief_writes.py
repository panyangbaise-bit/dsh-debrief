"""Kernel v2 white-list writes: holdings/watchlist add|update|remove + audit."""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Holding, UserAction, WatchlistItem
from debrief.catalog import _upsert_rows
from debrief.context import open_engine


@pytest.fixture(autouse=True)
def no_live_suggest(monkeypatch):
    from debrief import catalog

    monkeypatch.setattr(catalog, "eastmoney_suggest", lambda *a, **k: [])
    monkeypatch.setattr(catalog, "coingecko_search", lambda *a, **k: [])


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBRIEF_FX_USD", "7.2")
    engine = open_engine(tmp_path / "writes.db")
    yield engine
    engine.dispose()


def seed_catalog(db):
    with Session(db) as session:
        _upsert_rows(
            session,
            [
                {"market": "CN", "symbol": "600519", "name": "贵州茅台", "currency": "CNY", "asset_class": "stock", "pinyin_alias": "gzmt"},
                {"market": "US", "symbol": "AAPL", "name": "苹果", "currency": "USD", "asset_class": "stock", "pinyin_alias": ""},
                {"market": "CC", "symbol": "BTC", "name": "Bitcoin", "currency": "USD", "asset_class": "crypto", "pinyin_alias": ""},
            ],
        )


def audit_rows(db, action=None):
    with Session(db) as session:
        query = select(UserAction).order_by(UserAction.id)
        if action:
            query = query.where(UserAction.action == action)
        return session.scalars(query).all()


# ── holdings add ────────────────────────────────────────────────────────────


def test_holdings_add_with_catalog_name(db):
    seed_catalog(db)
    with Session(db) as session:
        from debrief import commands

        result = commands.cmd_holdings_add(
            session,
            {"market": "cn", "symbol": "600519", "quantity": 100, "cost": 1450},
        )
    assert result == {
        "id": result["id"],
        "market": "CN",
        "symbol": "600519",
        "name": "贵州茅台",
        "quantity": 100.0,
        "cost": 1450.0,
    }
    with Session(db) as session:
        holding = session.scalars(select(Holding)).one()
        assert holding.market == "CN"  # DB-normalized code
        assert holding.shares == 100
        assert holding.status == "open"
        # Opening buy keeps the ledger replayable.
        assert len(holding.transactions) == 1


def test_holdings_add_normalizes_crypto_to_cc(db):
    with Session(db) as session:
        from debrief import commands

        result = commands.cmd_holdings_add(
            session,
            {"market": "crypto", "symbol": "BTC", "name": "Bitcoin", "quantity": 0.5, "cost": 62000},
        )
    assert result["market"] == "CC"
    with Session(db) as session:
        holding = session.scalars(select(Holding)).one()
        assert holding.market == "CRYPTO"


def test_holdings_add_conflict(db):
    seed_catalog(db)
    with Session(db) as session:
        from debrief import commands

        commands.cmd_holdings_add(session, {"market": "cn", "symbol": "600519", "quantity": 100, "cost": 1450})
        with pytest.raises(Exception) as excinfo:
            commands.cmd_holdings_add(session, {"market": "CN", "symbol": "600519", "quantity": 1, "cost": 1})
    assert excinfo.value.code == "DEBRIEF_CONFLICT"


def test_holdings_add_reopens_a_closed_position(db):
    """Fully closed (shares 0) is not a duplicate: re-adding it is a re-buy."""
    seed_catalog(db)
    with Session(db) as session:
        from debrief import commands

        first = commands.cmd_holdings_add(
            session, {"market": "cn", "symbol": "600519", "quantity": 100, "cost": 1450}
        )
        holding = session.get(Holding, first["id"])
        holding.shares = 0.0
        holding.status = "closed"
        session.commit()

        again = commands.cmd_holdings_add(
            session, {"market": "CN", "symbol": "600519", "quantity": 387.93, "cost": 2.5778}
        )
    assert again["id"] == first["id"]  # same record, not a new row
    with Session(db) as session:
        holding = session.get(Holding, first["id"])
        assert holding.status == "open"
        assert holding.shares == pytest.approx(387.93)
        assert holding.cost_basis == pytest.approx(2.5778)
        assert len(holding.transactions) == 2
        assert session.scalars(select(Holding)).all() == [holding]
    notes = [row.notes for row in audit_rows(db, "holding.add")]
    assert notes[-1].startswith("reopen ")


def test_holdings_add_requires_name_without_catalog(db):
    with Session(db) as session:
        from debrief import commands

        with pytest.raises(Exception) as excinfo:
            commands.cmd_holdings_add(session, {"market": "us", "symbol": "ZZZZ", "quantity": 1, "cost": 1})
    assert excinfo.value.code == "DEBRIEF_VALIDATION"


def test_holdings_add_validates_fields(db):
    with Session(db) as session:
        from debrief import commands

        for bad in (
            {"market": "us", "symbol": "AAPL", "name": "x", "quantity": 0, "cost": 1},
            {"market": "us", "symbol": "AAPL", "name": "x", "quantity": 1, "cost": -1},
            {"market": "xx", "symbol": "AAPL", "name": "x", "quantity": 1, "cost": 1},
            {"market": "us", "symbol": "AAPL", "name": "x", "quantity": "ten", "cost": 1},
        ):
            with pytest.raises(Exception) as excinfo:
                commands.cmd_holdings_add(session, bad)
            assert excinfo.value.code in ("DEBRIEF_VALIDATION", "DEBRIEF_ARGS")


# ── holdings update / remove ────────────────────────────────────────────────


def _add_holding(db, market="us", symbol="AAPL", name="苹果"):
    with Session(db) as session:
        from debrief import commands

        return commands.cmd_holdings_add(
            session, {"market": market, "symbol": symbol, "name": name, "quantity": 10, "cost": 100}
        )


def test_holdings_update_by_id_and_by_market_symbol(db):
    _add_holding(db)
    with Session(db) as session:
        from debrief import commands

        result = commands.cmd_holdings_update(session, {"id": 1, "quantity": 25, "cost": 110})
        assert result == {"id": 1, "status": "updated"}
        result = commands.cmd_holdings_update(session, {"market": "us", "symbol": "AAPL", "quantity": 30})
        assert result == {"id": 1, "status": "updated"}
    with Session(db) as session:
        holding = session.scalars(select(Holding)).one()
        assert holding.shares == 30
        assert holding.cost_basis == 110


def test_holdings_update_requires_a_field(db):
    _add_holding(db)
    with Session(db) as session:
        from debrief import commands

        with pytest.raises(Exception) as excinfo:
            commands.cmd_holdings_update(session, {"id": 1})
    assert excinfo.value.code == "DEBRIEF_USAGE"


def test_holdings_update_not_found(db):
    with Session(db) as session:
        from debrief import commands

        for payload in ({"id": 999}, {"market": "us", "symbol": "NOPE"}):
            with pytest.raises(Exception) as excinfo:
                commands.cmd_holdings_update(session, {**payload, "quantity": 1})
            assert excinfo.value.code == "DEBRIEF_NOT_FOUND"


def test_holdings_remove_soft_deletes_and_disappears_from_gets(db):
    _add_holding(db)
    with Session(db) as session:
        from debrief import commands

        result = commands.cmd_holdings_remove(session, {"market": "us", "symbol": "AAPL"})
        assert result == {"id": 1, "status": "removed"}
    with Session(db) as session:
        holding = session.scalars(select(Holding)).one()
        assert holding.status == "archived"
    # GET holdings/dashboard no longer show it.
    from debrief.kernel import build_dashboard_payload, build_holdings_payload

    with Session(db) as session:
        payload = build_holdings_payload(session)
        assert payload["positions"] == []
        dashboard = build_dashboard_payload(session, 30)
        assert dashboard["holdings"] == []


def test_holdings_remove_twice_not_found(db):
    _add_holding(db)
    with Session(db) as session:
        from debrief import commands

        commands.cmd_holdings_remove(session, {"id": 1})
        with pytest.raises(Exception) as excinfo:
            commands.cmd_holdings_remove(session, {"id": 1})
    assert excinfo.value.code == "DEBRIEF_NOT_FOUND"


# ── watchlist add / update / remove ─────────────────────────────────────────


def test_watchlist_add_full(db):
    with Session(db) as session:
        from debrief import commands

        result = commands.cmd_watchlist_add(
            session,
            {"market": "hk", "symbol": "00700", "name": "腾讯控股", "targetPrice": 380, "alert": True},
        )
    assert result == {
        "id": result["id"],
        "market": "HK",
        "symbol": "00700",
        "name": "腾讯控股",
        "targetPrice": 380.0,
        "alert": True,
    }
    with Session(db) as session:
        item = session.scalars(select(WatchlistItem)).one()
        assert item.target_price_low == 380
        assert item.alert_enabled == 1
        assert item.status == "watching"


def test_watchlist_add_defaults_alert_and_null_target(db):
    with Session(db) as session:
        from debrief import commands

        result = commands.cmd_watchlist_add(session, {"market": "us", "symbol": "AAPL"})
    assert result["alert"] is True
    assert result["targetPrice"] is None
    with Session(db) as session:
        item = session.scalars(select(WatchlistItem)).one()
        assert item.target_price_low is None
        assert item.alert_enabled == 1


def test_watchlist_add_conflict_and_validation(db):
    with Session(db) as session:
        from debrief import commands

        commands.cmd_watchlist_add(session, {"market": "hk", "symbol": "00700"})
        with pytest.raises(Exception) as excinfo:
            commands.cmd_watchlist_add(session, {"market": "hk", "symbol": "00700"})
        assert excinfo.value.code == "DEBRIEF_CONFLICT"
        with pytest.raises(Exception) as excinfo:
            commands.cmd_watchlist_add(session, {"market": "us", "symbol": "X", "targetPrice": -5})
        assert excinfo.value.code == "DEBRIEF_VALIDATION"
        with pytest.raises(Exception) as excinfo:
            commands.cmd_watchlist_add(session, {"market": "us", "symbol": "Y", "alert": "yes"})
        assert excinfo.value.code == "DEBRIEF_VALIDATION"


def test_watchlist_update_fields(db):
    with Session(db) as session:
        from debrief import commands

        commands.cmd_watchlist_add(session, {"market": "hk", "symbol": "00700", "targetPrice": 380, "alert": True})
        result = commands.cmd_watchlist_update(session, {"market": "hk", "symbol": "00700", "targetPrice": 400})
        assert result == {"id": 1, "status": "updated"}
        result = commands.cmd_watchlist_update(session, {"id": 1, "alert": False})
        assert result == {"id": 1, "status": "updated"}
    with Session(db) as session:
        item = session.scalars(select(WatchlistItem)).one()
        assert item.target_price_low == 400
        assert item.alert_enabled == 0


def test_watchlist_update_empty_usage_and_not_found(db):
    with Session(db) as session:
        from debrief import commands

        commands.cmd_watchlist_add(session, {"market": "hk", "symbol": "00700"})
        with pytest.raises(Exception) as excinfo:
            commands.cmd_watchlist_update(session, {"id": 1})
        assert excinfo.value.code == "DEBRIEF_USAGE"
        with pytest.raises(Exception) as excinfo:
            commands.cmd_watchlist_update(session, {"market": "hk", "symbol": "NOPE", "alert": False})
        assert excinfo.value.code == "DEBRIEF_NOT_FOUND"


def test_watchlist_remove_soft_deletes(db):
    with Session(db) as session:
        from debrief import commands

        commands.cmd_watchlist_add(session, {"market": "hk", "symbol": "00700"})
        result = commands.cmd_watchlist_remove(session, {"id": 1})
        assert result == {"id": 1, "status": "removed"}
        with pytest.raises(Exception) as excinfo:
            commands.cmd_watchlist_remove(session, {"id": 1})
        assert excinfo.value.code == "DEBRIEF_NOT_FOUND"
    with Session(db) as session:
        item = session.scalars(select(WatchlistItem)).one()
        assert item.status == "archived"
    from debrief.kernel import build_watchlist_payload

    with Session(db) as session:
        assert build_watchlist_payload(session)["count"] == 0


# ── audit trail ─────────────────────────────────────────────────────────────


def test_audit_rows_carry_full_payload(db):
    with Session(db) as session:
        from debrief import commands

        commands.cmd_holdings_add(
            session,
            {"market": "us", "symbol": "AAPL", "name": "苹果", "quantity": 5, "cost": 180.2},
        )
        commands.cmd_holdings_update(session, {"id": 1, "quantity": 8})
        commands.cmd_holdings_remove(session, {"id": 1})
        commands.cmd_watchlist_add(session, {"market": "hk", "symbol": "00700", "targetPrice": 380})
        commands.cmd_watchlist_update(session, {"market": "hk", "symbol": "00700", "alert": False})
        commands.cmd_watchlist_remove(session, {"id": 1})

    expected = [
        ("holding.add", "holding"),
        ("holding.update", "holding"),
        ("holding.remove", "holding"),
        ("watchlist.add", "watchlist"),
        ("watchlist.update", "watchlist"),
        ("watchlist.remove", "watchlist"),
    ]
    rows = audit_rows(db)
    assert [(row.action, row.target_type) for row in rows] == expected
    assert all(row.target_id is not None for row in rows)
    assert all(row.acted_at is not None for row in rows)
    # Payload = full request JSON verbatim.
    assert rows[0].payload == {"market": "us", "symbol": "AAPL", "name": "苹果", "quantity": 5, "cost": 180.2}
    assert rows[1].payload == {"id": 1, "quantity": 8}
    assert rows[3].payload["targetPrice"] == 380


def test_writes_are_read_back_by_cli(seeded_db, run_cli):

    stdin = json.dumps({"market": "us", "symbol": "MSFT", "name": "微软", "quantity": 7, "cost": 400})
    code, payload = run_cli(
        ["--db", str(seeded_db), "holdings", "add", "--json"], stdin=stdin
    )
    assert code == 0
    assert payload["data"]["symbol"] == "MSFT"
    holding_id = payload["data"]["id"]

    # Read path sees it immediately.
    code, payload = run_cli(["--db", str(seeded_db), "holdings", "--json"])
    assert code == 0
    symbols = {p["symbol"] for p in payload["data"]["positions"]}
    assert "MSFT" in symbols

    stdin = json.dumps({"id": holding_id, "quantity": 9})
    code, payload = run_cli(["--db", str(seeded_db), "holdings", "update", "--json"], stdin=stdin)
    assert code == 0
    assert payload["data"]["status"] == "updated"

    # Conflict path via CLI returns envelope + non-zero exit.
    stdin = json.dumps({"market": "us", "symbol": "MSFT", "name": "微软", "quantity": 1, "cost": 1})
    code, payload = run_cli(["--db", str(seeded_db), "holdings", "add", "--json"], stdin=stdin)
    assert code == 1
    assert payload["error"]["code"] == "DEBRIEF_CONFLICT"
