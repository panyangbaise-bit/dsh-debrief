"""
Database migration helper — apply schema changes without data loss.
Import and call in config or app init before using models.

Usage:
    from db.migrate import migrate
    migrate(engine)

Legacy agent-trace migrations (v2/v2b/v2c/v6/v9b) reference tables that the
debrief kernel drops; on databases where those tables are already gone they
are recorded as applied no-ops. Fresh databases get every debrief table from
``Base.metadata.create_all``, so the v10+ steps only guard-and-skip.
"""

import json
import logging
from pathlib import Path
from typing import Callable, Union

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

MigrationStep = Union[str, Callable[[Connection], None]]

# Legacy trace tables removed by the debrief kernel (design §3.1).
TRACE_TABLES = ("agent_sessions", "agent_tool_calls", "conversation_messages", "recommendations")
# memory_checkpoints source cursors pointing at the dropped tables.
TRACE_CHECKPOINT_SOURCES = ("analysis", "recommendation", "message")
# VACUUM INTO archive created once before the trace tables are dropped.
TRACE_BACKUP_NAME = "pre-agent-removal-backup.db"


def _table_names(conn: Connection) -> set:
    return {
        row[0]
        for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()
    }


def _columns(conn: Connection, table: str) -> set:
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def _guarded_trace_step(sql: str):
    """Run a legacy step only when its trace table still exists."""

    def step(conn: Connection) -> None:
        tables = _table_names(conn)
        # Extract the target table from a simple ALTER TABLE <t> ... statement.
        parts = sql.split()
        table = parts[2] if len(parts) > 2 and parts[0].upper() == "ALTER" else ""
        if table and table not in tables:
            return  # Table already dropped by the debrief kernel — nothing to do.
        conn.execute(text(sql))

    return step


def _guarded_alter(sql: str, table: str, column: str):
    """ALTER TABLE only when the table exists and the column does not."""

    def step(conn: Connection) -> None:
        if table not in _table_names(conn) or column in _columns(conn, table):
            return
        conn.execute(text(sql))

    return step


def _guarded_backfill(func):
    """Run a backfill only when its primary table exists."""

    def step(conn: Connection) -> None:
        if "holdings" not in _table_names(conn):
            return
        func(conn)

    return step


def _backfill_recommendation_session_ids(conn: Connection) -> None:
    """Relink orphan recommendations (session_id=0) using save_recommendation tool logs.

    Moot on debrief databases (the tables are dropped) — no-ops there.
    """
    if "agent_tool_calls" not in _table_names(conn):
        return
    rows = conn.execute(
        text(
            """
            SELECT session_id, result_summary
            FROM agent_tool_calls
            WHERE tool_name = 'save_recommendation'
              AND session_id > 0
              AND result_summary IS NOT NULL
            """
        )
    ).fetchall()

    updates = []  # (session_id, recommendation_id)
    for session_id, result_summary in rows:
        try:
            payload = json.loads(result_summary)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        if isinstance(payload, dict) and payload.get("status") == "saved":
            rec_id = payload.get("recommendation_id")
            if isinstance(rec_id, int) and rec_id > 0:
                updates.append((session_id, rec_id))
            continue

        if isinstance(payload, dict) and payload.get("batch"):
            for item in payload.get("results") or []:
                if not isinstance(item, dict) or item.get("status") != "saved":
                    continue
                rec_id = item.get("recommendation_id")
                if isinstance(rec_id, int) and rec_id > 0:
                    updates.append((session_id, rec_id))

    for session_id, rec_id in updates:
        conn.execute(
            text(
                """
                UPDATE recommendations
                SET session_id = :sid
                WHERE id = :rid AND (session_id = 0 OR session_id IS NULL)
                """
            ),
            {"sid": session_id, "rid": rec_id},
        )


def _backfill_opening_buys(conn: Connection) -> None:
    """Give open holdings with an empty ledger an opening buy at current cost."""
    rows = conn.execute(
        text(
            """
            SELECT h.id, h.shares, h.cost_basis, h.created_at
            FROM holdings h
            WHERE lower(coalesce(h.status, 'open')) != 'closed'
              AND coalesce(h.shares, 0) > 0
              AND coalesce(h.cost_basis, 0) > 0
              AND NOT EXISTS (
                    SELECT 1 FROM transactions t WHERE t.holding_id = h.id
              )
            """
        )
    ).fetchall()
    for holding_id, shares, cost_basis, created_at in rows:
        conn.execute(
            text(
                """
                INSERT INTO transactions
                    (holding_id, action, shares, price, date, notes)
                VALUES
                    (:hid, 'buy', :shares, :price, coalesce(:date, CURRENT_TIMESTAMP), 'opening')
                """
            ),
            {
                "hid": holding_id,
                "shares": shares,
                "price": cost_basis,
                "date": created_at,
            },
        )


