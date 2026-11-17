"""Memory profile (investment memory summary) kernel contract tests.

Covers plan/kernel.md §8 test points plus the plan/README.md arbitration
deltas: A1 expectedVersion CAS, A2 closed evidence bundle, A3 metadata-only
audit payload, A4 dual-condition capture exclusion, and caller-derived
updatedBy via `--by user|agent`.
"""

import json

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from db.models import MemoryDocument, MemoryProfile, UserAction
from debrief.context import open_engine
from memory.indexer import backfill_batch

SIX_KEYS = ["portfolio", "habits", "discipline", "risk", "advice", "decisions"]


@pytest.fixture(autouse=True)
def no_live_suggest(monkeypatch):
    from debrief import catalog

    monkeypatch.setattr(catalog, "eastmoney_suggest", lambda *a, **k: [])
    monkeypatch.setattr(catalog, "coingecko_search", lambda *a, **k: [])


@pytest.fixture
def db(tmp_path):
    engine = open_engine(tmp_path / "profile.db")
    yield engine
    engine.dispose()


def _engine_for(db_path):
    engine = open_engine(db_path)
    try:
        yield engine
    finally:
        engine.dispose()


def _write(run_cli, db_path, payload, by="agent"):
    return run_cli(
        ["--db", str(db_path), "profile", "write", "--by", by, "--json"],
        stdin=json.dumps(payload),
    )


def _get(run_cli, db_path):
    return run_cli(["--db", str(db_path), "profile", "get", "--json"])


def _add_decision(run_cli, db_path, content="测试决策内容", instruments=None):
    code, env = run_cli(
        ["--db", str(db_path), "memory", "add", "--json"],
        stdin=json.dumps(
            {
                "sourceType": "decision",
                "content": content,
                "instruments": instruments or ["US:AAPL"],
            }
        ),
    )
    assert code == 0, env
    return env["data"]["docId"]


# ── migration v17 ───────────────────────────────────────────────────────────


def test_v17_creates_and_seeds_memory_profile(db):
    with Session(db) as session:
        rows = session.scalars(select(MemoryProfile)).all()
    assert len(rows) == 1
    assert rows[0].id == 1
    assert rows[0].version == 0
    assert rows[0].sections == []
    assert rows[0].updated_by == "system"
    with db.connect() as conn:
        applied = {
            r[0] for r in conn.execute(text("SELECT version FROM _migrations")).fetchall()
        }
    assert "v17_memory_profile" in applied


def test_v17_rerun_is_idempotent(db):
    from db.migrate import migrate

    migrate(db)
    migrate(db)
    with db.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM memory_profile")).scalar()
        versions = conn.execute(text("SELECT COUNT(*) FROM _migrations WHERE version='v17_memory_profile'")).scalar()
    assert count == 1
    assert versions == 1


def test_v17_seed_survives_create_all_precreated_table(tmp_path):
    from sqlalchemy import create_engine

    from db.migrate import migrate
    from db.models import Base

    path = tmp_path / "precreated.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)  # mirrors open_engine order (create_all before migrate)
    migrate(engine)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, version, sections FROM memory_profile")).all()
    assert rows == [(1, 0, "[]")]
    engine.dispose()


# ── profile get ─────────────────────────────────────────────────────────────


def test_profile_get_empty_library_returns_six_empty_sections(seeded_db, run_cli):
    code, env = _get(run_cli, seeded_db)
    assert code == 0, env
    data = env["data"]
    assert data["version"] == 0
    assert data["generated"] is False
    assert [s["key"] for s in data["sections"]] == SIX_KEYS
    assert all(s["content"] == "" for s in data["sections"])
    assert all(s["updatedBy"] is None for s in data["sections"])
    assert data["markdown"] == ""
    assert data["evidenceRefs"] == []
    assert data["discipline"] is None


def test_profile_get_exposes_closed_evidence_bundle(seeded_db, run_cli):
    code, env = _get(run_cli, seeded_db)
    assert code == 0, env
    evidence = env["data"]["evidence"]
    assert {"longTerm", "discipline", "portfolio", "recentDecisions"} == set(evidence)
    symbols = {(h["market"], h["symbol"]) for h in evidence["portfolio"]["holdings"]}
    assert ("CN", "600519") in symbols
    assert ("US", "AAPL") in symbols
    actions = [t["action"] for t in evidence["portfolio"]["recentTransactions"]]
    assert "buy" in actions


