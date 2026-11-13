"""Database context for the debrief kernel: engine, pragmas, migration, helpers."""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from config import PROJECT_ROOT
from debrief.errors import KernelError

# Market normalization: the CLI contract uses us|cn|hk|crypto, the database
# stores US|CN|HK|CRYPTO, and the JSON schema renders crypto as CC (as the
# plugin mock does).
MARKET_INPUT_TO_DB = {"US": "US", "CN": "CN", "HK": "HK", "CRYPTO": "CRYPTO", "CC": "CRYPTO"}
MARKET_DB_TO_OUTPUT = {"US": "US", "CN": "CN", "HK": "HK", "CRYPTO": "CC"}

MARKET_LABELS = {"US": "美股", "CN": "A股", "HK": "港股", "CC": "加密"}


def normalize_market_db(value: str) -> str:
    market = MARKET_INPUT_TO_DB.get((value or "").strip().upper())
    if market is None:
        raise KernelError(
            "DEBRIEF_ARGS", f"invalid market '{value}'; expected one of us, cn, hk, crypto"
        )
    return market


def market_to_output(value: str) -> str:
    return MARKET_DB_TO_OUTPUT.get((value or "").strip().upper(), (value or "").strip().upper())


def resolve_db_path(db_arg: Optional[str] = None) -> Path:
    """Resolve the SQLite file path from --db, DATABASE_URL, or the default.

    ``PROJECT_ROOT`` is the config module's module-level constant (the Config
    instance does not expose it).
    """
    if db_arg:
        return Path(db_arg).expanduser().resolve()
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite:///"):
        raw = url[len("sqlite:///") :]
        path = Path(raw)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.expanduser().resolve()
    return Path(PROJECT_ROOT / "portfolio.db")


def _apply_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA auto_vacuum=INCREMENTAL")
    cursor.execute("PRAGMA foreign_keys=OFF")
    cursor.close()


def open_engine(db_path: Path, *, migrate: bool = True) -> Engine:
    """Open (and if needed migrate) the kernel database."""
    if not db_path.parent.exists():
        raise KernelError("DEBRIEF_DB", f"database directory does not exist: {db_path.parent}")
    engine = create_engine(
        f"sqlite:///{db_path}", echo=False, connect_args={"timeout": 15}
    )
    event.listen(engine, "connect", _apply_pragmas)
    if migrate:
        try:
            from db.migrate import migrate as run_migrations
            from db.models import Base

            Base.metadata.create_all(engine)
            run_migrations(engine)
        except KernelError:
            raise
        except Exception as exc:
            raise KernelError("DEBRIEF_DB", f"database migration failed: {exc}") from exc
    return engine


def open_session(db_path: Path, migrate: bool = True) -> tuple[Session, Engine]:
    engine = open_engine(db_path, migrate=migrate)
    return Session(engine), engine


def display_now() -> str:
    from datetime import timezone as _tz

    from common.time import format_display_time

    return format_display_time(datetime.now(_tz.utc), fmt="%Y-%m-%d %H:%M")