def _create_memory_tables(conn):
    from db.models import MemoryCheckpoint, MemoryChunk, MemoryDocument, MemoryEmbedding

    for model in (MemoryDocument, MemoryChunk, MemoryCheckpoint, MemoryEmbedding):
        model.__table__.create(conn, checkfirst=True)
    conn.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(tokens)"))


def _vacuum_into(engine: Engine, path: Path) -> None:
    """VACUUM INTO must run outside any transaction, on its own connection."""
    raw = engine.raw_connection()
    try:
        dbapi = getattr(raw, "driver_connection", raw)
        dbapi.isolation_level = None  # autocommit
        dbapi.execute("VACUUM INTO ?", (str(path),))
        dbapi.isolation_level = ""
    finally:
        raw.close()


def _migrate_v10_drop_trace(conn: Connection) -> None:
    """P3: archive and drop the legacy LangGraph trace tables (design §3.1)."""
    engine = conn.engine
    tables = _table_names(conn)
    present = [t for t in TRACE_TABLES if t in tables]

    # One-time archive of the whole database before anything is dropped.
    if present:
        db_path = Path(engine.url.database or "portfolio.db")
        backup = db_path.parent / TRACE_BACKUP_NAME
        if not backup.exists():
            _vacuum_into(engine, backup)
            logger.info("Trace backup archived to %s", backup)

    # Rebuild user_actions without the recommendations foreign key (audit is
    # permanent; the trace tables are not).
    if "user_actions" in tables and "target_type" not in _columns(conn, "user_actions"):
        conn.execute(
            text(
                """
                CREATE TABLE user_actions_new (
                    id INTEGER PRIMARY KEY,
                    recommendation_id INTEGER,
                    action VARCHAR(50) NOT NULL,
                    target_type VARCHAR(40),
                    target_id VARCHAR(64),
                    notes TEXT,
                    acted_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO user_actions_new (id, recommendation_id, action, notes, acted_at)
                SELECT id, recommendation_id, action, notes, acted_at FROM user_actions
                """
            )
        )
        conn.execute(text("DROP TABLE user_actions"))
        conn.execute(text("ALTER TABLE user_actions_new RENAME TO user_actions"))
        logger.info("user_actions rebuilt without the recommendations foreign key")

    # Rebuild analysis_charts without the agent_sessions foreign key; charts
    # are report artifacts, not trace.
    if (
        "analysis_charts" in tables
        and "report_id" not in _columns(conn, "analysis_charts")
    ):
        conn.execute(
            text(
                """
                CREATE TABLE analysis_charts_new (
                    id VARCHAR(32) PRIMARY KEY,
                    report_id VARCHAR(64),
                    payload JSON NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO analysis_charts_new (id, report_id, payload, created_at)
                SELECT id, NULL, payload, created_at FROM analysis_charts
                """
            )
        )
        conn.execute(text("DROP TABLE analysis_charts"))
        conn.execute(text("ALTER TABLE analysis_charts_new RENAME TO analysis_charts"))
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_analysis_charts_report_id ON analysis_charts (report_id)")
        )
        logger.info("analysis_charts rebuilt without the agent_sessions foreign key")

    # Drop the trace tables (children before parents).
    for table in ("agent_tool_calls", "conversation_messages", "recommendations", "agent_sessions"):
        if table in tables:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))

    # Source cursors pointing at the dropped tables can never advance again.
    conn.execute(
        text(
            "DELETE FROM memory_checkpoints WHERE source_type IN ('analysis', 'recommendation', 'message')"
        )
    )

    # Memory compaction bookkeeping columns (design §3.2 step 6).
    if "archived_into" not in _columns(conn, "memory_documents"):
        conn.execute(text("ALTER TABLE memory_documents ADD COLUMN archived_into INTEGER"))
    if "archived_at" not in _columns(conn, "memory_documents"):
        conn.execute(text("ALTER TABLE memory_documents ADD COLUMN archived_at DATETIME"))

    # SQLite operational pragmas (design §3.1).
    conn.commit()
    for pragma in ("PRAGMA journal_mode=WAL", "PRAGMA auto_vacuum=INCREMENTAL"):
        try:
            conn.exec_driver_sql(pragma)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("%s failed: %s", pragma, exc)


