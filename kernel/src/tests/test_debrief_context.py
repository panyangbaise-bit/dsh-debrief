"""DB path resolution and upstream-failure degradation for the CLI."""

from pathlib import Path

import pytest

import config as config_module
from debrief import catalog
from debrief.context import resolve_db_path


@pytest.fixture
def db(tmp_path, monkeypatch):
    from debrief.context import open_engine

    engine = open_engine(tmp_path / "ctx.db")
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_env_db(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_resolve_db_path_defaults_to_project_root_db():
    """No --db and no DATABASE_URL → PROJECT_ROOT/portfolio.db, no exception."""
    path = resolve_db_path(None)
    assert path.name == "portfolio.db"
    assert path == (config_module.PROJECT_ROOT / "portfolio.db").resolve()


def test_resolve_db_path_explicit_arg_wins():
    path = resolve_db_path("/tmp/x.db")
    assert path == Path("/tmp/x.db").resolve()


def test_resolve_db_path_relative_url_anchors_on_project_root(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./x.db")
    path = resolve_db_path(None)
    assert path == (config_module.PROJECT_ROOT / "x.db").resolve()


def test_resolve_db_path_absolute_url_kept(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:////srv/data/x.db")
    assert resolve_db_path(None) == Path("/srv/data/x.db")


def test_instruments_upstream_failure_falls_back_to_local(db, monkeypatch):
    """Any suggest failure → local catalog results, never an exception."""
    from sqlalchemy.orm import Session

    from debrief.catalog import _upsert_rows

    with Session(db) as session:
        _upsert_rows(
            session,
            [
                {"market": "US", "symbol": "MSFT", "name": "微软", "currency": "USD", "asset_class": "stock", "pinyin_alias": ""},
            ],
        )

    def boom(*args, **kwargs):
        raise ConnectionError("upstream timed out")

    monkeypatch.setattr(catalog, "eastmoney_suggest", boom)
    monkeypatch.setattr(catalog, "coingecko_search", boom)

    with Session(db) as session:
        items, source = catalog.search(session, "US", "MSFT")
    assert [item["symbol"] for item in items] == ["MSFT"]
    assert "akshare catalog" in source
