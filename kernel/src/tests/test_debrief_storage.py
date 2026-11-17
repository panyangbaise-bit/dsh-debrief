"""Memory compaction state machine, write-back, audit, and catalog ranking."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from db.models import (
    InstrumentCatalog,
    LongTermMemory,
    MemoryCompactionRun,
    MemoryDocument,
    UserAction,
)
from debrief import commands
from debrief.context import open_engine
from debrief.errors import KernelError


def add_doc(session, content, source_type="decision", instruments=None):
    import hashlib

    doc = MemoryDocument(
        source_type=source_type,
        source_id=0,
        operation="create",
        actor="dsn",
        title=f"{source_type} · {', '.join(instruments or []) or '决策沉淀'}",
        body=content,
        snapshot={"content": content},
        instruments=sorted(set(instruments or [])),
        occurred_at=datetime.now(timezone.utc).replace(tzinfo=None),
        known_at=datetime.now(timezone.utc).replace(tzinfo=None),
        time_quality="recorded",
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
    )
    session.add(doc)
    session.flush()
    doc.source_id = doc.id
    session.commit()
    return doc


@pytest.fixture(autouse=True)
def no_live_suggest(monkeypatch):
    from debrief import catalog

    monkeypatch.setattr(catalog, "eastmoney_suggest", lambda *a, **k: [])
    monkeypatch.setattr(catalog, "coingecko_search", lambda *a, **k: [])


@pytest.fixture
def db(tmp_path):
    engine = open_engine(tmp_path / "mem.db")
    yield engine
    engine.dispose()


def test_compact_write_state_machine_and_versioning(db):
    with Session(db) as session:
        first = add_doc(session, "建仓理由：服务收入增长", instruments=["US:AAPL"])
        second = add_doc(session, "加仓复盘：毛利率达标", instruments=["US:AAPL"])
        first_id, second_id = first.id, second.id

    payload = {
        "topic": "position-aapl-rationale",
        "instruments": ["US:AAPL"],
        "summary": "生态护城河 + 服务收入占比提升。",
        "evidenceRefs": [{"docId": first_id, "quote": "服务收入"}],
        "timeRange": {"from": "2026-03-01", "to": "2026-05-01"},
        "confidence": "high",
    }
    with Session(db) as session:
        result = commands.cmd_memory_compact_write(session, payload)
    assert result["version"] == 1
    memory_id = result["id"]

    with Session(db) as session:
        memory = session.get(LongTermMemory, memory_id)
        assert memory.summary == "生态护城河 + 服务收入占比提升。"
        assert memory.version == 1
        runs = session.scalars(select(MemoryCompactionRun)).all()
        assert len(runs) == 1
        assert runs[0].status == "done"
        assert runs[0].result_memory_id == memory_id
        assert runs[0].doc_ids == [first_id]
        # Archived document carries the back-pointer.
        archived = session.get(MemoryDocument, first_id)
        assert archived.archived_into == memory_id
        assert archived.archived_at is not None
        # Audit trail written.
        audit = session.scalars(
            select(UserAction).where(
                UserAction.action == "memory.compact_write",
                UserAction.target_type == "long_term_memory",
            )
        ).all()
        assert len(audit) == 1

    # Re-compaction merges and bumps the version; evidence refs merge by docId.
    payload2 = dict(
        payload,
        summary="重压缩：生态护城河 + 端侧 AI 换机。",
        evidenceRefs=[{"docId": first_id}, {"docId": second_id}],
        confidence="medium",
        caveats="2026 年展望未兑现。",
    )
    with Session(db) as session:
        result2 = commands.cmd_memory_compact_write(session, payload2)
    assert result2["id"] == memory_id
    assert result2["version"] == 2

    with Session(db) as session:
        memory = session.get(LongTermMemory, memory_id)
        assert memory.version == 2
        assert memory.confidence == "medium"
        assert memory.caveats == "2026 年展望未兑现。"
        ref_ids = {ref.get("docId") for ref in memory.evidence_refs}
        assert ref_ids == {first_id, second_id}
        runs = session.scalars(select(MemoryCompactionRun).order_by(MemoryCompactionRun.id)).all()
        assert len(runs) == 2  # a done run per write
        assert all(run.status == "done" for run in runs)


def test_compact_write_failure_marks_run_failed(db, monkeypatch):
    with Session(db) as session:
        doc = add_doc(session, "被压缩的决策内容", instruments=["CN:600519"])
        doc_id = doc.id

    payload = {
        "topic": "cn-discipline",
        "instruments": ["CN:600519"],
        "summary": "纪律总结",
        "evidenceRefs": [{"docId": doc_id}],
        "timeRange": {"from": "2026-01-01", "to": "2026-02-01"},
    }

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("db.repository.record_user_action", boom)
    with Session(db) as session:
        with pytest.raises(KernelError):
            commands.cmd_memory_compact_write(session, payload)
    with Session(db) as session:
        run = session.scalars(select(MemoryCompactionRun)).one()
        assert run.status == "failed"
        assert "disk full" in run.error
        assert run.retry_at is not None
        # Failure must not leave a partial long-term memory.
        assert session.scalar(select(LongTermMemory.id)) is None


def test_compact_write_validates_refs(db):
    with Session(db) as session:
        with pytest.raises(KernelError) as excinfo:
            commands.cmd_memory_compact_write(
                session,
                {
                    "topic": "t",
                    "instruments": [],
                    "summary": "s",
                    "evidenceRefs": [{"docId": 999999}],
                    "timeRange": {"from": "2026-01-01", "to": "2026-02-01"},
                },
            )
    assert excinfo.value.code == "DEBRIEF_VALIDATION"


def test_memory_add_writes_audit_and_indexes(db):
    with Session(db) as session:
        result = commands.cmd_memory_add(
            session,
            {
                "sourceType": "decision",
                "content": "止盈纪律：单标的权重上限 15%。",
                "instruments": ["US:NVDA"],
            },
        )
    doc_id = result["docId"]
    with Session(db) as session:
        doc = session.get(MemoryDocument, doc_id)
        assert doc.source_id == doc_id
        assert doc.indexed_at is not None
        audit = session.scalars(
            select(UserAction).where(
                UserAction.action == "memory.add",
                UserAction.target_type == "memory_document",
                UserAction.target_id == str(doc_id),
            )
        ).all()
        assert len(audit) == 1
        # Immediately searchable through FTS.
        hits = commands._short_hits(session, "止盈纪律")
        assert any(item["evidence"][0]["docId"] == doc_id for item in hits)


def test_compact_candidates_window_and_batching(db):
    old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=90)
    with Session(db) as session:
        for i in range(5):
            doc = add_doc(session, f"旧决策 {i}", instruments=["CN:600519"])
            doc.occurred_at = old + timedelta(days=i)
            session.commit()
        fresh = add_doc(session, "新决策", instruments=["CN:600519"])
        fresh.occurred_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.commit()

    with Session(db) as session:
        result = commands.cmd_memory_compact_candidates(session)
    assert result["pendingCount"] == 5
    assert len(result["batches"]) == 1
    assert result["batches"][0]["topic"] == "decision:CN:600519"
    assert len(result["batches"][0]["items"]) == 5
    ids = {item["docId"] for item in result["batches"][0]["items"]}
    assert len(ids) == 5


def test_catalog_upsert_and_rank(db):
    from debrief.catalog import _upsert_rows
    from debrief.catalog import search as catalog_search

    rows = [
        {"market": "US", "symbol": "AAPL", "name": "苹果", "currency": "USD", "asset_class": "stock", "pinyin_alias": ""},
        {"market": "US", "symbol": "MSFT", "name": "微软", "currency": "USD", "asset_class": "stock", "pinyin_alias": ""},
        {"market": "US", "symbol": "AAPX", "name": "甲科技", "currency": "USD", "asset_class": "stock", "pinyin_alias": ""},
    ]
    with Session(db) as session:
        assert _upsert_rows(session, rows) == 3
        # Ranking: exact code > code prefix.
        items, source = catalog_search(session, "US", "AAPL")
        assert [item["symbol"] for item in items] == ["AAPL"]
        items, _ = catalog_search(session, "US", "AAP")
        assert [item["symbol"] for item in items] == ["AAPL", "AAPX"]
        assert "akshare catalog" in source
        # Re-upsert updates in place (unique market+symbol).
        _upsert_rows(session, [dict(rows[0], name="苹果公司")])
        assert session.scalars(select(InstrumentCatalog)).all()[0].name == "苹果公司"


def test_compact_write_retire_hard_deletes_a_topic(db):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(db) as session:
        session.add(
            LongTermMemory(
                topic="ops-general-run-x", instruments=[], summary="任务执行日志",
                evidence_refs=[], time_range="{}", confidence="medium", compressed_at=now,
            )
        )
        session.commit()
        result = commands.cmd_memory_compact_write(session, {"topic": "ops-general-run-x", "retire": True})
        assert result["retired"] is True and result.get("deleted") is True
        session.expire_all()
        # retire is a hard delete: the row is physically gone, not soft-archived
        assert session.scalars(
            select(LongTermMemory).where(LongTermMemory.topic == "ops-general-run-x")
        ).first() is None
        # retiring twice is a not-found, not a silent success
        with pytest.raises(KernelError) as excinfo:
            commands.cmd_memory_compact_write(session, {"topic": "ops-general-run-x", "retire": True})
        assert excinfo.value.code == "DEBRIEF_NOT_FOUND"


def test_compact_candidates_offer_ops_and_stale_low_for_retirement(db):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    old = now - timedelta(days=400)
    with Session(db) as session:
        for topic, conf, at in (
            ("ops-general-run-1", "high", now),
            ("stale-low", "low", old),
            ("fresh-high", "high", now),
        ):
            session.add(
                LongTermMemory(
                    topic=topic, instruments=[], summary="s", evidence_refs=[],
                    time_range="{}", confidence=conf, compressed_at=at,
                )
            )
        session.commit()
        result = commands.cmd_memory_compact_candidates(session)
    topics = {item["topic"] for item in result["retireCandidates"]}
    assert "ops-general-run-1" in topics
    assert "stale-low" in topics
    assert "fresh-high" not in topics


def test_capture_whitelist_skips_operational_rows(db):
    """Job-run ledger and news rows live in their own tables, not in memory."""
    from db.models import JobRun, NewsArticle
    from db.repository import create_holding

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(db) as session:
        session.add(
            JobRun(job_id="prices", job_name="价格采集", status="succeeded", started_at=now, ended_at=now)
        )
        session.add(
            NewsArticle(ticker=None, headline="某条新闻", source="wallstreetcn", url=None,
                        published_at=now, summary=None, relevance_score=None)
        )
        session.commit()
        assert session.scalars(
            select(MemoryDocument).where(MemoryDocument.source_type.in_(["run", "news"]))
        ).all() == []
    with Session(db) as session:
        create_holding(session, "600519", "CN", shares=100, cost_basis=1400.0, name="贵州茅台")
        session.commit()
        captured = {doc.source_type for doc in session.scalars(select(MemoryDocument)).all()}
        assert "holding" in captured and "transaction" in captured


def test_lexical_index_skips_operational_sources(db):
    from db.models import MemoryChunk
    from memory import indexer

    with Session(db) as session:
        add_doc(session, "run 任务执行日志", source_type="run")
        add_doc(session, "交易 买入 卖出", source_type="transaction", instruments=["US:NVDA"])
        session.commit()
    indexer.index_lexical_batch(db, limit=50)
    with Session(db) as session:
        chunked = session.scalars(
            select(MemoryDocument.id)
            .join(MemoryChunk, MemoryChunk.document_id == MemoryDocument.id)
            .distinct()
        ).all()
        docs = {doc.id: doc.source_type for doc in session.scalars(select(MemoryDocument)).all()}
    assert {docs[ident] for ident in chunked} == {"transaction"}


def test_memory_list_update_restore_remove_lifecycle(db):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(db) as session:
        session.add(
            LongTermMemory(
                topic="position-aapl-rationale", instruments=["US:AAPL"], summary="建仓理由",
                evidence_refs=[], time_range="{}", confidence="high", compressed_at=now,
            )
        )
        session.commit()

        listed = commands.cmd_memory_list(session)
        assert listed["count"] == 1 and listed["items"][0]["topic"] == "position-aapl-rationale"

        updated = commands.cmd_memory_update(
            session, {"topic": "position-aapl-rationale", "summary": "更新的理由", "confidence": "medium"}
        )
        assert updated["version"] == 2

        # retire is a hard delete (user ruling): nothing archived remains
        commands.cmd_memory_compact_write(session, {"topic": "position-aapl-rationale", "retire": True})
        session.expire_all()
        assert commands.cmd_memory_list(session)["count"] == 0
        assert commands.cmd_memory_list(session, include_retired=True)["count"] == 0
        # restore is not-found on a deleted topic
        with pytest.raises(KernelError) as excinfo:
            commands.cmd_memory_update(session, {"topic": "position-aapl-rationale", "restore": True})
        assert excinfo.value.code == "DEBRIEF_NOT_FOUND"

        # restore still works for a legacy soft-retired row (created via SQL)
        session.add(
            LongTermMemory(
                topic="position-aapl-rationale", instruments=["US:AAPL"], summary="建仓理由",
                evidence_refs=[], time_range="{}", confidence="high", compressed_at=now,
            )
        )
        session.commit()
        session.execute(
            text("UPDATE long_term_memories SET retired_at = :t WHERE topic = 'position-aapl-rationale'"),
            {"t": now},
        )
        session.commit()
        session.expire_all()
        assert commands.cmd_memory_update(
            session, {"topic": "position-aapl-rationale", "restore": True}
        )["restored"] is True

        assert commands.cmd_memory_remove(session, {"topic": "position-aapl-rationale"})["removed"] is True
        assert commands.cmd_memory_list(session)["count"] == 0
