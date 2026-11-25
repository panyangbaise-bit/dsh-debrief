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
    Holding,
    JobRun,
    LongTermMemory,
    MemoryChunk,
    MemoryCompactionRun,
    MemoryDocument,
    MemoryProfile,
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

# A "running" after-market job older than this is presumed orphaned (its agent
# session died before writing the report) and is auto-failed on the next
# prepare instead of blocking the market forever.
AFTER_MARKET_STALE_MINUTES = int(os.environ.get("AFTER_MARKET_STALE_MINUTES", "90"))

# When a market has no open holdings and no watchlist entries, the after-market
# package falls back to quoting these benchmark tickers so the report carries
# real market data instead of an empty quotes list (which read like a failed
# quote fetch). Tickers must exist in the market adapter's catalog.
MARKET_BENCHMARK_TICKERS = {
    "CRYPTO": ("BTC", "ETH"),
}
BENCHMARK_NAMES = {"BTC": "比特币", "ETH": "以太坊"}

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


def cmd_notify_send(payload: dict) -> dict:
    """Send an agent-composed Telegram message (digest/alert).

    Payload: {"text": "..."} — markdown bold/lists/links are converted to
    Telegram HTML by notifier.notify(); long messages are split safely.
    """
    from notifier.telegram import is_configured, notify

    text = (payload or {}).get("text")
    if not isinstance(text, str) or not text.strip():
        raise KernelError(
            "DEBRIEF_ARGS",
            'notify send 需要非空 text 字段（payload: {"text": "..."}）',
        )
    if not is_configured():
        raise KernelError(
            "DEBRIEF_TELEGRAM_UNCONFIGURED",
            "未配置 Telegram：请设置 TELEGRAM_BOT_TOKEN 与 TELEGRAM_CHAT_ID"
            "（插件 Config.telegram.botToken/chatId 或内核环境变量）",
        )
    return {"sent": bool(notify(text))}


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


def cmd_memory_list(session: Session, include_retired: bool = False, limit: int = 100) -> dict:
    """Management listing for the memory page: everything the model may edit.

    Unlike the retrieval paths, this surfaces `ops-*` topics too — the page is
    where the user retires or deletes them.
    """
    limit = max(1, min(limit, 200))
    query = session.query(LongTermMemory).order_by(desc(LongTermMemory.compressed_at), desc(LongTermMemory.id))
    if not include_retired:
        query = query.filter(LongTermMemory.retired_at.is_(None))
    rows = query.limit(limit).all()
    return {
        "items": [
            {
                "id": memory.id,
                "topic": memory.topic,
                "instruments": list(memory.instruments or []),
                "summary": memory.summary,
                "confidence": memory.confidence or "medium",
                "version": memory.version or 1,
                "compressedAt": _fmt_window(memory.compressed_at),
                "retiredAt": _fmt_window(memory.retired_at) if memory.retired_at else None,
            }
            for memory in rows
        ],
        "count": len(rows),
    }


def cmd_memory_update(session: Session, payload: dict) -> dict:
    """Edit a topic in place (summary/confidence/caveats) or restore a retired one.

    Version bumps and `compressed_at` refreshes so re-compaction keeps working.
    """
    from db.repository import record_user_action

    topic = require_string(payload, "topic") or ""
    memory = session.scalars(select(LongTermMemory).where(LongTermMemory.topic == topic)).first()
    if memory is None:
        raise KernelError("DEBRIEF_NOT_FOUND", f"long-term memory '{topic}' not found")
    if payload.get("restore"):
        if memory.retired_at is None:
            raise KernelError("DEBRIEF_CONFLICT", f"memory '{topic}' is not retired")
        memory.retired_at = None
        memory.compressed_at = _now()
        record_user_action(
            session, "memory.restore", target_type="long_term_memory",
            target_id=str(memory.id), notes=topic,
        )
        session.commit()
        return {"id": memory.id, "version": memory.version, "restored": True}
    summary = payload.get("summary")
    confidence = payload.get("confidence")
    caveats = payload.get("caveats")
    if summary is None and confidence is None and caveats is None:
        raise KernelError("DEBRIEF_VALIDATION", "at least one of summary, confidence, caveats is required")
    if summary is not None:
        if not isinstance(summary, str) or not summary.strip():
            raise KernelError("DEBRIEF_VALIDATION", "summary must be a non-empty string")
        memory.summary = summary.strip()
    if confidence is not None:
        if confidence not in ("high", "medium", "low"):
            raise KernelError("DEBRIEF_VALIDATION", "confidence must be high|medium|low")
        memory.confidence = confidence
    if caveats is not None:
        if not isinstance(caveats, str):
            raise KernelError("DEBRIEF_VALIDATION", "caveats must be a string")
        memory.caveats = caveats
    memory.version = (memory.version or 1) + 1
    memory.compressed_at = _now()
    record_user_action(
        session, "memory.update", target_type="long_term_memory",
        target_id=str(memory.id), notes=topic,
    )
    session.commit()
    return {"id": memory.id, "version": memory.version}