def test_profile_get_returns_discipline_and_evidence_refs(seeded_db, run_cli):
    from db.repository import save_trading_discipline

    engine = next(_engine_for(seeded_db))
    with Session(engine) as session:
        save_trading_discipline(session, "单票仓位不超过 30%")
    doc_id = _add_decision(run_cli, seeded_db)
    code, env = _write(run_cli, seeded_db, {"sections": [{"key": "risk", "content": "中等风险"}], "evidenceRefs": [{"docId": doc_id}]})
    assert code == 0, env
    code, env = _get(run_cli, seeded_db)
    data = env["data"]
    assert data["generated"] is True
    assert data["discipline"]["content"] == "单票仓位不超过 30%"
    assert data["evidenceRefs"] == [{"docId": doc_id}]
    assert data["evidence"]["discipline"]["content"] == "单票仓位不超过 30%"
    by_key = {s["key"]: s for s in data["sections"]}
    assert by_key["risk"]["content"] == "中等风险"
    assert by_key["risk"]["updatedBy"] == "agent"


def test_profile_get_missing_row_degrades_to_empty(seeded_db, run_cli):
    engine = next(_engine_for(seeded_db))
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE memory_profile"))
        conn.commit()
    # open_engine re-runs create_all (empty table) but v17 is already recorded:
    # the defensive branch must return an empty profile, not an error.
    code, env = _get(run_cli, seeded_db)
    assert code == 0, env
    assert env["data"]["version"] == 0
    assert env["data"]["generated"] is False
    assert len(env["data"]["sections"]) == 6


# ── profile write: validation ───────────────────────────────────────────────


def test_profile_write_requires_by_flag(seeded_db, run_cli):
    code, env = run_cli(
        ["--db", str(seeded_db), "profile", "write", "--json"],
        stdin=json.dumps({"sections": [{"key": "risk", "content": "x"}]}),
    )
    assert code == 2
    assert env["error"]["code"] == "DEBRIEF_USAGE"


def test_profile_write_creates_row_and_bumps_version(seeded_db, run_cli):
    code, env = _write(run_cli, seeded_db, {"sections": [{"key": "portfolio", "content": "核心：茅台"}]})
    assert code == 0, env
    assert env["data"]["version"] == 1
    assert env["data"]["updatedBy"] == "agent"
    assert env["data"]["updatedAt"]
    assert [s["key"] for s in env["data"]["sections"]] == SIX_KEYS
    code, env = _write(run_cli, seeded_db, {"sections": [{"key": "portfolio", "content": "核心：茅台（更新）"}]})
    assert env["data"]["version"] == 2


def test_profile_write_partial_update_preserves_other_sections(seeded_db, run_cli):
    _write(run_cli, seeded_db, {"sections": [{"key": "habits", "content": "分批建仓"}]})
    code, env = _write(run_cli, seeded_db, {"sections": [{"key": "portfolio", "content": "茅台+苹果"}]})
    assert code == 0, env
    by_key = {s["key"]: s for s in env["data"]["sections"]}
    assert by_key["habits"]["content"] == "分批建仓"
    assert by_key["habits"]["updatedBy"] == "agent"
    assert by_key["portfolio"]["content"] == "茅台+苹果"
    assert by_key["risk"]["content"] == ""


def test_profile_write_unknown_section_key_rejected(seeded_db, run_cli):
    code, env = _write(run_cli, seeded_db, {"sections": [{"key": "peformance", "content": "x"}]})
    assert code == 1
    assert env["error"]["code"] == "DEBRIEF_VALIDATION"


def test_profile_write_duplicate_keys_rejected(seeded_db, run_cli):
    payload = {
        "sections": [
            {"key": "risk", "content": "a"},
            {"key": "risk", "content": "b"},
        ]
    }
    code, env = _write(run_cli, seeded_db, payload)
    assert code == 1
    assert env["error"]["code"] == "DEBRIEF_VALIDATION"


def test_profile_write_rejects_payload_updated_by_and_title_markdown(seeded_db, run_cli):
    for payload in (
        {"sections": [{"key": "risk", "content": "x", "updatedBy": "agent"}]},
        {"updatedBy": "agent", "sections": [{"key": "risk", "content": "x"}]},
        {"title": "风险画像", "sections": [{"key": "risk", "content": "x"}]},
        {"markdown": "## 风险画像", "sections": [{"key": "risk", "content": "x"}]},
    ):
        code, env = _write(run_cli, seeded_db, payload)
        assert code == 1, payload
        assert env["error"]["code"] == "DEBRIEF_VALIDATION", payload


def test_profile_write_agent_truncates_overlong_content(seeded_db, run_cli):
    long_text = "长" * 2500
    code, env = _write(run_cli, seeded_db, {"sections": [{"key": "advice", "content": long_text}]})
    assert code == 0, env
    assert env["data"]["truncated"] == ["advice"]
    by_key = {s["key"]: s for s in env["data"]["sections"]}
    assert len(by_key["advice"]["content"]) == 2000


