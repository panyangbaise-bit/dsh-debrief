"""After-market input package (news scoping + memory candidates) and A5 window filters."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from db.models import JobRun, LongTermMemory, MemoryDocument
from debrief.commands import (
    _memory_candidates,
    _news_market,
    _scope_news,
    cmd_memory_compact_candidates,
)
from debrief.context import open_engine


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def db(tmp_path):
    engine = open_engine(tmp_path / "ctx.db")
    yield engine
    engine.dispose()


def _ltm(session, topic, instruments, summary="历史结论", evidence=None):
    session.add(
        LongTermMemory(
            topic=topic,
            instruments=instruments,
            summary=summary,
            evidence_refs=evidence or [],
            time_range="{}",
            confidence="high",
        )
    )
    session.flush()


def _doc(session, source_type, instruments, body="证据内容", occurred_at=None):
    session.add(
        MemoryDocument(
            source_type=source_type,
            source_id=0,
            operation="create",
            actor="dsn",
            title=f"{source_type} test",
            body=body,
            snapshot={"content": body},
            instruments=instruments,
            occurred_at=occurred_at or _now(),
            known_at=_now(),
            time_quality="recorded",
            content_hash=f"h-{source_type}-{id(body)}",
        )
    )
    session.flush()


# ── A2: news scoping ─────────────────────────────────────────────────────────


def test_news_market_classifies_chinese_headlines():
    assert _news_market("英伟达财报，AI交易更大的考验") == "US"
    assert _news_market("A股创业板午后跌超3%") == "CN"
    assert _news_market("港股恒生科技指数下挫") == "HK"
    assert _news_market("比特币突破新高，加密市场沸腾") == "CRYPTO"
    assert _news_market("某公司发布新产品") is None


def test_scope_news_keeps_target_and_neutral_drops_other_markets(monkeypatch, db):
    import db.repository as repo

    class Article:
        def __init__(self, headline):
            self.headline = headline
            self.source = "wallstreetcn"
            self.published_at = _now()

    articles = [
        Article("英伟达财报引发美股震荡"),
        Article("A股创业板午后跌超3%"),
        Article("比特币突破新高"),
        Article("央行降准释放流动性"),
        Article("某公司发布新品"),
    ]
    monkeypatch.setattr(repo, "get_recent_news", lambda session, limit=60: articles)
    with Session(db) as session:
        news = _scope_news(session, "CN", limit=12)
    titles = [item["title"] for item in news]
    assert "A股创业板午后跌超3%" in titles
    assert "央行降准释放流动性" in titles
    assert "某公司发布新品" in titles  # neutral passes through
    assert "英伟达财报引发美股震荡" not in titles
    assert "比特币突破新高" not in titles


# ── A1: memory candidates ────────────────────────────────────────────────────


def test_memory_candidates_match_ignoring_market_prefix_and_skip_ops(db):
    with Session(db) as session:
        _ltm(session, "decision-book-2026", ["US:NVDA", "US:QQQ"], evidence=[{"docId": 7}])
        _ltm(session, "ops-general-run-2026-x", [], "任务执行日志")
        _ltm(session, "discipline-and-user-protocol-2026", [])
        session.commit()
        candidates = _memory_candidates(session, {"NVDA", "QQQ"}, "US")
    topics = [item["topic"] for item in candidates]
    assert "decision-book-2026" in topics
    assert "ops-general-run-2026-x" not in topics
    assert "discipline-and-user-protocol-2026" in topics  # discipline binds globally
    decision = next(item for item in candidates if item["topic"] == "decision-book-2026")
    assert decision["evidenceDocIds"] == [7]


def test_memory_candidates_fall_back_to_market_instruments_when_no_holdings(db):
    with Session(db) as session:
        _ltm(session, "decisions-crypto-2026", ["CRYPTO:BTC"])
        _ltm(session, "decision-book-us", ["US:NVDA"])
        session.commit()
        candidates = _memory_candidates(session, set(), "CRYPTO")
    topics = [item["topic"] for item in candidates]
    assert topics and topics[0] == "decisions-crypto-2026"
    assert "decision-book-us" not in topics


# ── A4: compaction excludes run logs ─────────────────────────────────────────


def test_compact_candidates_exclude_run_source_type(db):
    old = _now() - timedelta(days=60)
    with Session(db) as session:
        _doc(session, "run", [], "run id: 1 job_id: prices", occurred_at=old)
        _doc(session, "decision", ["US:NVDA"], "买入 NVDA", occurred_at=old)
        session.commit()
        result = cmd_memory_compact_candidates(session)
    topics = {batch["topic"] for batch in result["batches"]}
    assert all(not topic.startswith("run:") for topic in topics)
    assert "decision:US:NVDA" in topics


# ── A5: date windows ─────────────────────────────────────────────────────────


def test_transactions_since_until(seeded_db, run_cli):
    past = (_now() - timedelta(days=1)).isoformat()
    future = (_now() + timedelta(days=1)).isoformat()
    code, payload = run_cli(["--db", str(seeded_db), "transactions", "--since", past, "--until", future])
    assert code == 0
    # seed = 2 opening buys (create_holding) + 1 explicit buy (apply_trade)
    assert payload["data"]["total"] == 3
    code, payload = run_cli(["--db", str(seeded_db), "transactions", "--since", future])
    assert payload["data"]["total"] == 0


def test_job_list_since_until(db, run_cli):
    with Session(db) as session:
        for label, started in (
            ("old", _now() - timedelta(days=10)),
            ("new", _now()),
        ):
            session.add(
                JobRun(
                    job_id=label,
                    job_name=label,
                    status="succeeded",
                    started_at=started,
                    ended_at=started,
                )
            )
        session.commit()
    cutoff = (_now() - timedelta(days=1)).isoformat()
    code, payload = run_cli(["--db", str(db.url.database), "job", "list", "--since", cutoff])
    assert code == 0
    kinds = [item["kind"] for item in payload["data"]["items"]]
    assert kinds == ["new"]


def test_report_list_window(seeded_db, run_cli):
    # Write two reports with distinct markets via report create, then list one.
    for market in ("US", "CN"):
        code, _ = run_cli(
            ["--db", str(seeded_db), "report", "create"],
            stdin=json.dumps(
                {"market": market, "title": f"盘后 {market}", "summary": "结论"},
                ensure_ascii=False,
            ),
        )
        assert code == 0
    code, payload = run_cli(["--db", str(seeded_db), "report", "list", "--market", "cn"])
    assert code == 0
    assert [item["market"] for item in payload["data"]["items"]] == ["CN"]
    assert payload["data"]["count"] == 1