def _migrate_v11_debrief_tables(conn: Connection) -> None:
    """P3: long-term memory, compaction state machine, instrument catalog."""
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS long_term_memories (
                id INTEGER PRIMARY KEY,
                topic VARCHAR(200) NOT NULL,
                instruments JSON NOT NULL DEFAULT '[]',
                summary TEXT NOT NULL,
                evidence_refs JSON NOT NULL DEFAULT '[]',
                time_range TEXT NOT NULL,
                confidence VARCHAR(10),
                caveats TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                compressed_at DATETIME NOT NULL,
                embedding_profile VARCHAR(64),
                UNIQUE (topic)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS memory_compaction_runs (
                id INTEGER PRIMARY KEY,
                topic VARCHAR(200) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                retry_at DATETIME,
                candidate_count INTEGER NOT NULL DEFAULT 0,
                doc_ids JSON NOT NULL DEFAULT '[]',
                result_memory_id INTEGER,
                error TEXT,
                created_at DATETIME NOT NULL,
                started_at DATETIME,
                finished_at DATETIME
            )
            """
        )
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_compaction_topic ON memory_compaction_runs (topic)")
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS instrument_catalog (
                id INTEGER PRIMARY KEY,
                market VARCHAR(10) NOT NULL,
                symbol VARCHAR(32) NOT NULL,
                name VARCHAR(200) NOT NULL,
                currency VARCHAR(10),
                asset_class VARCHAR(20) NOT NULL DEFAULT 'stock',
                pinyin_alias VARCHAR(300),
                updated_at DATETIME NOT NULL,
                UNIQUE (market, symbol)
            )
            """
        )
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_catalog_market_name ON instrument_catalog (market, name)")
    )


def _migrate_v11b_job_runs_columns(conn: Connection) -> None:
    """job_runs observability columns: error_code + produced report id."""
    columns = _columns(conn, "job_runs")
    if "error_code" not in columns:
        conn.execute(text("ALTER TABLE job_runs ADD COLUMN error_code VARCHAR(40)"))
    if "report_id" not in columns:
        conn.execute(text("ALTER TABLE job_runs ADD COLUMN report_id VARCHAR(64)"))


