"""Implementations of every debrief CLI command (envelope-shaped returns)."""

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from db.models import (
    AnalysisChart,
    AnalysisReport,
    JobRun,
    LongTermMemory,
    MemoryChunk,
    MemoryCompactionRun,
    MemoryDocument,
    Transaction,
    WatchlistItem,
)
from debrief import catalog
from debrief.context import MARKET_LABELS, display_now, market_to_output, normalize_market_db
from debrief.errors import KernelError, UsageError, require_string
from debrief.kernel import (
    build_dashboard_payload,
    build_holdings_payload,
    build_transactions_payload,
    build_watchlist_payload,
)
from memory.indexer import chunks as split_chunks
from memory.indexer import tokens as tokenize

logger = logging.getLogger(__name__)

MEMORY_SHORT_TERM_DAYS = int(os.environ.get("MEMORY_SHORT_TERM_DAYS", "30"))
MEMORY_SHORT_TERM_MAX = int(os.environ.get("MEMORY_SHORT_TERM_MAX", "500"))
MEMORY_RETIRE_DAYS = int(os.environ.get("MEMORY_RETIRE_DAYS", "180"))
MEMORY_COMPACT_BATCH = min(int(os.environ.get("MEMORY_COMPACT_BATCH", "30")), 30)
MEMORY_ARCHIVE_DELETE = os.environ.get("MEMORY_ARCHIVE_DELETE", "false").lower() in (
    "1",
    "true",
    "yes",
)

KIND_LABELS = {
    "after-market-us": "盘后分析 · 美股",
    "after-market-cn": "盘后分析 · A股",
    "after-market-hk": "盘后分析 · 港股",
    "after-market-crypto": "盘后分析 · 加密",
    "news-scan": "盘前新闻扫描",
    "news": "新闻轮询",
    "weekly-review": "周复盘",
    "monthly-review": "月度复盘",
    "memory-compact": "记忆压缩",
    "prices": "价格采集",
    "catalog-sync": "目录同步",
    "reminders": "提醒比对",
    "cleanup": "台账清理",
}