def cmd_memory_remove(session: Session, payload: dict) -> dict:
    """Hard-delete one topic (explicit user action, audited; evidence docs stay)."""
    from db.repository import record_user_action

    topic = require_string(payload, "topic") or ""
    memory = session.scalars(select(LongTermMemory).where(LongTermMemory.topic == topic)).first()
    if memory is None:
        raise KernelError("DEBRIEF_NOT_FOUND", f"long-term memory '{topic}' not found")
    memory_id, version = memory.id, memory.version
    session.delete(memory)
    record_user_action(
        session, "memory.remove", target_type="long_term_memory",
        target_id=str(memory_id), notes=topic,
    )
    session.commit()
    return {"id": memory_id, "version": version, "removed": True}


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
    # are offered for retirement; retiring a topic hard-deletes it (see
    # cmd_memory_compact_write), so the list never re-offers the same topic.
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
        memory_id, version = memory.id, memory.version
        # Hard delete: retired topics are removed outright (same semantics as
        # `memory remove`; evidence documents stay, dangling archived_into is
        # accepted by the candidate filter). Nothing soft-archived remains.
        session.delete(memory)
        record_user_action(
            session,
            "memory.retire",
            target_type="long_term_memory",
            target_id=str(memory_id),
            notes=topic,
        )
        session.commit()
        return {"id": memory_id, "version": version, "retired": True, "deleted": True}
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


# ── profile (investment memory summary) ─────────────────────────────────────
# Contract: plan/kernel.md §3 + plan/README.md arbitration A1–A4.
# sections 是唯一权威内容；markdown 是内核渲染缓存；updatedBy 由调用方经
# CLI --by 派生（不信任 payload）；审计只存元数据（A3）；捕获排除见
# memory/capture.py（A4）。

PROFILE_SECTION_KEYS = (
    "portfolio",
    "habits",
    "discipline",
    "risk",
    "advice",
    "decisions",
)
PROFILE_SECTION_TITLES = {
    "portfolio": "投资组合",
    "habits": "交易习惯",
    "discipline": "纪律与规则",
    "risk": "风险画像",
    "advice": "操作建议",
    "decisions": "关键决策",
}
PROFILE_SECTION_MAX_CHARS = 2000
PROFILE_TOTAL_MAX_CHARS = 8000
PROFILE_EVIDENCE_REFS_MAX = 64
PROFILE_LTM_LIMIT = 40
PROFILE_DECISIONS_LIMIT = 10
PROFILE_TXN_LIMIT = 20


def _render_profile_markdown(sections: list[dict]) -> str:
    """Deterministic display cache derived from sections (sections authoritative)."""
    by_key = {s.get("key"): s for s in sections}
    parts = []
    for key in PROFILE_SECTION_KEYS:
        content = (by_key.get(key) or {}).get("content") or ""
        parts.append(f"## {PROFILE_SECTION_TITLES[key]}\n\n{content}")
    return "\n\n".join(parts)


