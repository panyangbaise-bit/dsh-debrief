"""Keep the default suite isolated from local credentials and the live ledger."""

import io
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

# These must be set before application modules import config during collection.
# Provider-specific tests replace transports with deterministic fixtures.
_test_data = tempfile.TemporaryDirectory(prefix="portfolio-agent-tests-")
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_test_data.name) / 'test.db'}"
os.environ["DEEPSEEK_API_KEY"] = "test-only-not-a-real-key"
for key in (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "LANGSMITH_API_KEY",
    "LANGCHAIN_API_KEY",
    "BRAVE_SEARCH_API_KEY",
    "MEMORY_EMBEDDING_API_KEY",
    "DASHSCOPE_API_KEY",
    "MEMORY_QDRANT_API_KEY",
    "A2A_TOKEN",
    "ACTIONS_TOKEN",
):
    os.environ[key] = ""
for key in (
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING_V2",
    "MEMORY_VECTOR_ENABLED",
    "A2A_ENABLED",
    "ACTIONS_ENABLED",
):
    os.environ[key] = "false"


# ── debrief kernel fixtures ───────────────────────────────────────────────────

from db.repository import (  # noqa: E402 — env must be set first
    apply_trade,
    create_holding,
    create_watchlist_item,
    upsert_price,
)
from debrief.context import open_engine  # noqa: E402 — env must be set first


def _make_seed(db_path):
    """Create and migrate a fresh database with deterministic portfolio data."""
    engine = open_engine(db_path)
    session = Session(engine)
    try:
        create_holding(session, "600519", "CN", shares=200, cost_basis=1450.0, name="贵州茅台")
        h_aapl = create_holding(session, "AAPL", "US", shares=100, cost_basis=180.2, name="苹果")
        apply_trade(session, h_aapl.id, "buy", 100, 185.0)
        create_watchlist_item(
            session, "00700", "HK", name="腾讯控股", target_price_low=380.0, priority="high"
        )
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)
        upsert_price(session, "600519", "CN", yesterday, close=1450.0, source="seed")
        upsert_price(session, "600519", "CN", today, close=1412.0, source="seed")
        upsert_price(session, "AAPL", "US", yesterday, close=182.4, source="seed")
        upsert_price(session, "AAPL", "US", today, close=189.5, source="seed")
    finally:
        session.close()
    engine.dispose()
    return db_path


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBRIEF_FX_USD", "7.2")
    monkeypatch.setenv("DEBRIEF_FX_HKD", "0.92")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    return _make_seed(tmp_path / "kernel.db")


@pytest.fixture
def run_cli(monkeypatch, capsys):
    """Run the CLI in-process; return (exit_code, envelope dict)."""
    import debrief.cli as cli

    def run(argv, stdin=None):
        if stdin is not None:
            monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        try:
            code = cli.main(argv)
        except SystemExit as exc:  # fail_and_exit raises SystemExit with the code
            code = exc.code if isinstance(exc.code, int) else 1
        out = capsys.readouterr().out
        assert out.strip(), "CLI produced no stdout"
        return code, json.loads(out)

    return run
