"""P3 storage tests: drop-trace migration, idempotency, retention cleanup."""

import sqlite3
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text

from db.migrate import migrate
from debrief.retention import cleanup_job_runs

LEGACY_SCHEMA = """
CREATE TABLE agent_sessions (
    id INTEGER PRIMARY KEY, triggered_by VARCHAR(20) NOT NULL, job_id VARCHAR(40),
    market VARCHAR(10), job_run_id INTEGER, status VARCHAR(20), summary TEXT,
    started_at DATETIME, ended_at DATETIME
);
CREATE TABLE agent_tool_calls (
    id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, tool_name VARCHAR(50),
    params JSON, result_summary TEXT, called_at DATETIME
);
CREATE TABLE conversation_messages (
    id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, role VARCHAR(20),
    content TEXT, created_at DATETIME
);
CREATE TABLE recommendations (
    id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, ticker VARCHAR(20),
    action VARCHAR(20), reasoning TEXT, confidence FLOAT, urgency VARCHAR(10),
    status VARCHAR(20), created_at DATETIME
);
CREATE TABLE user_actions (
    id INTEGER PRIMARY KEY, recommendation_id INTEGER NOT NULL,
    action VARCHAR(20) NOT NULL, notes TEXT, acted_at DATETIME NOT NULL
);
CREATE TABLE analysis_charts (
    id VARCHAR(32) PRIMARY KEY, session_id INTEGER NOT NULL, payload JSON NOT NULL,
    created_at DATETIME NOT NULL
);
CREATE TABLE holdings (
    id INTEGER PRIMARY KEY, ticker VARCHAR(20) NOT NULL, name VARCHAR(100),
    market VARCHAR(10) NOT NULL, shares FLOAT NOT NULL, cost_basis FLOAT NOT NULL,
    position_type VARCHAR(20), status VARCHAR(20), created_at DATETIME, updated_at DATETIME
);
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY, holding_id INTEGER NOT NULL, action VARCHAR(20),
    shares FLOAT NOT NULL, price FLOAT NOT NULL, date DATETIME, notes TEXT
);
CREATE TABLE memory_documents (
    id INTEGER PRIMARY KEY, source_type VARCHAR(40), source_id INTEGER,
    operation VARCHAR(20), actor VARCHAR(20), title TEXT, body TEXT,
    snapshot JSON, previous JSON, instruments JSON, relations JSON,
    occurred_at DATETIME, known_at DATETIME, time_quality VARCHAR(20),
    content_hash VARCHAR(64), indexed_at DATETIME, vector_profile VARCHAR(64),
    retry_at DATETIME, attempts INTEGER, error TEXT
);
CREATE TABLE memory_checkpoints (source_type VARCHAR(40) PRIMARY KEY, last_id INTEGER);
"""


def make_legacy_db(path):
    con = sqlite3.connect(path)
    con.executescript(LEGACY_SCHEMA)
    con.execute(
        "INSERT INTO user_actions (recommendation_id, action, notes, acted_at) VALUES (7, 'accept', 'legacy note', '2026-10-01 00:00:00')"
    )
    con.execute(
        "INSERT INTO memory_checkpoints VALUES ('analysis', 26), ('message', 1), ('recommendation', 39), ('holding', 8)"
    )
    con.commit()
    con.close()
    return path


def table_names(engine):
    with engine.connect() as conn:
        return {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }


def columns(engine, table):
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}


def test_fresh_db_migrate_is_idempotent(tmp_path):
    db = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{db}")
    migrate(engine)
    first = {r[0] for r in engine.connect().execute(text("SELECT version FROM _migrations"))}
    assert "v10_debrief_drop_trace" in first
    assert "v12_debrief_analysis_reports" in first

    migrate(engine)  # second run applies nothing
    second = {r[0] for r in engine.connect().execute(text("SELECT version FROM _migrations"))}
    assert first == second
    engine.dispose()


def test_legacy_db_drop_trace_preserves_data(tmp_path):
    db = tmp_path / "legacy.db"
    make_legacy_db(db)
    engine = create_engine(f"sqlite:///{db}")
    migrate(engine)

    tables = table_names(engine)
    for trace_table in ("agent_sessions", "agent_tool_calls", "conversation_messages", "recommendations"):
        assert trace_table not in tables

    # One-time archive next to the database.
    backup = tmp_path / "pre-agent-removal-backup.db"
    assert backup.exists()

    # user_actions rebuilt: legacy rows preserved, FK gone, audit columns added.
    assert {"target_type", "target_id"} <= columns(engine, "user_actions")
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT recommendation_id, action, notes FROM user_actions")).all()
    assert rows == [(7, "accept", "legacy note")]

    # analysis_charts rebuilt with report_id instead of session_id.
    assert "report_id" in columns(engine, "analysis_charts")
    assert "session_id" not in columns(engine, "analysis_charts")

    # memory_documents gained compaction bookkeeping columns.
    assert {"archived_into", "archived_at"} <= columns(engine, "memory_documents")

    # Checkpoints pointing at dropped tables removed; others kept.
    with engine.connect() as conn:
        remaining = {
            row[0]
            for row in conn.execute(text("SELECT source_type FROM memory_checkpoints"))
        }
    assert remaining == {"holding"}

    engine.dispose()


def test_legacy_backup_not_overwritten(tmp_path):
    db = tmp_path / "legacy2.db"
    make_legacy_db(db)
    backup = tmp_path / "pre-agent-removal-backup.db"
    backup.write_bytes(b"pre-existing archive")

    engine = create_engine(f"sqlite:///{db}")
    migrate(engine)
    engine.dispose()
    assert backup.read_bytes() == b"pre-existing archive"


def test_retention_cleanup_batches_and_protects_running(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_RUN_RETENTION_DAYS", "30")
    from debrief import retention as ret_module

    monkeypatch.setattr(ret_module, "JOB_RUN_RETENTION_DAYS", 30)
    monkeypatch.setattr(ret_module, "CLEANUP_BATCH_SIZE", 2)

    engine = create_engine(f"sqlite:///{tmp_path / 'runs.db'}")
    from db.models import Base

    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    old = now - timedelta(days=120)
    with engine.begin() as conn:
        for i in range(5):
            conn.execute(
                text(
                    "INSERT INTO job_runs (job_id, job_name, status, started_at, ended_at) "
                    "VALUES ('prices', '价格采集', 'completed', :started, :ended)"
                ),
                {"started": old - timedelta(days=i), "ended": old - timedelta(days=i)},
            )
        # A running old row must be protected from deletion.
        conn.execute(
            text(
                "INSERT INTO job_runs (job_id, job_name, status, started_at) "
                "VALUES ('prices', '价格采集', 'running', :started)"
            ),
            {"started": old - timedelta(days=10)},
        )
        # A recent row stays regardless of status.
        conn.execute(
            text(
                "INSERT INTO job_runs (job_id, job_name, status, started_at, ended_at) "
                "VALUES ('news', '新闻轮询', 'failed', :started, :ended)"
            ),
            {"started": now - timedelta(days=1), "ended": now - timedelta(days=1)},
        )

    result = cleanup_job_runs(engine)
    assert result["deleted"] == 5
    with engine.connect() as conn:
        remaining = conn.execute(text("SELECT count(*) FROM job_runs")).scalar()
    assert remaining == 2  # running old row + recent row
    engine.dispose()