def _migrate_v12_analysis_reports(conn: Connection) -> None:
    """Analysis report center table (reports are artifacts, not trace)."""
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS analysis_reports (
                id VARCHAR(64) PRIMARY KEY,
                market VARCHAR(10) NOT NULL,
                title VARCHAR(200) NOT NULL,
                summary TEXT NOT NULL,
                full_text TEXT,
                metrics JSON NOT NULL DEFAULT '[]',
                chart_id VARCHAR(32),
                job_run_id INTEGER REFERENCES job_runs(id),
                generated_at DATETIME NOT NULL
            )
            """
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_analysis_reports_market_time "
            "ON analysis_reports (market, generated_at)"
        )
    )


def _migrate_v13_write_columns(conn: Connection) -> None:
    """v2 white-list writes: audit payload column + watchlist alert toggle."""
    if "payload" not in _columns(conn, "user_actions"):
        conn.execute(text("ALTER TABLE user_actions ADD COLUMN payload JSON"))
    if "alert_enabled" not in _columns(conn, "watchlist_items"):
        conn.execute(
            text(
                "ALTER TABLE watchlist_items ADD COLUMN alert_enabled INTEGER NOT NULL DEFAULT 1"
            )
        )


def _migrate_v14_price_cache_fetched_at(conn: Connection) -> None:
    """price_cache fetched_at: freshness marker for on-read price refresh."""
    if "price_cache" in _table_names(conn) and "fetched_at" not in _columns(conn, "price_cache"):
        conn.execute(text("ALTER TABLE price_cache ADD COLUMN fetched_at DATETIME"))


MIGRATIONS = [
    # Each entry: (version, sql_statement | callable)
    # Version 1: add name column to holdings (added 2026-07-18)
    (
        "v1_add_holdings_name",
        _guarded_alter("ALTER TABLE holdings ADD COLUMN name VARCHAR(100)", "holdings", "name"),
    ),
    (
        "v2_agent_sessions_job_market",
        _guarded_trace_step("ALTER TABLE agent_sessions ADD COLUMN job_id VARCHAR(40)"),
    ),
    (
        "v2b_agent_sessions_market",
        _guarded_trace_step("ALTER TABLE agent_sessions ADD COLUMN market VARCHAR(10)"),
    ),
    (
        "v2c_agent_sessions_summary",
        _guarded_trace_step("ALTER TABLE agent_sessions ADD COLUMN summary TEXT"),
    ),
    (
        "v3_create_job_runs",
        """
        CREATE TABLE IF NOT EXISTS job_runs (
            id INTEGER PRIMARY KEY,
            job_id VARCHAR(40) NOT NULL,
            job_name VARCHAR(100) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'running',
            details TEXT,
            started_at DATETIME NOT NULL,
            ended_at DATETIME
        )
        """,
    ),
    (
        "v3b_job_runs_index",
        "CREATE INDEX IF NOT EXISTS ix_job_runs_job_started ON job_runs (job_id, started_at)",
    ),
    (
        "v4_holdings_status",
        _guarded_alter(
            "ALTER TABLE holdings ADD COLUMN status VARCHAR(20) DEFAULT 'open'",
            "holdings",
            "status",
        ),
    ),
    (
        "v5_create_watchlist",
        """
        CREATE TABLE IF NOT EXISTS watchlist_items (
            id INTEGER PRIMARY KEY,
            ticker VARCHAR(20) NOT NULL,
            name VARCHAR(100),
            market VARCHAR(10) NOT NULL,
            watch_reason TEXT,
            target_price_low FLOAT,
            target_price_high FLOAT,
            status VARCHAR(20) NOT NULL DEFAULT 'watching',
            priority VARCHAR(10) NOT NULL DEFAULT 'medium',
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """,
    ),
    (
        "v5b_watchlist_indexes",
        "CREATE INDEX IF NOT EXISTS ix_watchlist_status ON watchlist_items (status)",
    ),
    (
        "v5c_watchlist_ticker_index",
        "CREATE INDEX IF NOT EXISTS ix_watchlist_ticker ON watchlist_items (ticker)",
    ),
    (
        "v6_backfill_recommendation_session_ids",
        _backfill_recommendation_session_ids,
    ),
    (
        "v7_backfill_opening_buys",
        _guarded_backfill(_backfill_opening_buys),
    ),
    (
        "v8_trading_discipline",
        """CREATE TABLE IF NOT EXISTS trading_discipline (
            id INTEGER PRIMARY KEY,
            content TEXT NOT NULL DEFAULT '',
            updated_at DATETIME NOT NULL
        )""",
    ),
    ("v9_memory", _create_memory_tables),
    (
        "v9b_session_run",
        _guarded_trace_step("ALTER TABLE agent_sessions ADD COLUMN job_run_id INTEGER REFERENCES job_runs(id)"),
    ),
    # ── debrief kernel (P3 storage, design §3) ────────────────────────────────
    ("v10_debrief_drop_trace", _migrate_v10_drop_trace),
    ("v11_debrief_memory_catalog", _migrate_v11_debrief_tables),
    ("v11b_debrief_job_runs_columns", _migrate_v11b_job_runs_columns),
    ("v12_debrief_analysis_reports", _migrate_v12_analysis_reports),
    ("v13_debrief_write_columns", _migrate_v13_write_columns),
    ("v14_price_cache_fetched_at", _migrate_v14_price_cache_fetched_at),
]


def migrate(engine: Engine):
    """Apply any pending migrations (idempotent; safe to re-run)."""
    with engine.connect() as conn:
        # Ensure migration tracking table exists
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS _migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        conn.commit()

        applied = {
            row[0] for row in conn.execute(text("SELECT version FROM _migrations")).fetchall()
        }

        for version, step in MIGRATIONS:
            if version in applied:
                continue
            logger.info(f"Applying migration: {version}")
            try:
                if callable(step):
                    step(conn)
                else:
                    conn.execute(text(step))
                conn.execute(
                    text("INSERT INTO _migrations (version) VALUES (:v)"), {"v": version}
                )
                conn.commit()
                logger.info(f"Migration {version} applied.")
            except Exception as e:
                # Column may already exist — skip
                logger.warning(f"Migration {version} skipped: {e}")
                conn.rollback()