DISPLAY_STATUS = {
    "completed": "succeeded",
    "skipped": "succeeded",
    "succeeded": "succeeded",
    "done": "succeeded",
    "failed": "failed",
    "running": "running",
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fmt_time(dt) -> str:
    from common.time import format_display_time

    if dt is None:
        return "—"
    return format_display_time(dt, fmt="%Y-%m-%d %H:%M")


def _fmt_date(dt) -> str:
    from common.time import format_display_time

    if dt is None:
        return "—"
    return format_display_time(dt, fmt="%Y-%m-%d")


# ── holdings / transactions / watchlist / dashboard (thin glue) ────────────


def cmd_holdings(session: Session, status: Optional[str], refresh: Optional[bool] = None) -> dict:
    if status and status not in ("open",):
        raise KernelError("DEBRIEF_ARGS", f"--status must be 'open'; got '{status}'")
    return build_holdings_payload(session, status, refresh=refresh)


def cmd_transactions(
    session: Session,
    ticker: Optional[str],
    limit: int,
    offset: int,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> dict:
    return build_transactions_payload(session, ticker, limit, offset, since=since, until=until)


def cmd_watchlist(session: Session, ticker: Optional[str], refresh: Optional[bool] = None) -> dict:
    return build_watchlist_payload(session, ticker, refresh=refresh)


def cmd_dashboard(session: Session, range_days: int, refresh: Optional[bool] = None) -> dict:
    return build_dashboard_payload(session, range_days, refresh=refresh)


# ── news / fx / notify ──────────────────────────────────────────────────────


def cmd_news_latest(
    session: Session, limit: int, refresh: bool = True, notify: bool = False
) -> dict:
    from db.models import NewsArticle
    from db.repository import get_recent_news

    limit = max(1, min(limit, 100))
    fetched, new_count, new_items = False, 0, []
    if refresh:
        try:
            from debrief.worker import collect_news

            result = collect_news(session)
            fetched = True
            new_count = int(result.get("saved") or 0)
            new_items = list(result.get("items") or [])
        except Exception:
            fetched, new_count, new_items = False, 0, []
    rows = get_recent_news(session, limit=limit)
    items = [
        {
            "id": article.id,
            "title": article.headline,
            "source": article.source,
            "url": article.url,
            "summary": article.summary,
            "publishedAt": _fmt_time(article.published_at),
        }
        for article in rows
    ]
    payload = {
        "items": items,
        "total": session.query(NewsArticle).count(),
        "fetched": fetched,
        "newCount": new_count,
        "asOf": display_now(),
        "notified": False,
    }
    if notify and new_count > 0:
        try:
            from notifier.telegram import is_configured, notify_news_digest

            if is_configured():
                payload["notified"] = bool(notify_news_digest(new_items, count=new_count))
        except Exception:
            payload["notified"] = False
    return payload


def cmd_fx(base: str) -> dict:
    from adapters.fx import get_rates

    try:
        return get_rates(base)
    except Exception as exc:
        raise KernelError(
            "DEBRIEF_FX_UNAVAILABLE",
            "no FX rates from open.er-api.com for base '"
            + str(base or "CNY").upper()
            + f"' ({exc}); set DEBRIEF_FX_<CCY>=<CNY per CCY> env overrides"
            " (e.g. DEBRIEF_FX_USD=7.2) or check connectivity",
        ) from None


def cmd_notify_test() -> dict:
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    from common.time import format_display_time
    from notifier.telegram import is_configured, notify

    if not is_configured():
        raise KernelError(
            "DEBRIEF_TELEGRAM_UNCONFIGURED",
            "未配置 Telegram：请设置 TELEGRAM_BOT_TOKEN 与 TELEGRAM_CHAT_ID"
            "（插件 Config.telegram.botToken/chatId 或内核环境变量）",
        )
    now = format_display_time(_dt.now(_tz.utc))
    return {"sent": bool(notify(f"✅ <b>debrief 推送测试</b>\n<code>{now}</code>"))}


def cmd_notify_status() -> dict:
    from config import config

    token = config.TELEGRAM_BOT_TOKEN or ""
    chat_id = config.TELEGRAM_CHAT_ID or ""
    token_mask = None
    if token:
        if len(token) <= 8:
            token_mask = f"{token[0]}…{token[-1]}" if len(token) > 1 else "…"
        else:
            token_mask = f"{token[:4]}…{token[-4:]}"
    return {
        "configured": bool(token and chat_id),
        "chatIdSet": bool(chat_id),
        "tokenMask": token_mask,
    }


# ── instruments ────────────────────────────────────────────────────────────


def cmd_instruments(session: Session, market: str, query: str) -> dict:
    market_db = normalize_market_db(market)
    query = query.strip()
    if len(query) < 2:
        raise KernelError("DEBRIEF_ARGS", "--query must be at least 2 characters")
    items, source = catalog.search(session, market_db, query)
    held = catalog.held_symbols(session, market_db)
    for item in items:
        if item["symbol"].upper() in held:
            item["held"] = True
    market_label = "crypto" if market.lower() in ("crypto", "cc") else market.lower()
    return {"query": query, "market": market_label, "source": source, "items": items}


# ── report ─────────────────────────────────────────────────────────────────


def _report_dict(session: Session, report: AnalysisReport) -> dict:
    chart = None
    if report.chart_id:
        row = session.get(AnalysisChart, report.chart_id)
        if row:
            chart = row.payload or {}
    return {
        "id": report.id,
        "market": market_to_output(report.market),
        "title": report.title,
        "generatedAt": _fmt_time(report.generated_at),
        "summary": report.summary,
        "fullText": report.full_text,
        "metrics": list(report.metrics or []),
        "chart": chart,
    }


def cmd_report_latest(session: Session, market: Optional[str]) -> dict:
    query = session.query(AnalysisReport).order_by(
        desc(AnalysisReport.generated_at), desc(AnalysisReport.id)
    )
    if market:
        market_db = normalize_market_db(market)
        query = query.filter(AnalysisReport.market == market_db)
    report = query.first()
    if report is None:
        raise KernelError("DEBRIEF_NOT_FOUND", "no analysis report found")
    return _report_dict(session, report)


def cmd_report_by_id(session: Session, report_id: str) -> dict:
    report = session.get(AnalysisReport, report_id)
    if report is None:
        raise KernelError("DEBRIEF_NOT_FOUND", f"analysis report '{report_id}' not found")
    return _report_dict(session, report)


def cmd_report_list(
    session: Session,
    market: Optional[str],
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = 50,
) -> dict:
    """Reports in a window (newest first) — lets weekly/monthly reviews page the
    whole week instead of only the single latest report."""
    limit = max(1, min(limit, 100))
    query = session.query(AnalysisReport).order_by(
        desc(AnalysisReport.generated_at), desc(AnalysisReport.id)
    )
    if market:
        query = query.filter(AnalysisReport.market == normalize_market_db(market))
    if since is not None:
        query = query.filter(AnalysisReport.generated_at >= since)
    if until is not None:
        query = query.filter(AnalysisReport.generated_at < until)
    reports = query.limit(limit).all()
    return {
        "items": [
            {
                "id": report.id,
                "market": market_to_output(report.market),
                "title": report.title,
                "generatedAt": _fmt_time(report.generated_at),
                "summary": report.summary,
            }
            for report in reports
        ],
        "count": len(reports),
    }


def cmd_report_create(session: Session, payload: dict) -> dict:
    from db.repository import finish_job_run, record_user_action

    market_db = normalize_market_db(require_string(payload, "market") or "")
    title = require_string(payload, "title") or ""
    summary = require_string(payload, "summary") or ""
    full_text = payload.get("fullText")
    if full_text is not None and not isinstance(full_text, str):
        raise KernelError("DEBRIEF_VALIDATION", "fullText must be a string")
    metrics = payload.get("metrics") or []
    if not isinstance(metrics, list):
        raise KernelError("DEBRIEF_VALIDATION", "metrics must be a list")
    cleaned_metrics = []
    for metric in metrics:
        if not isinstance(metric, dict) or "label" not in metric or "value" not in metric:
            raise KernelError("DEBRIEF_VALIDATION", "each metric needs {label, value}")
        cleaned_metrics.append({"label": str(metric["label"]), "value": str(metric["value"])})
    chart = payload.get("chart")
    if chart is not None:
        if (
            not isinstance(chart, dict)
            or not isinstance(chart.get("title", ""), str)
            or not isinstance(chart.get("points", []), list)
        ):
            raise KernelError("DEBRIEF_VALIDATION", "chart needs {title, unit?, points[]}")

    report_id = f"rpt-{datetime.now(timezone.utc):%Y-%m-%d}-{market_to_output(market_db).lower()}"
    existing = session.get(AnalysisReport, report_id)
    suffix = 1
    while existing is not None:
        suffix += 1
        candidate = f"{report_id}-{suffix}"
        existing = session.get(AnalysisReport, candidate)
        report_id = candidate

    chart_id = None
    if chart:
        chart_id = uuid.uuid4().hex[:8]
        session.add(
            AnalysisChart(
                id=chart_id,
                report_id=report_id,
                payload={"title": chart.get("title", ""), "unit": chart.get("unit", ""), "points": chart["points"]},
            )
        )

    report = AnalysisReport(
        id=report_id,
        market=market_db,
        title=title,
        summary=summary,
        full_text=full_text,
        metrics=cleaned_metrics,
        chart_id=chart_id,
    )
    session.add(report)

    job_status = "created"
    job_id = payload.get("jobId")
    if job_id is not None:
        run = session.get(JobRun, int(job_id)) if str(job_id).isdigit() else None
        if run is None:
            raise KernelError("DEBRIEF_NOT_FOUND", f"job run '{job_id}' not found")
        run.report_id = report_id
        finish_job_run(session, run.id, "succeeded", details=f"report {report_id}", report_id=report_id)
        job_status = "succeeded"
    else:
        session.commit()
    record_user_action(
        session,
        "report.create",
        target_type="analysis_report",
        target_id=report_id,
        notes=title,
    )
    notified = False
    try:
        from config import config
        from notifier.telegram import is_configured, notify

        if config.TELEGRAM_REPORT_PUSH and is_configured():
            notified = bool(
                notify(
                    f"📋 <b>复盘报告 · {market_to_output(market_db)}</b>\n{title}\n\n{summary}"
                )
            )
    except Exception:
        notified = False
    return {"id": report_id, "status": job_status, "notified": notified}


# ── memory ─────────────────────────────────────────────────────────────────


def _long_term_matches(session: Session, query: str) -> list[LongTermMemory]:
    words = [w for w in tokenize(query) if len(w) > 1]
    memories = session.scalars(
        select(LongTermMemory)
        .where(LongTermMemory.retired_at.is_(None))
        .order_by(desc(LongTermMemory.version), desc(LongTermMemory.id))
    ).all()
    scored = []
    haystack_query = query.lower()
    for memory in memories:
        if (memory.topic or "").startswith("ops-"):
            continue
        haystack = (
            f"{memory.topic} {memory.summary} {' '.join(memory.instruments or [])}".lower()
        )
        if not words and haystack_query not in haystack:
            continue
        score = sum(1 for word in words if word in haystack)
        if haystack_query in haystack:
            score += 2
        if score:
            scored.append((score, memory))
    scored.sort(key=lambda pair: (-pair[0], -pair[1].id))
    return [memory for _, memory in scored[:5]]


def _long_item(session: Session, memory: LongTermMemory) -> dict:
    evidence = []
    for ref in memory.evidence_refs or []:
        doc_id = ref.get("docId") if isinstance(ref, dict) else ref
        doc = session.get(MemoryDocument, int(doc_id)) if str(doc_id).isdigit() else None
        quote = (ref.get("quote") if isinstance(ref, dict) else None)
        evidence.append(
            {
                "docId": int(doc_id),
                "date": _fmt_date(doc.occurred_at) if doc else "—",
                "label": doc.title if doc else f"document {doc_id}",
                "quote": (quote or (doc.body[:200] if doc else "")) or "",
            }
        )
    try:
        window = json.loads(memory.time_range) if memory.time_range else {}
        time_range = f"{window.get('from', '')} ~ {window.get('to', '')}".strip(" ~")
    except (TypeError, ValueError):
        time_range = memory.time_range or ""
    return {
        "layer": "long",
        "topic": memory.topic,
        "instruments": list(memory.instruments or []),
        "confidence": memory.confidence or "medium",
        "timeRange": time_range or "—",
        "summary": memory.summary,
        "evidence": evidence,
    }


def _short_hits(session: Session, query: str, limit: int = 5) -> list[dict]:
    words = list(dict.fromkeys(tokenize(query)))[:48]
    lexical = []
    if words:
        fts = " OR ".join('"' + w + '"' for w in words)
        lexical = [
            r[0]
            for r in session.execute(
                text(
                    """
                    SELECT c.id FROM memory_fts
                    JOIN memory_chunks c ON c.id = memory_fts.rowid
                    JOIN memory_documents d ON d.id = c.document_id
                    WHERE memory_fts MATCH :q AND d.archived_into IS NULL AND d.source_type != 'run' 
                    ORDER BY bm25(memory_fts), c.id DESC LIMIT 80
                    """
                ),
                {"q": fts},
            )
        ]
    results, seen = [], set()
    if lexical:
        for chunk_id in lexical:
            chunk = session.get(MemoryChunk, chunk_id)
            doc = session.get(MemoryDocument, chunk.document_id) if chunk else None
            if doc is None or doc.content_hash in seen or doc.archived_into is not None:
                continue
            seen.add(doc.content_hash)
            results.append(_short_item(session, doc, chunk.body[:300]))
            if len(results) >= limit:
                break
    # LIKE fallback for not-yet-indexed documents (fresh seeds / imports).
    if len(results) < limit:
        pattern = f"%{query.strip()}%"
        rows = session.scalars(
            select(MemoryDocument)
            .where(
                MemoryDocument.archived_into.is_(None),
                (MemoryDocument.body.like(pattern)) | (MemoryDocument.title.like(pattern)),
            )
            .order_by(desc(MemoryDocument.id))
            .limit(100)
        ).all()
        for doc in rows:
            if doc.content_hash in seen:
                continue
            seen.add(doc.content_hash)
            results.append(_short_item(session, doc, doc.body[:300]))
            if len(results) >= limit:
                break
    return results


def _short_item(session: Session, doc: MemoryDocument, excerpt: str) -> dict:
    instruments = [market_to_output(i.split(":")[0]) + ":" + i.split(":", 1)[-1] if ":" in (i or "") else i for i in (doc.instruments or [])]
    return {
        "layer": "short",
        "topic": doc.title or f"{doc.source_type} #{doc.id}",
        "instruments": instruments,
        "confidence": "high" if doc.time_quality == "recorded" else "low",
        "timeRange": _fmt_date(doc.occurred_at),
        "summary": excerpt[:300],
        "evidence": [
            {
                "docId": doc.id,
                "date": _fmt_date(doc.occurred_at),
                "label": doc.title or f"{doc.source_type} #{doc.id}",
                "quote": (doc.body or "")[:200],
            }
        ],
    }


def cmd_memory_search(session: Session, query: str) -> dict:
    query = query.strip()
    if not query:
        raise KernelError("DEBRIEF_ARGS", "--query is required")
    items = [_long_item(session, memory) for memory in _long_term_matches(session, query)]
    items += _short_hits(session, query)
    return {"query": query, "items": items}


def _candidate_topics(doc: MemoryDocument) -> str:
    first = (doc.instruments or ["general"])[0]
    return f"{doc.source_type}:{first}"


def cmd_memory_compact_candidates(session: Session) -> dict:
    cutoff = _now() - timedelta(days=MEMORY_SHORT_TERM_DAYS)
    # Operational `run` ledger captures (prices/reminders/news jobs) are not
    # investment memory: never offer them as compaction candidates, or they
    # flood long-term memory with "通用定时任务执行日志" topics.
    unarchived = session.scalars(
        select(MemoryDocument).where(
            MemoryDocument.archived_into.is_(None),
            MemoryDocument.source_type != "run",
        )
    ).all()
    expired = [doc for doc in unarchived if (doc.occurred_at or _now()) < cutoff]
    overflow = len(unarchived) - MEMORY_SHORT_TERM_MAX
    if overflow > 0:
        expired_ids = {doc.id for doc in expired}
        oldest = sorted(
            (doc for doc in unarchived if doc.id not in expired_ids),
            key=lambda d: (d.occurred_at or _now(), d.id),
        )[:overflow]
        expired.extend(oldest)
        expired.sort(key=lambda d: (d.occurred_at or _now(), d.id))
    candidates = [doc for doc in expired if doc.archived_into is None]

    # Group by topic (source_type + first instrument), batches of ≤30.
    grouped: dict[str, list] = {}
    order: list[str] = []
    for doc in candidates:
        topic = _candidate_topics(doc)
        if topic not in grouped:
            grouped[topic] = []
            order.append(topic)
        grouped[topic].append(doc)
    batches = []
    for topic in order:
        docs = grouped[topic]
        for start in range(0, len(docs), MEMORY_COMPACT_BATCH):
            batches.append(
                {
                    "topic": topic,
                    "items": [
                        {
                            "docId": doc.id,
                            "content": (doc.body or "")[:2000],
                            "occurredAt": (doc.occurred_at or _now()).isoformat(),
                            "instruments": list(doc.instruments or []),
                        }
                        for doc in docs[start : start + MEMORY_COMPACT_BATCH]
                    ],
                }
            )
    # Forgetting: operational-noise topics and stale low-confidence summaries
    # are offered for retirement (archived, never deleted — stays auditable).
    retire_cutoff = _now() - timedelta(days=MEMORY_RETIRE_DAYS)
    retire_candidates = []
    for memory in session.scalars(
        select(LongTermMemory)
        .where(LongTermMemory.retired_at.is_(None))
        .order_by(desc(LongTermMemory.compressed_at))
    ).all():
        stale_low = memory.confidence == "low" and (memory.compressed_at or _now()) < retire_cutoff
        if (memory.topic or "").startswith("ops-") or stale_low:
            retire_candidates.append(
                {
                    "topic": memory.topic,
                    "id": memory.id,
                    "confidence": memory.confidence,
                    "compressedAt": _fmt_window(memory.compressed_at),
                    "daysSince": max(0, (_now() - (memory.compressed_at or _now())).days),
                }
            )
    return {"batches": batches, "pendingCount": len(candidates), "retireCandidates": retire_candidates}


def _iso_parse(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        return None


def _fmt_window(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        return dt.strftime("%Y-%m-%d")
    return dt.isoformat()


def cmd_memory_compact_write(session: Session, payload: dict) -> dict:
    from db.repository import record_user_action

    topic = require_string(payload, "topic") or ""
    if payload.get("retire"):
        memory = session.scalars(
            select(LongTermMemory).where(
                LongTermMemory.topic == topic, LongTermMemory.retired_at.is_(None)
            )
        ).first()
        if memory is None:
            raise KernelError("DEBRIEF_NOT_FOUND", f"active long-term memory '{topic}' not found")
        memory.retired_at = _now()
        record_user_action(
            session,
            "memory.retire",
            target_type="long_term_memory",
            target_id=str(memory.id),
            notes=topic,
        )
        session.commit()
        return {"id": memory.id, "version": memory.version, "retired": True}
    summary = require_string(payload, "summary") or ""
    instruments = payload.get("instruments") or []
    if not isinstance(instruments, list):
        raise KernelError("DEBRIEF_VALIDATION", "instruments must be a list of strings")
    refs = payload.get("evidenceRefs") or []
    if not isinstance(refs, list) or not refs:
        raise KernelError("DEBRIEF_VALIDATION", "evidenceRefs must be a non-empty list")
    doc_ids = []
    for ref in refs:
        if isinstance(ref, dict):
            doc_id = ref.get("docId")
        elif isinstance(ref, (int, str)):
            doc_id = ref
        else:
            raise KernelError("DEBRIEF_VALIDATION", "each evidenceRef needs a docId")
        if not str(doc_id).isdigit():
            raise KernelError("DEBRIEF_VALIDATION", f"invalid docId: {doc_id!r}")
        doc_ids.append(int(doc_id))
    for doc_id in doc_ids:
        if session.get(MemoryDocument, doc_id) is None:
            raise KernelError(
                "DEBRIEF_VALIDATION", f"evidence docId {doc_id} does not exist"
            )
    time_range = payload.get("timeRange") or {}
    if not isinstance(time_range, dict) or "from" not in time_range or "to" not in time_range:
        raise KernelError("DEBRIEF_VALIDATION", "timeRange needs {from, to}")
    confidence = payload.get("confidence")
    if confidence not in (None, "high", "medium", "low"):
        raise KernelError("DEBRIEF_VALIDATION", "confidence must be high|medium|low")
    caveats = payload.get("caveats")
    if caveats is not None and not isinstance(caveats, str):
        raise KernelError("DEBRIEF_VALIDATION", "caveats must be a string")

    # Outbox state machine: reuse an unfinished run, else create one.
    run = session.scalars(
        select(MemoryCompactionRun)
        .where(MemoryCompactionRun.topic == topic)
        .order_by(desc(MemoryCompactionRun.id))
    ).first()
    if run is None or run.status == "done":
        run = MemoryCompactionRun(topic=topic, status="pending", doc_ids=doc_ids)
        session.add(run)
        session.commit()
    run.status = "running"
    run.attempts = (run.attempts or 0) + 1
    run.candidate_count = len(doc_ids)
    run.doc_ids = doc_ids
    run.started_at = _now()
    run.error = None
    session.commit()

    memory_id = None
    try:
        existing = session.scalars(
            select(LongTermMemory).where(LongTermMemory.topic == topic)
        ).first()
        if existing is not None:
            existing.version = (existing.version or 1) + 1
            existing.summary = summary
            merged_instruments = sorted(set(existing.instruments or []) | set(instruments))
            existing.instruments = merged_instruments
            merged_refs = {ref.get("docId") if isinstance(ref, dict) else ref: ref for ref in (existing.evidence_refs or [])}
            for ref in refs:
                key = ref.get("docId") if isinstance(ref, dict) else ref
                merged_refs[key] = ref
            existing.evidence_refs = list(merged_refs.values())
            window = json.loads(existing.time_range) if isinstance(existing.time_range, str) else {}
            old_from, old_to = _iso_parse(window.get("from") or ""), _iso_parse(window.get("to") or "")
            new_from, new_to = _iso_parse(time_range.get("from") or ""), _iso_parse(time_range.get("to") or "")
            merged_from = min([d for d in (old_from, new_from) if d]) if (old_from or new_from) else None
            merged_to = max([d for d in (old_to, new_to) if d]) if (old_to or new_to) else None
            existing.time_range = json.dumps(
                {
                    "from": _fmt_window(merged_from) or time_range.get("from", ""),
                    "to": _fmt_window(merged_to) or time_range.get("to", ""),
                },
                ensure_ascii=False,
            )
            if confidence:
                existing.confidence = confidence
            if caveats is not None:
                existing.caveats = caveats
            existing.compressed_at = _now()
            memory = existing
        else:
            memory = LongTermMemory(
                topic=topic,
                instruments=sorted(set(instruments)),
                summary=summary,
                evidence_refs=refs,
                time_range=json.dumps(time_range, ensure_ascii=False),
                confidence=confidence,
                caveats=caveats,
                version=1,
                compressed_at=_now(),
            )
            session.add(memory)
            session.flush()
        memory_id = memory.id

        session.execute(
            text(
                """
                UPDATE memory_documents
                SET archived_into = :mid, archived_at = :now
                WHERE id IN (SELECT value FROM json_each(:ids)) AND archived_into IS NULL
                """
            ),
            {"mid": memory_id, "now": _now(), "ids": json.dumps(doc_ids)},
        )
        if MEMORY_ARCHIVE_DELETE:
            session.execute(
                text(
                    """
                    DELETE FROM memory_fts WHERE rowid IN (
                        SELECT c.id FROM memory_chunks c
                        JOIN memory_documents d ON d.id = c.document_id
                        WHERE d.id IN (SELECT value FROM json_each(:ids))
                    )
                    """
                ),
                {"ids": json.dumps(doc_ids)},
            )
            session.execute(
                text(
                    """
                    DELETE FROM memory_chunks WHERE document_id IN (SELECT value FROM json_each(:ids))
                    """
                ),
                {"ids": json.dumps(doc_ids)},
            )
            session.execute(
                text(
                    "UPDATE memory_documents SET body = '' WHERE id IN (SELECT value FROM json_each(:ids))"
                ),
                {"ids": json.dumps(doc_ids)},
            )
        run.status = "done"
        run.result_memory_id = memory_id
        run.finished_at = _now()
        record_user_action(
            session,
            "memory.compact_write",
            target_type="long_term_memory",
            target_id=str(memory_id),
            notes=topic,
        )
        session.commit()
        return {"id": memory_id, "version": memory.version}
    except KernelError:
        raise
    except Exception as exc:
        # Roll the write back so a failed compaction leaves no partial memory;
        # only the run's failed-state update survives (the running state was
        # committed before the write began).
        session.rollback()
        run = session.get(MemoryCompactionRun, run.id)
        run.status = "failed"
        run.error = str(exc)[:1000]
        run.retry_at = _now() + timedelta(seconds=min(3600, 30 * 2 ** min(run.attempts, 7)))
        run.finished_at = _now()
        session.commit()
        raise KernelError("DEBRIEF_INTERNAL", f"compaction write failed: {exc}") from exc


def cmd_memory_add(session: Session, payload: dict) -> dict:
    from db.repository import record_user_action

    source_type = require_string(payload, "sourceType") or ""
    if len(source_type) > 40:
        raise KernelError("DEBRIEF_VALIDATION", "sourceType must be at most 40 characters")
    content = require_string(payload, "content") or ""
    instruments = payload.get("instruments") or []
    if not isinstance(instruments, list) or not all(isinstance(i, str) for i in instruments):
        raise KernelError("DEBRIEF_VALIDATION", "instruments must be a list of strings")
    occurred_at = _iso_parse(payload.get("occurredAt") or "") or _now()

    doc = MemoryDocument(
        source_type=source_type,
        source_id=0,  # self-referential id assigned after flush
        operation="create",
        actor="dsn",
        title=f"{source_type} · {', '.join(instruments) if instruments else '决策沉淀'}",
        body=content,
        snapshot={"content": content},
        instruments=sorted(set(instruments)),
        occurred_at=occurred_at,
        known_at=_now(),
        time_quality="recorded",
        content_hash=hashlib.sha256(content.strip().encode()).hexdigest(),
        archived_into=None,
    )
    session.add(doc)
    session.flush()
    doc.source_id = doc.id

    # Index lexically right away so the evidence is searchable immediately.
    from memory.indexer import tokens as _tokens

    for ordinal, piece in enumerate(split_chunks(doc.body)):
        chunk = MemoryChunk(document_id=doc.id, ordinal=ordinal, body=piece)
        session.add(chunk)
        session.flush()
        session.execute(
            text("INSERT INTO memory_fts(rowid, tokens) VALUES (:id, :tokens)"),
            {"id": chunk.id, "tokens": " ".join(_tokens(doc.title + " " + piece))},
        )
    doc.indexed_at = _now()
    record_user_action(
        session,
        "memory.add",
        target_type="memory_document",
        target_id=str(doc.id),
        notes=doc.title,
    )
    session.commit()
    return {"docId": doc.id}


# ── analysis prepare ───────────────────────────────────────────────────────

# Keyword hints to scope the single WallStreetCN feed per market. Purely a
# relevance heuristic; untagged items still pass through as "general".
NEWS_MARKET_KEYWORDS = {
    "US": ("美股", "纳斯达克", "纳指", "标普", "道指", "道琼斯", "美联储", "华尔街", "美元", "美债", "英伟达", "苹果", "微软", "特斯拉", "亚马逊", "谷歌", "meta", "台积电", "openai", "anthropic", "sec", "降息", "加息", "非农", "通胀"),
    "CN": ("a股", "上证", "深证", "创业板", "科创板", "北证", "央行", "人民币", "社融", "贷款", "券商", "北向", "沪深", "中证", "宁德时代", "比亚迪", "茅台", "lpr", "mlf", "降准"),
    "HK": ("港股", "恒生", "恒指", "港交所", "南向", "港股通", "腾讯", "阿里", "美团", "小米", "快手", "京东"),
    "CRYPTO": ("加密", "比特币", "以太坊", "区块链", "币安", "coinbase", "稳定币", "山寨币", "狗狗币", "defi", "nft", "挖矿"),
}


def _news_market(headline: str) -> Optional[str]:
    """Best-effort market tag for a headline; None when it is market-neutral."""
    text = (headline or "").lower()
    best, best_score = None, 0
    for market, words in NEWS_MARKET_KEYWORDS.items():
        score = sum(1 for word in words if word in text)
        if score > best_score:
            best, best_score = market, score
    return best if best_score >= 1 else None


def _scope_news(session: Session, market_db: str, limit: int = 12) -> list[dict]:
    """Recent news scoped to one market (unrecognised/neutral items included).

    The feed is a single WallStreetCN stream skewing US/macro; without this the
    A股/港股/加密盘后 all read the same US items.
    """
    from db.repository import get_recent_news

    scoped = []
    for article in get_recent_news(session, limit=60):
        tag = _news_market(article.headline or "")
        if tag is None or tag == market_db:
            scoped.append(
                {
                    "title": article.headline,
                    "at": _fmt_time(article.published_at),
                    "source": article.source,
                    "market": tag or "general",
                }
            )
        if len(scoped) >= limit:
            break
    return scoped


def _strip_market(symbol: str) -> str:
    """Comparable instrument key: 'US:NVDA' / '09992.HK' / 'NVDA' → 'NVDA' / '09992'."""
    value = (symbol or "").strip()
    if ":" in value:
        value = value.split(":", 1)[1]
    if "." in value:
        value = value.split(".", 1)[0]
    return value.upper()


def _memory_candidates(session: Session, symbols, market_db: str, limit: int = 6) -> list[dict]:
    """Historical context for the after-market analysis.

    Matches by instrument (market prefix ignored); a market with no holdings/
    watchlist falls back to memories tagged for that market. Operational `run`
    logs and `ops-*` compaction noise never count, and candidates carry the
    citable evidence doc ids so the report can reference [[cite:doc:<id>]].
    """
    keys = {_strip_market(symbol) for symbol in symbols if symbol}
    candidates: list[dict] = []

    def matches(instruments) -> bool:
        values = [str(i) for i in (instruments or [])]
        if keys:
            return bool(keys & {_strip_market(i) for i in values})
        return any(str(i).startswith(market_db + ":") for i in values)

    def candidate(memory: LongTermMemory) -> dict:
        refs = memory.evidence_refs or []
        doc_ids = [
            int(ref.get("docId") if isinstance(ref, dict) else ref)
            for ref in refs
            if str(ref.get("docId") if isinstance(ref, dict) else ref).isdigit()
        ]
        return {
            "topic": memory.topic,
            "summary": (memory.summary or "")[:300],
            "instruments": list(memory.instruments or []),
            "confidence": memory.confidence or "medium",
            "evidenceDocIds": doc_ids[:8],
        }

    for memory in session.scalars(
        select(LongTermMemory)
        .where(LongTermMemory.retired_at.is_(None))
        .order_by(desc(LongTermMemory.compressed_at))
    ).all():
        topic = memory.topic or ""
        if topic.startswith(("ops-", "run:")):
            continue
        if matches(memory.instruments):
            candidates.append(candidate(memory))
            if len(candidates) >= limit:
                return candidates

    # Discipline/strategy topics bind regardless of instrument.
    if len(candidates) < limit:
        for memory in session.scalars(
            select(LongTermMemory)
            .where(LongTermMemory.retired_at.is_(None))
            .order_by(desc(LongTermMemory.compressed_at))
        ).all():
            topic = memory.topic or ""
            if topic.startswith(("ops-", "run:")) or (memory.instruments or []):
                continue
            if any(key in topic.lower() for key in ("discipline", "strategy", "risk", "rule")):
                candidates.append(candidate(memory))
                if len(candidates) >= limit:
                    return candidates

    # Freshest decisions/trades that compaction has not summarised yet.
    for doc in session.scalars(
        select(MemoryDocument)
        .where(MemoryDocument.source_type.in_(["decision", "trade", "transaction"]))
        .order_by(desc(MemoryDocument.occurred_at), desc(MemoryDocument.id))
        .limit(300)
    ).all():
        if matches(doc.instruments):
            candidates.append(
                {
                    "topic": f"{doc.source_type}:{','.join(doc.instruments or ['general'])}",
                    "summary": (doc.body or "")[:300],
                    "instruments": list(doc.instruments or []),
                    "confidence": "high",
                    "evidenceDocIds": [doc.id],
                }
            )
            if len(candidates) >= limit:
                break
    return candidates


def cmd_analysis_prepare(
    session: Session, market: str, refresh: Optional[bool] = None
) -> dict:
    from db.repository import create_job_run

    market_db = normalize_market_db(market)
    market_label = "crypto" if market_db == "CRYPTO" else market.lower()
    kind = f"after-market-{market_label}"
    running = session.scalars(
        select(JobRun).where(JobRun.job_id == kind, JobRun.status == "running")
    ).first()
    if running is not None:
        raise KernelError(
            "DEBRIEF_JOB_ALREADY_RUNNING",
            f"job {running.id} ({KIND_LABELS.get(kind, kind)}) is already running",
        )
    run = create_job_run(session, kind, KIND_LABELS.get(kind, kind))

    from db.models import Holding
    from db.repository import get_recent_news

    # Refresh quotes for this market's holdings + watchlist before quoting.
    refresh_meta = {"pricesRefreshed": False}
    if refresh is not False:
        from debrief.kernel import _refresh_meta

        targets = {
            (market_db, holding.ticker.upper())
            for holding in session.scalars(
                select(Holding).where(Holding.status == "open", Holding.market == market_db)
            ).all()
        }
        targets |= {
            (market_db, item.ticker.upper())
            for item in session.scalars(
                select(WatchlistItem).where(
                    WatchlistItem.status != "archived", WatchlistItem.market == market_db
                )
            ).all()
        }
        refresh_meta = _refresh_meta(refresh, session, targets)

    quotes = []
    seen = set()
    for holding in session.scalars(
        select(Holding).where(Holding.status == "open", Holding.market == market_db)
    ).all():
        from debrief.kernel import _two_closes

        last, prev = _two_closes(session, holding.ticker, market_db)
        if holding.ticker in seen:
            continue
        seen.add(holding.ticker)
        quotes.append(
            {
                "symbol": holding.ticker,
                "name": holding.name or holding.ticker,
                "price": round(last, 4) if last is not None else None,
                "changePct": round((last - prev) / prev * 100, 2) if last and prev else None,
            }
        )
    for item in session.scalars(
        select(WatchlistItem).where(WatchlistItem.status != "archived", WatchlistItem.market == market_db)
    ).all():
        if item.ticker in seen or len(quotes) >= 12:
            break
        from debrief.kernel import _two_closes

        last, prev = _two_closes(session, item.ticker, market_db)
        seen.add(item.ticker)
        quotes.append(
            {
                "symbol": item.ticker,
                "name": item.name or item.ticker,
                "price": round(last, 4) if last is not None else None,
                "changePct": round((last - prev) / prev * 100, 2) if last and prev else None,
            }
        )

    news = _scope_news(session, market_db, limit=12)
    candidates = _memory_candidates(session, set(seen), market_db)

    label = MARKET_LABELS.get(market_to_output(market_db), market_db)
    guidance = (
        f"基于以上 {label} 行情、新闻与记忆候选，输出结构化盘后结论：一句话总结 / 关键变化 / 组合影响 / 是否触发操作信号（不写库，只呈现）。"
    )
    return {
        "market": market_label,
        "preparedAt": display_now(),
        "jobId": run.id,
        "inputs": {"quotes": quotes, "news": news, "memoryCandidates": candidates},
        "guidance": guidance,
        **refresh_meta,
    }


# ── job ────────────────────────────────────────────────────────────────────


def _job_dict(run: JobRun) -> dict:
    duration = None
    if run.started_at and run.ended_at:
        duration = int((run.ended_at - run.started_at).total_seconds())
    item = {
        "id": run.id,
        "kind": run.job_name or run.job_id,
        "at": _fmt_time(run.started_at),
        "status": DISPLAY_STATUS.get(run.status, run.status),
        "durationSec": duration,
    }
    if run.error_code:
        item["errorCode"] = run.error_code
    return item


def cmd_job_list(
    session: Session,
    limit: int,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> dict:
    limit = max(1, min(limit, 100))
    query = session.query(JobRun).order_by(desc(JobRun.started_at), desc(JobRun.id))
    if since is not None:
        query = query.filter(JobRun.started_at >= since)
    if until is not None:
        query = query.filter(JobRun.started_at < until)
    rows = query.limit(limit).all()
    return {"items": [_job_dict(run) for run in rows]}


def cmd_job_start(session: Session, kind: str) -> dict:
    from db.repository import create_job_run

    kind = (kind or "").strip()
    if not kind:
        raise KernelError("DEBRIEF_ARGS", "--kind is required")
    run = create_job_run(session, kind, KIND_LABELS.get(kind, kind), status="running")
    return {"id": run.id, "status": "running"}


def cmd_job_status(session: Session, run_id: int) -> dict:
    run = session.get(JobRun, run_id)
    if run is None:
        raise KernelError("DEBRIEF_NOT_FOUND", f"job run '{run_id}' not found")
    item = _job_dict(run)
    return {"id": item["id"], "kind": item["kind"], "status": item["status"], "durationSec": item["durationSec"], **({"errorCode": item["errorCode"]} if "errorCode" in item else {})}


def cmd_job_finish(
    session: Session, run_id: int, status: str, error_code: Optional[str]
) -> dict:
    from db.repository import finish_job_run

    if status not in ("done", "failed"):
        raise KernelError("DEBRIEF_USAGE", "--status must be 'done' or 'failed'")
    run = session.get(JobRun, run_id)
    if run is None:
        raise KernelError("DEBRIEF_NOT_FOUND", f"job run '{run_id}' not found")
    if run.status not in ("running",):
        # Idempotent: finishing an already-terminal run reports its state.
        return {"id": run.id, "status": DISPLAY_STATUS.get(run.status, run.status)}
    internal = "succeeded" if status == "done" else "failed"
    finish_job_run(
        session,
        run_id,
        internal,
        details=None,
        error_code=error_code if internal == "failed" else None,
    )
    return {"id": run.id, "status": internal}


# ── v2 write commands (holdings / watchlist add|update|remove) ─────────────


def _number(value, key: str, *, minimum: float, allow_zero: bool = False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KernelError("DEBRIEF_VALIDATION", f"{key} must be a number")
    if value < minimum or (not allow_zero and value == minimum):
        suffix = f"> {minimum}" if not allow_zero else f">= {minimum}"
        raise KernelError("DEBRIEF_VALIDATION", f"{key} must be {suffix}")
    return float(value)


def _market_symbol(payload: dict) -> tuple[str, str]:
    from debrief.context import normalize_market_db

    market_db = normalize_market_db(require_string(payload, "market") or "")
    symbol = (require_string(payload, "symbol") or "").upper()
    return market_db, symbol


def _resolve_holding(session: Session, payload: dict):
    from db.models import Holding

    raw_id = payload.get("id")
    if raw_id is not None:
        if isinstance(raw_id, bool) or not isinstance(raw_id, (int, float)) or not str(raw_id).isdigit():
            raise KernelError("DEBRIEF_VALIDATION", "id must be an integer")
        holding = session.get(Holding, int(raw_id))
        if holding is not None and holding.status == "archived":
            holding = None
    else:
        market_db, symbol = _market_symbol(payload)
        holding = (
            session.query(Holding)
            .filter(
                Holding.market == market_db,
                Holding.ticker == symbol,
                Holding.status != "archived",
            )
            .first()
        )
    if holding is None:
        raise KernelError("DEBRIEF_NOT_FOUND", "holding not found")
    return holding


def _resolve_watchlist(session: Session, payload: dict):
    raw_id = payload.get("id")
    if raw_id is not None:
        if isinstance(raw_id, bool) or not isinstance(raw_id, (int, float)) or not str(raw_id).isdigit():
            raise KernelError("DEBRIEF_VALIDATION", "id must be an integer")
        item = session.get(WatchlistItem, int(raw_id))
        if item is not None and item.status == "archived":
            item = None
    else:
        market_db, symbol = _market_symbol(payload)
        item = (
            session.query(WatchlistItem)
            .filter(
                WatchlistItem.market == market_db,
                WatchlistItem.ticker == symbol,
                WatchlistItem.status != "archived",
            )
            .first()
        )
    if item is None:
        raise KernelError("DEBRIEF_NOT_FOUND", "watchlist item not found")
    return item


def cmd_holdings_add(session: Session, payload: dict) -> dict:
    from db.models import Holding
    from db.repository import record_user_action

    market_db, symbol = _market_symbol(payload)
    quantity = _number(payload.get("quantity"), "quantity", minimum=0)
    cost = _number(payload.get("cost"), "cost", minimum=0, allow_zero=True)
    name = payload.get("name")
    if name is not None and not isinstance(name, str):
        raise KernelError("DEBRIEF_VALIDATION", "name must be a string")

    existing = (
        session.query(Holding)
        .filter(
            Holding.market == market_db,
            Holding.ticker == symbol,
            Holding.status != "archived",
        )
        .first()
    )
    # A fully closed position (shares 0) is not a duplicate: adding it again is
    # a re-buy, so the same record is re-opened instead of returning a conflict.
    reopen = False
    if existing is not None:
        closed = existing.status == "closed" or float(existing.shares or 0) <= 0
        if not closed:
            raise KernelError(
                "DEBRIEF_CONFLICT",
                f"holding {market_to_output(market_db)}:{symbol} already exists (id {existing.id})",
            )
        reopen = True

    catalog_hit = catalog.lookup_exact(session, market_to_output(market_db), symbol)
    resolved_name = (name or "").strip() or None
    if resolved_name is None and catalog_hit:
        resolved_name = catalog_hit["name"]
    if resolved_name is None and reopen:
        resolved_name = (existing.name or "").strip() or None
    if not resolved_name:
        raise KernelError(
            "DEBRIEF_VALIDATION",
            "name is required when the symbol is not in the instrument catalog",
        )

    if reopen:
        holding = existing
        holding.shares = quantity
        holding.cost_basis = cost
        holding.name = resolved_name
        holding.updated_at = _now()
        if quantity > 0:
            holding.status = "open"
        session.flush()
    else:
        holding = Holding(
            ticker=symbol,
            name=resolved_name,
            market=market_db,
            shares=quantity,
            cost_basis=cost,
            position_type="core",
            status="open",
        )
        session.add(holding)
        session.flush()
    if quantity > 0:
        session.add(
            Transaction(
                holding_id=holding.id,
                action="buy",
                shares=quantity,
                price=cost if cost > 0 else 0.0,
                notes="reopen" if reopen else "opening",
                date=_now(),
            )
        )
    audit_payload = dict(payload)
    if catalog_hit:
        audit_payload["catalogCurrency"] = catalog_hit.get("currency")
    record_user_action(
        session,
        "holding.add",
        target_type="holding",
        target_id=str(holding.id),
        notes=f"{'reopen' if reopen else 'add'} {market_to_output(market_db)}:{symbol}",
        payload=audit_payload,
    )
    return {
        "id": holding.id,
        "market": market_to_output(market_db),
        "symbol": symbol,
        "name": resolved_name,
        "quantity": quantity,
        "cost": cost,
    }


def cmd_holdings_update(session: Session, payload: dict) -> dict:
    from db.repository import record_user_action

    holding = _resolve_holding(session, payload)
    quantity = payload.get("quantity")
    cost = payload.get("cost")
    if quantity is None and cost is None:
        raise UsageError("at least one of quantity, cost is required")
    if quantity is not None:
        quantity = _number(quantity, "quantity", minimum=0)
        holding.shares = quantity
    if cost is not None:
        cost = _number(cost, "cost", minimum=0, allow_zero=True)
        holding.cost_basis = cost
    holding.updated_at = _now()
    record_user_action(
        session,
        "holding.update",
        target_type="holding",
        target_id=str(holding.id),
        notes=f"update {market_to_output(holding.market)}:{holding.ticker}",
        payload=dict(payload),
    )
    return {"id": holding.id, "status": "updated"}


def cmd_holdings_remove(session: Session, payload: dict) -> dict:
    from db.repository import record_user_action

    holding = _resolve_holding(session, payload)
    holding.status = "archived"
    holding.updated_at = _now()
    record_user_action(
        session,
        "holding.remove",
        target_type="holding",
        target_id=str(holding.id),
        notes=f"remove {market_to_output(holding.market)}:{holding.ticker}",
        payload=dict(payload),
    )
    return {"id": holding.id, "status": "removed"}


def cmd_watchlist_add(session: Session, payload: dict) -> dict:
    from db.repository import record_user_action

    market_db, symbol = _market_symbol(payload)
    name = payload.get("name")
    if name is not None and not isinstance(name, str):
        raise KernelError("DEBRIEF_VALIDATION", "name must be a string")

    target = payload.get("targetPrice")
    if target is not None:
        target = _number(target, "targetPrice", minimum=0, allow_zero=True)
    alert = payload.get("alert", True)
    if not isinstance(alert, bool):
        raise KernelError("DEBRIEF_VALIDATION", "alert must be a boolean")

    existing = (
        session.query(WatchlistItem)
        .filter(
            WatchlistItem.market == market_db,
            WatchlistItem.ticker == symbol,
            WatchlistItem.status != "archived",
        )
        .first()
    )
    if existing is not None:
        raise KernelError(
            "DEBRIEF_CONFLICT",
            f"watchlist item {market_to_output(market_db)}:{symbol} already exists (id {existing.id})",
        )

    catalog_hit = catalog.lookup_exact(session, market_to_output(market_db), symbol)
    resolved_name = (name or "").strip() or (catalog_hit["name"] if catalog_hit else None)

    item = WatchlistItem(
        ticker=symbol,
        name=resolved_name,
        market=market_db,
        target_price_low=target,
        status="watching",
        priority="medium",
        alert_enabled=1 if alert else 0,
    )
    session.add(item)
    session.flush()
    audit_payload = dict(payload)
    if catalog_hit:
        audit_payload["catalogCurrency"] = catalog_hit.get("currency")
    record_user_action(
        session,
        "watchlist.add",
        target_type="watchlist",
        target_id=str(item.id),
        notes=f"add {market_to_output(market_db)}:{symbol}",
        payload=audit_payload,
    )
    return {
        "id": item.id,
        "market": market_to_output(market_db),
        "symbol": symbol,
        "name": resolved_name or symbol,
        "targetPrice": target,
        "alert": bool(alert),
    }


def cmd_watchlist_update(session: Session, payload: dict) -> dict:
    from db.repository import record_user_action

    item = _resolve_watchlist(session, payload)
    has_target = "targetPrice" in payload
    has_alert = "alert" in payload
    if not has_target and not has_alert:
        raise UsageError("at least one of targetPrice, alert is required")
    if has_target:
        target = payload.get("targetPrice")
        if target is not None:
            target = _number(target, "targetPrice", minimum=0, allow_zero=True)
        item.target_price_low = target
    if has_alert:
        alert = payload.get("alert")
        if not isinstance(alert, bool):
            raise KernelError("DEBRIEF_VALIDATION", "alert must be a boolean")
        item.alert_enabled = 1 if alert else 0
    item.updated_at = _now()
    record_user_action(
        session,
        "watchlist.update",
        target_type="watchlist",
        target_id=str(item.id),
        notes=f"update {market_to_output(item.market)}:{item.ticker}",
        payload=dict(payload),
    )
    return {"id": item.id, "status": "updated"}


def cmd_watchlist_remove(session: Session, payload: dict) -> dict:
    from db.repository import record_user_action

    item = _resolve_watchlist(session, payload)
    item.status = "archived"
    item.updated_at = _now()
    record_user_action(
        session,
        "watchlist.remove",
        target_type="watchlist",
        target_id=str(item.id),
        notes=f"remove {market_to_output(item.market)}:{item.ticker}",
        payload=dict(payload),
    )
    return {"id": item.id, "status": "removed"}


# ── migrate ────────────────────────────────────────────────────────────────


def cmd_migrate(engine) -> dict:
    from db.migrate import MIGRATIONS
    from db.migrate import migrate as run_migrations
    from db.models import Base

    Base.metadata.create_all(engine)

    def applied_versions():
        with engine.connect() as conn:
            has_table = conn.execute(
                text("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='_migrations'")
            ).scalar()
            if not has_table:
                return set()
            return {
                row[0]
                for row in conn.execute(text("SELECT version FROM _migrations")).fetchall()
            }

    before = applied_versions()
    run_migrations(engine)
    after = applied_versions()
    return {
        "db": str(engine.url),
        "applied": sorted(after - before),
        "totalMigrations": len(MIGRATIONS),
    }