def test_profile_write_user_rejects_overlong_content(seeded_db, run_cli):
    code, env = _write(run_cli, seeded_db, {"sections": [{"key": "advice", "content": "长" * 2500}]}, by="user")
    assert code == 1
    assert env["error"]["code"] == "DEBRIEF_VALIDATION"


def test_profile_write_total_limit_rejected(seeded_db, run_cli):
    payload = {"sections": [{"key": key, "content": "x" * 1500} for key in SIX_KEYS]}
    code, env = _write(run_cli, seeded_db, payload)
    assert code == 1
    assert env["error"]["code"] == "DEBRIEF_VALIDATION"


def test_profile_write_requires_sections_or_refs(seeded_db, run_cli):
    code, env = _write(run_cli, seeded_db, {})
    assert code == 1
    assert env["error"]["code"] == "DEBRIEF_VALIDATION"


# ── profile write: CAS / protection / idempotency ───────────────────────────


def test_profile_write_expected_version_conflict(seeded_db, run_cli):
    _write(run_cli, seeded_db, {"sections": [{"key": "risk", "content": "v1"}]})
    code, env = _write(
        run_cli,
        seeded_db,
        {"sections": [{"key": "risk", "content": "v2"}], "expectedVersion": 0},
    )
    assert code == 1
    assert env["error"]["code"] == "DEBRIEF_CONFLICT"
    code, env = _get(run_cli, seeded_db)
    by_key = {s["key"]: s for s in env["data"]["sections"]}
    assert by_key["risk"]["content"] == "v1"  # nothing changed


def test_profile_write_protects_user_sections_for_agent(seeded_db, run_cli):
    _write(run_cli, seeded_db, {"sections": [{"key": "habits", "content": "用户手改"}]}, by="user")
    code, env = _write(
        run_cli,
        seeded_db,
        {
            "sections": [
                {"key": "habits", "content": "agent 试图覆盖"},
                {"key": "portfolio", "content": "agent 正常写"},
            ],
            "protectUserSections": True,
        },
        by="agent",
    )
    assert code == 0, env
    assert env["data"]["preserved"] == ["habits"]
    by_key = {s["key"]: s for s in env["data"]["sections"]}
    assert by_key["habits"]["content"] == "用户手改"
    assert by_key["habits"]["updatedBy"] == "user"
    assert by_key["portfolio"]["content"] == "agent 正常写"


def test_profile_write_user_bypasses_protection(seeded_db, run_cli):
    _write(run_cli, seeded_db, {"sections": [{"key": "habits", "content": "用户手改"}]}, by="user")
    code, env = _write(
        run_cli,
        seeded_db,
        {"sections": [{"key": "habits", "content": "用户再改"}], "protectUserSections": True},
        by="user",
    )
    assert code == 0, env
    assert env["data"]["preserved"] == []
    by_key = {s["key"]: s for s in env["data"]["sections"]}
    assert by_key["habits"]["content"] == "用户再改"


def test_profile_write_noop_is_idempotent(seeded_db, run_cli):
    engine = next(_engine_for(seeded_db))
    payload = {"sections": [{"key": "risk", "content": "不变内容"}]}
    code, first = _write(run_cli, seeded_db, payload)
    assert code == 0
    with Session(engine) as session:
        audits_before = len(session.scalars(select(UserAction)).all())
    code, second = _write(run_cli, seeded_db, payload)
    assert code == 0, second
    assert second["data"]["noop"] is True
    assert second["data"]["version"] == first["data"]["version"]
    with Session(engine) as session:
        audits_after = len(session.scalars(select(UserAction)).all())
    assert audits_after == audits_before  # noop writes no audit row


# ── evidence refs ───────────────────────────────────────────────────────────


def test_profile_write_evidence_refs_validated(seeded_db, run_cli):
    doc_id = _add_decision(run_cli, seeded_db)
    code, env = _write(run_cli, seeded_db, {"evidenceRefs": [{"docId": doc_id}]})
    assert code == 0, env
    assert env["data"]["evidenceRefs"] == [{"docId": doc_id}]

    code, env = _write(run_cli, seeded_db, {"evidenceRefs": [{"docId": 999999}]})
    assert code == 1
    assert env["error"]["code"] == "DEBRIEF_VALIDATION"

    code, env = _write(run_cli, seeded_db, {"evidenceRefs": ["not-a-ref"]})
    assert code == 1
    assert env["error"]["code"] == "DEBRIEF_VALIDATION"

    code, env = _write(run_cli, seeded_db, {"evidenceRefs": []})
    assert code == 0, env
    assert env["data"]["evidenceRefs"] == []


