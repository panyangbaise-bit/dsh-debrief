"""Capture immutable business snapshots in the same transaction as the write."""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

_INSTALLED = False
# Memory captures only what the model cannot recompute from a business table:
# user trades, watchlist/position edits, discipline rules and feedback, plus
# written analysis reports. Job-run ledgers (`run`) and news articles (`news`)
# already live in their own tables and are operational noise in memory — every
# 30-minute poll would otherwise mint a memory document.
SOURCE_TYPES = {
    "holdings": "holding",
    "transactions": "transaction",
    "user_actions": "feedback",
    "watchlist_items": "watchlist",
    "trading_discipline": "discipline",
    "financial_reports": "financial",
    "analysis_reports": "report",
}


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def scalar(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def snapshot(obj):
    return {c.key: scalar(getattr(obj, c.key)) for c in inspect(obj).mapper.column_attrs}


def _date(value, fallback):
    if not value:
        return fallback
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def build_document(conn, obj, operation, previous=None, actor=None, backfill=False):
    from db.models import Holding, MemoryDocument, WatchlistItem

    source = SOURCE_TYPES.get(obj.__tablename__)
    if source is None:
        return None
    data = snapshot(obj)
    # Running ledger rows are not yet a report.
    if source == "run" and data.get("status") == "running":
        return None
    # Profile write audits must not become memory evidence: the profile is a
    # projection of memory, and capturing its audit rows would feed the next
    # regeneration with its own output (write → feedback doc → regenerate →
    # write …). Dual condition (plan/README.md A4): target_type anchor plus
    # any profile.* action naming. Audit rows stay in user_actions; only the
    # feedback document is skipped. Covers both this after_flush path and
    # backfill_batch, which builds documents directly.
    if source == "feedback" and (
        data.get("target_type") == "memory_profile"
        or str(data.get("action") or "").startswith("profile.")
    ):
        return None
    now = utcnow()
    relations = []
    ticker, market, name = data.get("ticker"), data.get("market"), data.get("name")

    def related(model, ident, kind):
        if not ident:
            return {}
        relations.append({"source_type": kind, "source_id": ident})
        row = conn.execute(select(model.__table__).where(model.id == ident)).mappings().first()
        return dict(row) if row else {}

    if source == "transaction":
        holding = related(Holding, data.get("holding_id"), "holding")
        ticker, market, name = holding.get("ticker"), holding.get("market"), holding.get("name")
    if ticker and not market:
        markets = list(
            conn.execute(
                select(Holding.market).where(Holding.ticker == ticker).distinct()
            ).scalars()
        )
        if len(markets) == 1:
            market = markets[0]
    instruments = [f"{market or '?'}:{str(ticker).upper()}"] if ticker else []
    # Reports and run details may cover many markets. Match exact codes /
    # known names, never guess market.
    if source in ("report", "run"):
        import re

        content = str(data.get("summary") or data.get("full_text") or data.get("details") or "")
        for model in (Holding, WatchlistItem):
            for row in conn.execute(select(model.ticker, model.market, model.name)):
                if re.search(r"(?<![\w])" + re.escape(row.ticker) + r"(?![\w])", content, re.I) or (
                    row.name and row.name in content
                ):
                    instruments.append(f"{row.market}:{row.ticker.upper()}")
    data["instrument_ticker"] = ticker
    data["instrument_market"] = market
    if name:
        data["instrument_name"] = name
    occurred = _date(
        data.get("date")
        or data.get("acted_at")
        or data.get("published_at")
        or data.get("report_date")
        or data.get("generated_at")
        or data.get("created_at")
        or data.get("started_at")
        or data.get("updated_at"),
        now,
    )
    if operation in ("update", "delete"):
        occurred = now
    # Imported historical mutable records cannot prove when this version was known.
    # Use import time conservatively, never leak hindsight into an as_of query.
    known = now
    quality = "imported" if backfill else "recorded"
    actor = actor or (
        "system"
        if source in ("run", "news", "financial", "report")
        else "user"
    )
    if source == "report":
        title = f"report {data.get('id')} · {data.get('market', '')} · {data.get('title') or operation}"
    else:
        title = f"{source} #{obj.id} · {ticker or data.get('job_id') or ''} · {data.get('action') or data.get('status') or operation}"
    labels = {
        "feedback": "用户反馈 拒绝 忽略 接受",
        "discipline": "交易纪律 规则",
        "transaction": "交易 买入 卖出",
        "report": "分析报告 复盘",
        "watchlist": "关注 观察",
    }
    render_data = dict(data)
    body = (
        labels.get(source, source)
        + "\n\n"
        + "\n\n".join(
            f"{key}: {json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else value}"
            for key, value in render_data.items()
            if value is not None
        )
    )
    # Raw snapshot retains exact values, including the duplicate run output.

    if previous:
        body += "\nPrevious values / 变更前：\n" + json.dumps(
            previous, ensure_ascii=False, default=str
        )
    fingerprint = (data.get("summary") or data.get("details")) if source == "run" else None
    return MemoryDocument(
        source_type=source,
        source_id=obj.id,
        operation=operation,
        actor=actor,
        title=title,
        body=body,
        snapshot=data,
        previous=previous,
        instruments=sorted(set(instruments)),
        relations=relations,
        occurred_at=occurred,
        known_at=known,
        time_quality=quality,
        content_hash=hashlib.sha256((fingerprint or body).strip().encode()).hexdigest(),
    )


def _capture(session, flush_context):
    if session.info.get("skip_memory_capture"):
        return
    conn = session.connection()
    # after_flush: inserted IDs and server defaults are available; histories remain.
    for group, operation in (
        (session.new, "create"),
        (session.dirty, "update"),
        (session.deleted, "delete"),
    ):
        for obj in list(group):
            if getattr(obj, "__tablename__", "") not in SOURCE_TYPES:
                continue
            if operation == "update" and not session.is_modified(obj, include_collections=False):
                continue
            previous = {}
            if operation == "update":
                for attr in inspect(obj).mapper.column_attrs:
                    history = inspect(obj).attrs[attr.key].history
                    if history.has_changes() and history.deleted:
                        previous[attr.key] = scalar(history.deleted[0])
            doc = build_document(
                conn, obj, operation, previous or None, session.info.get("memory_actor")
            )
            if doc:
                session.add(doc)


def install_capture():
    global _INSTALLED
    if not _INSTALLED:
        event.listen(Session, "after_flush", _capture)
        _INSTALLED = True