def _profile_sections_dto(by_key: dict) -> list[dict]:
    """Six canonical sections in fixed order; missing keys pad to empty."""
    items = []
    for key in PROFILE_SECTION_KEYS:
        stored = by_key.get(key) or {}
        items.append(
            {
                "key": key,
                "title": PROFILE_SECTION_TITLES[key],
                "content": stored.get("content") or "",
                "updatedBy": stored.get("updatedBy"),
                "updatedAt": stored.get("updatedAt"),
            }
        )
    return items


def _profile_evidence_package(session: Session) -> dict:
    """Closed evidence bundle for regeneration (plan/README.md A2).

    Only this bundle may feed `profile` regeneration; `memory search` stays
    reserved for the Q&A mode. Composition: active long-term topics
    (ops-/run: noise excluded), the trading_discipline original text,
    a holdings + recent-transactions structure snapshot, and the freshest
    non-feedback/run decision documents.
    """
    from db.repository import get_trading_discipline

    long_term = []
    for memory in session.scalars(
        select(LongTermMemory)
        .where(LongTermMemory.retired_at.is_(None))
        .order_by(desc(LongTermMemory.compressed_at), desc(LongTermMemory.id))
        .limit(PROFILE_LTM_LIMIT)
    ).all():
        topic = memory.topic or ""
        if topic.startswith(("ops-", "run:")):
            continue
        long_term.append(
            {
                "topic": topic,
                "summary": (memory.summary or "")[:400],
                "confidence": memory.confidence or "medium",
                "instruments": list(memory.instruments or []),
                "compressedAt": _fmt_window(memory.compressed_at),
            }
        )

    holdings = [
        {
            "market": market_to_output(h.market),
            "symbol": h.ticker,
            "name": h.name or h.ticker,
            "quantity": h.shares,
            "cost": h.cost_basis,
            "status": h.status,
        }
        for h in session.scalars(
            select(Holding)
            .where(Holding.status == "open")
            .order_by(Holding.market, Holding.ticker)
        ).all()
    ]

    recent_transactions = []
    for txn, holding in session.execute(
        select(Transaction, Holding)
        .join(Holding, Transaction.holding_id == Holding.id)
        .where(Holding.status != "archived")
        .order_by(desc(Transaction.date), desc(Transaction.id))
        .limit(PROFILE_TXN_LIMIT)
    ).all():
        recent_transactions.append(
            {
                "market": market_to_output(holding.market),
                "symbol": holding.ticker,
                "action": txn.action,
                "quantity": txn.shares,
                "price": txn.price,
                "date": _fmt_date(txn.date),
                "notes": txn.notes,
            }
        )

    recent_decisions = []
    for doc in session.scalars(
        select(MemoryDocument)
        .where(
            MemoryDocument.source_type.in_(["decision", "trade"]),
            MemoryDocument.archived_into.is_(None),
        )
        .order_by(desc(MemoryDocument.occurred_at), desc(MemoryDocument.id))
        .limit(PROFILE_DECISIONS_LIMIT)
    ).all():
        instruments = [
            market_to_output(i.split(":")[0]) + ":" + i.split(":", 1)[-1]
            if ":" in (i or "")
            else i
            for i in (doc.instruments or [])
        ]
        recent_decisions.append(
            {
                "docId": doc.id,
                "title": doc.title,
                "body": (doc.body or "")[:800],
                "occurredAt": _fmt_date(doc.occurred_at),
                "instruments": instruments,
                "sourceType": doc.source_type,
            }
        )

    discipline = get_trading_discipline(session)
    return {
        "longTerm": long_term,
        "discipline": (
            {"content": discipline.content, "updatedAt": _fmt_window(discipline.updated_at)}
            if discipline
            else None
        ),
        "portfolio": {
            "holdings": holdings,
            "recentTransactions": recent_transactions,
        },
        "recentDecisions": recent_decisions,
    }


def _profile_read_row(session: Session) -> Optional[MemoryProfile]:
    row = session.get(MemoryProfile, 1)
    if row is None:
        return None
    if not isinstance(row.sections, list) or not isinstance(row.evidence_refs, list):
        raise KernelError("DEBRIEF_INTERNAL", "memory_profile JSON columns are corrupted")
    return row