# ── audit: A3 metadata-only payload ─────────────────────────────────────────


def test_profile_write_audit_payload_is_metadata_only(seeded_db, run_cli):
    body = "高度敏感的个人画像正文 marker-secret-9f3a"
    _write(run_cli, seeded_db, {"sections": [{"key": "risk", "content": body}]}, by="user")
    engine = next(_engine_for(seeded_db))
    with Session(engine) as session:
        actions = session.scalars(
            select(UserAction).where(UserAction.action == "profile.write")
        ).all()
    assert len(actions) == 1
    action = actions[0]
    assert action.target_type == "memory_profile"
    assert action.target_id == "1"
    assert body not in action.notes
    assert set(action.payload) == {
        "version",
        "previousVersion",
        "updatedBy",
        "changedSections",
        "preservedSections",
        "truncatedSections",
        "sectionChars",
    }
    assert action.payload["updatedBy"] == "user"
    assert action.payload["changedSections"] == ["risk"]
    assert action.payload["sectionChars"]["risk"] == len(body)
    assert body not in json.dumps(action.payload)


# ── capture exclusion: A4 (event path + backfill path) ──────────────────────


def _feedback_docs(db_path):
    engine = open_engine(db_path)
    try:
        with Session(engine) as session:
            return session.scalars(
                select(MemoryDocument).where(MemoryDocument.source_type == "feedback")
            ).all()
    finally:
        engine.dispose()


def test_profile_write_audit_not_captured_as_feedback(seeded_db, run_cli):
    engine = next(_engine_for(seeded_db))
    _write(run_cli, seeded_db, {"sections": [{"key": "risk", "content": "审计不应成为证据"}]})
    _write(run_cli, seeded_db, {"sections": [{"key": "risk", "content": "再写一次"}]}, by="user")

    with Session(engine) as session:
        leak = session.scalars(
            select(MemoryDocument).where(
                MemoryDocument.source_type == "feedback",
                MemoryDocument.snapshot["target_type"].as_string() == "memory_profile",
            )
        ).all()
        by_action = session.scalars(
            select(MemoryDocument).where(
                MemoryDocument.source_type == "feedback",
                MemoryDocument.snapshot["action"].as_string().startswith("profile."),
            )
        ).all()
    assert leak == []
    assert by_action == []

    # backfill path: the checkpoint cursor would otherwise mint documents later.
    count = backfill_batch(engine, limit=200)
    with Session(engine) as session:
        after = session.scalars(
            select(MemoryDocument).where(
                MemoryDocument.source_type == "feedback",
                MemoryDocument.snapshot["target_type"].as_string() == "memory_profile",
            )
        ).all()
    assert after == []
    assert count >= 0  # backfill itself must not resurrect the excluded rows


# ── retrieval isolation: profile content stays out of every memory surface ──


def test_profile_content_not_in_memory_search(seeded_db, run_cli):
    marker = "画像唯一标记词 profilemarker-8c2d"
    _write(run_cli, seeded_db, {"sections": [{"key": "risk", "content": marker}]})
    code, env = run_cli(["--db", str(seeded_db), "memory", "search", "--query", marker, "--json"])
    assert code == 0, env
    assert all(marker not in item.get("summary", "") for item in env["data"]["items"])


def test_profile_not_in_compact_candidates(seeded_db, run_cli):
    _write(run_cli, seeded_db, {"sections": [{"key": "risk", "content": "不影响压缩候选"}]})
    code, env = run_cli(["--db", str(seeded_db), "memory", "compact-candidates", "--json"])
    assert code == 0, env
    for batch in env["data"]["batches"]:
        assert batch["topic"] != "feedback:memory_profile"


# ── envelope shapes ─────────────────────────────────────────────────────────


def test_profile_envelope_shapes(seeded_db, run_cli):
    code, env = _get(run_cli, seeded_db)
    assert code == 0
    assert env["ok"] is True
    assert env["schemaVersion"] == 1
    assert set(env["data"]) == {
        "version",
        "generated",
        "updatedAt",
        "updatedBy",
        "sections",
        "markdown",
        "evidenceRefs",
        "discipline",
        "evidence",
    }
    code, env = _write(run_cli, seeded_db, {"sections": [{"key": "risk", "content": "x"}]})
    assert code == 0
    assert set(env["data"]) == {
        "version",
        "updatedAt",
        "updatedBy",
        "noop",
        "preserved",
        "truncated",
        "sections",
        "markdown",
        "evidenceRefs",
    }
