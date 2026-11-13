from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db.models import Base
from db.repository import get_trading_discipline, save_trading_discipline


def test_rules_survive_new_sessions_and_can_be_updated_or_cleared():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        assert get_trading_discipline(db) is None
        save_trading_discipline(db, "  先止损，再开仓。\n避免冲动交易。  ")
    with Session(engine) as db:
        assert get_trading_discipline(db).content == "先止损，再开仓。\n避免冲动交易。"
        save_trading_discipline(db, "Updated rule")
    with Session(engine) as db:
        assert get_trading_discipline(db).content == "Updated rule"
        save_trading_discipline(db, "")
        assert get_trading_discipline(db).content == ""


def test_migration_adds_memo_table_to_existing_database():
    from db.migrate import migrate

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Base.metadata.tables["trading_discipline"].drop(engine)
    migrate(engine)
    migrate(engine)
    assert "trading_discipline" in inspect(engine).get_table_names()
    with Session(engine) as db:
        save_trading_discipline(db, "Persisted after migration")
        assert get_trading_discipline(db).content == "Persisted after migration"