def cmd_profile_get(session: Session) -> dict:
    """Read the six-section profile plus the closed evidence bundle.

    Never DEBRIEF_NOT_FOUND: a missing row degrades to an empty profile
    (version=0, generated=false); the evidence bundle is still assembled so a
    first regeneration has everything it needs.
    """
    row = _profile_read_row(session)
    evidence = _profile_evidence_package(session)
    if row is None:
        return {
            "version": 0,
            "generated": False,
            "updatedAt": "",
            "updatedBy": "system",
            "sections": _profile_sections_dto({}),
            "markdown": "",
            "evidenceRefs": [],
            "discipline": evidence["discipline"],
            "evidence": evidence,
        }
    by_key = {s.get("key"): s for s in row.sections if isinstance(s, dict)}
    return {
        "version": row.version or 0,
        "generated": bool(row.version),
        "updatedAt": _fmt_window(row.updated_at),
        "updatedBy": row.updated_by or "system",
        "sections": _profile_sections_dto(by_key),
        "markdown": row.markdown or "",
        "evidenceRefs": row.evidence_refs,
        "discipline": evidence["discipline"],
        "evidence": evidence,
    }


def cmd_profile_write(session: Session, payload: dict, by: str) -> dict:
    """Partial-update write with CAS, per-section ownership and noop idempotency.

    `by` (--by user|agent) is the caller-derived writer for every section in
    this write; payloads never carry updatedBy (rejected). protectUserSections
    skips user-owned sections for agent writes. Content-identical writes are
    noops: no version bump, no audit row.
    """
    from db.repository import record_user_action

    if by not in ("user", "agent"):
        raise KernelError("DEBRIEF_VALIDATION", "updatedBy must be user|agent")

    for forbidden in ("title", "markdown", "updatedBy", "updatedAt"):
        if forbidden in payload:
            raise KernelError(
                "DEBRIEF_VALIDATION",
                f"field '{forbidden}' is not accepted; sections are the only authoritative content",
            )

    sections_in = payload.get("sections")
    refs_in = payload.get("evidenceRefs")
    if sections_in is None and refs_in is None:
        raise KernelError("DEBRIEF_VALIDATION", "at least one of sections, evidenceRefs is required")

    expected_version = payload.get("expectedVersion")
    if expected_version is not None and (
        not isinstance(expected_version, int)
        or isinstance(expected_version, bool)
        or expected_version < 0
    ):
        raise KernelError("DEBRIEF_VALIDATION", "expectedVersion must be a non-negative integer")
    protect = payload.get("protectUserSections")
    if protect is not None and not isinstance(protect, bool):
        raise KernelError("DEBRIEF_VALIDATION", "protectUserSections must be a boolean")

    # ── sections validation ──────────────────────────────────────────────
    cleaned = []
    seen_keys = set()
    if sections_in is not None:
        if not isinstance(sections_in, list) or not sections_in:
            raise KernelError("DEBRIEF_VALIDATION", "sections must be a non-empty list")
        for item in sections_in:
            if not isinstance(item, dict):
                raise KernelError("DEBRIEF_VALIDATION", "each section must be an object")
            extra = sorted(set(item) - {"key", "content"})
            if extra:
                raise KernelError(
                    "DEBRIEF_VALIDATION", f"unexpected section field: {extra[0]!r}"
                )
            key = item.get("key")
            if key not in PROFILE_SECTION_KEYS:
                raise KernelError("DEBRIEF_VALIDATION", f"unknown section key: {key!r}")
            if key in seen_keys:
                raise KernelError("DEBRIEF_VALIDATION", f"duplicate section key: {key!r}")
            seen_keys.add(key)
            content = item.get("content")
            if content is None or not isinstance(content, str):
                raise KernelError("DEBRIEF_VALIDATION", f"section '{key}' content must be a string")
            cleaned.append({"key": key, "content": content})

    # ── evidence_refs validation (docId must exist; whole-list replace) ──
    refs_cleaned = None
    if refs_in is not None:
        if not isinstance(refs_in, list):
            raise KernelError("DEBRIEF_VALIDATION", "evidenceRefs must be a list")
        if len(refs_in) > PROFILE_EVIDENCE_REFS_MAX:
            raise KernelError(
                "DEBRIEF_VALIDATION",
                f"evidenceRefs must have at most {PROFILE_EVIDENCE_REFS_MAX} entries",
            )
        refs_cleaned = []
        for ref in refs_in:
            if not isinstance(ref, dict) or "docId" not in ref:
                raise KernelError("DEBRIEF_VALIDATION", "each evidenceRef needs {docId}")
            doc_id = ref.get("docId")
            if not isinstance(doc_id, int) or isinstance(doc_id, bool) or doc_id < 1:
                raise KernelError("DEBRIEF_VALIDATION", f"invalid docId: {doc_id!r}")
            if session.get(MemoryDocument, doc_id) is None:
                raise KernelError("DEBRIEF_VALIDATION", f"evidence docId {doc_id} does not exist")
            refs_cleaned.append({"docId": doc_id})

    # ── CAS + merge under the SQLite write lock ──────────────────────────
    session.commit()  # release the validation read transaction
    session.execute(text("BEGIN IMMEDIATE"))  # serialize concurrent writers
    row = _profile_read_row(session)
    if row is None:
        row = MemoryProfile(
            id=1, sections=[], markdown="", version=0,
            updated_at=_now(), updated_by="system", evidence_refs=[],
        )
        session.add(row)
        session.flush()
    old_version = row.version or 0
    if expected_version is not None and expected_version != old_version:
        raise KernelError(
            "DEBRIEF_CONFLICT", f"profile version is {old_version}, expected {expected_version}"
        )

    stored_map = {
        s.get("key"): dict(s) for s in row.sections if isinstance(s, dict) and s.get("key")
    }
    merged = {key: dict(value) for key, value in stored_map.items()}
    truncated, preserved = [], []
    changed_keys = []
    if cleaned is not None:
        for item in cleaned:
            key = item["key"]
            content = item["content"]
            current = merged.get(key) or {}
            if protect and by == "agent" and current.get("updatedBy") == "user":
                preserved.append(key)
                continue
            if len(content) > PROFILE_SECTION_MAX_CHARS:
                if by == "user":
                    raise KernelError(
                        "DEBRIEF_VALIDATION",
                        f"section '{key}' exceeds {PROFILE_SECTION_MAX_CHARS} characters",
                    )
                content = content[:PROFILE_SECTION_MAX_CHARS]
                truncated.append(key)
            merged[key] = {
                "key": key,
                "content": content,
                "updatedBy": by,
                "updatedAt": _fmt_window(_now()),
            }
            changed_keys.append(key)

    new_sections = [merged[key] for key in PROFILE_SECTION_KEYS if key in merged]
    total_chars = sum(len(s.get("content") or "") for s in new_sections)
    if total_chars > PROFILE_TOTAL_MAX_CHARS:
        raise KernelError(
            "DEBRIEF_VALIDATION",
            f"total section content exceeds {PROFILE_TOTAL_MAX_CHARS} characters",
        )
    new_markdown = _render_profile_markdown(new_sections)

    old_refs = row.evidence_refs
    refs_changed = refs_cleaned is not None and {
        r.get("docId") for r in refs_cleaned
    } != {r.get("docId") for r in old_refs if isinstance(r, dict)}

    # Noop: identical render + identical refs → no version bump, no audit.
    if new_markdown == (row.markdown or "") and not refs_changed:
        return {
            "version": old_version,
            "updatedAt": _fmt_window(row.updated_at),
            "updatedBy": row.updated_by or "system",
            "noop": True,
            "preserved": preserved,
            "truncated": truncated,
            "sections": _profile_sections_dto(stored_map),
            "markdown": row.markdown or "",
            "evidenceRefs": old_refs,
        }

    new_version = old_version + 1
    row.sections = new_sections
    row.markdown = new_markdown
    row.version = new_version
    row.updated_at = _now()
    row.updated_by = by
    if refs_cleaned is not None:
        row.evidence_refs = refs_cleaned
    session.flush()

    # A3: audit metadata only — no section bodies in user_actions.payload.
    record_user_action(
        session,
        "profile.write",
        target_type="memory_profile",
        target_id="1",
        notes=(
            f"v{old_version}→v{new_version} sections={','.join(sorted(changed_keys)) or '-'} "
            f"by={by} preserved={','.join(preserved) or '-'} "
            f"truncated={','.join(truncated) or '-'}"
        ),
        payload={
            "version": new_version,
            "previousVersion": old_version,
            "updatedBy": by,
            "changedSections": sorted(changed_keys),
            "preservedSections": preserved,
            "truncatedSections": truncated,
            "sectionChars": {
                key: len(merged[key].get("content") or "")
                for key in PROFILE_SECTION_KEYS
                if key in merged
            },
        },
    )
    session.commit()
    return {
        "version": new_version,
        "updatedAt": _fmt_window(row.updated_at),
        "updatedBy": by,
        "noop": False,
        "preserved": preserved,
        "truncated": truncated,
        "sections": _profile_sections_dto(merged),
        "markdown": new_markdown,
        "evidenceRefs": row.evidence_refs,
    }


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
        # A crashed/aborted agent leaves its job "running" forever, which would
        # block every future prepare of this market (DEBRIEF_JOB_ALREADY_RUNNING).
        # Auto-fail runs older than the stale threshold so one dead session
        # cannot wedge the whole pipeline.
        age = _now() - running.started_at if running.started_at else timedelta(0)
        if age <= timedelta(minutes=AFTER_MARKET_STALE_MINUTES):
            raise KernelError(
                "DEBRIEF_JOB_ALREADY_RUNNING",
                f"job {running.id} ({KIND_LABELS.get(kind, kind)}) is already running",
            )
        from db.repository import finish_job_run

        finish_job_run(
            session,
            running.id,
            "failed",
            details=f"auto-failed: running for {int(age.total_seconds() // 60)}m, past the "
            f"{AFTER_MARKET_STALE_MINUTES}m stale threshold",
            error_code="DEBRIEF_JOB_STALE",
        )
        logger.warning(
            "auto-failed stale running job %s (%s) after %dm",
            running.id,
            kind,
            int(age.total_seconds() // 60),
        )
    run = create_job_run(session, kind, KIND_LABELS.get(kind, kind))

    from db.models import Holding
    from db.repository import get_recent_news

    # Quote targets: this market's open holdings + watchlist. When the market
    # has neither, fall back to benchmark tickers so the input package still
    # carries market quotes (an empty quotes list reads like a failed fetch).
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
    benchmark_tickers = []
    if not targets:
        benchmark_tickers = list(MARKET_BENCHMARK_TICKERS.get(market_db, ()))
        targets = {(market_db, ticker.upper()) for ticker in benchmark_tickers}

    refresh_meta = {"pricesRefreshed": False}
    if refresh is not False:
        from debrief.kernel import _refresh_meta

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

    # Benchmark fallback: markets without any positions/watchlist targets still
    # get real quotes (e.g. CRYPTO → BTC/ETH) instead of an empty list.
    if not quotes:
        from debrief.kernel import _two_closes

        for ticker in benchmark_tickers:
            last, prev = _two_closes(session, ticker.upper(), market_db)
            quotes.append(
                {
                    "symbol": ticker.upper(),
                    "name": BENCHMARK_NAMES.get(ticker.upper(), ticker.upper()),
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
        # A new target invalidates the old reminder state: the next hit in the
        # session should alert immediately instead of waiting out the cooldown.
        item.alert_active = 0
        item.last_alert_at = None
    if has_alert:
        alert = payload.get("alert")
        if not isinstance(alert, bool):
            raise KernelError("DEBRIEF_VALIDATION", "alert must be a boolean")
        item.alert_enabled = 1 if alert else 0
        item.alert_active = 0
        item.last_alert_at = None
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
