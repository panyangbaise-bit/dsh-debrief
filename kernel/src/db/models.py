from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow():
    """Return current UTC datetime. Lambdas aren't pickleable, use a helper."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Holding(Base):
    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    cost_basis: Mapped[float] = mapped_column(Float, nullable=False)
    position_type: Mapped[str] = mapped_column(String(20), nullable=False, default="core")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    transactions = relationship("Transaction", back_populates="holding")

    def __repr__(self):
        return f"<Holding(id={self.id}, ticker='{self.ticker}')>"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    holding_id: Mapped[int] = mapped_column(ForeignKey("holdings.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    holding = relationship("Holding", back_populates="transactions")

    def __repr__(self):
        return f"<Transaction(id={self.id}, action='{self.action}')>"


class PriceCache(Base):
    __tablename__ = "price_cache"
    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_price_cache_ticker_date"),
        Index("ix_price_cache_ticker_date", "ticker", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    open_price: Mapped[Optional[float]] = mapped_column("open", Float, nullable=True)
    high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self):
        return f"<PriceCache(ticker='{self.ticker}', date={self.date})>"


class NewsArticle(Base):
    __tablename__ = "news_articles"
    __table_args__ = (Index("ix_news_ticker_published", "ticker", "published_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    headline: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="wallstreetcn")
    url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    relevance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    def __repr__(self):
        return f"<NewsArticle(id={self.id}, headline='{self.headline[:40]}...')>"


class FinancialReport(Base):
    """Company financial statements (revenue/eps), kept separate from analysis reports."""

    __tablename__ = "financial_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    report_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    report_type: Mapped[str] = mapped_column(String(20), nullable=False)
    revenue: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    eps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    key_metrics: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    def __repr__(self):
        return f"<FinancialReport(ticker='{self.ticker}', report_date={self.report_date})>"


class AnalysisReport(Base):
    """Debrief 运行中心报告（盘后分析等）——报告是产出，不是 trace。

    Reports are written by the DSH agent through `debrief report create` and
    read back through `debrief report latest|--id`. Charts live in
    ``analysis_charts`` (``chart_id`` link).
    """

    __tablename__ = "analysis_reports"
    __table_args__ = (Index("ix_analysis_reports_market_time", "market", "generated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    full_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metrics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    chart_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    job_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("job_runs.id"), nullable=True, index=True
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    def __repr__(self):
        return f"<AnalysisReport(id={self.id!r}, market='{self.market}')>"


class AnalysisChart(Base):
    """Immutable report figure (SVG/data payload), linked to an analysis report."""

    __tablename__ = "analysis_charts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    report_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class JobRun(Base):
    """Durable outcome record for every scheduler/kernel invocation.

    ``error_code`` carries a stable DEBRIEF_* code; ``report_id`` links the
    produced analysis report when a run finishes with one.
    """

    __tablename__ = "job_runs"
    __table_args__ = (Index("ix_job_runs_job_started", "job_id", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(String(40), nullable=False)
    job_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    report_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self):
        return f"<JobRun(id={self.id}, job_id='{self.job_id}', status='{self.status}')>"


class WatchlistItem(Base):
    """Watchlist — stocks the user is monitoring before deciding to enter."""

    __tablename__ = "watchlist_items"
    __table_args__ = (
        Index("ix_watchlist_status", "status"),
        Index("ix_watchlist_ticker", "ticker"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    watch_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_price_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_price_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="watching")
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="medium")
    alert_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    def __repr__(self):
        return f"<WatchlistItem(id={self.id}, ticker='{self.ticker}', status='{self.status}')>"


class UserAction(Base):
    """Business audit trail (permanent retention).

    Schema was rebuilt during migration ``v10_debrief_drop_trace``: the old
    ``recommendation_id`` foreign key into the dropped trace tables became a
    plain legacy integer column, and generic ``target_type``/``target_id``
    columns carry the affected kernel object (report / memory document / job /
    holding / watchlist item). ``payload`` (v13) stores the full request JSON
    of white-list writes.
    """

    __tablename__ = "user_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    acted_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    def __repr__(self):
        return f"<UserAction(id={self.id}, action='{self.action}')>"


class TradingDiscipline(Base):
    """Shared dashboard memo, persisted as a single document."""

    __tablename__ = "trading_discipline"

    id: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class MemoryDocument(Base):
    """Immutable source snapshot and transactional indexing outbox.

    Content/metadata never change. Only processing state may change. A source
    can have many versions; IDs also serve as stable evidence references.
    ``archived_into``/``archived_at`` mark documents compressed into a
    long-term memory (design §3.2): they stay indexed but leave the short-term
    retrieval window.
    """

    __tablename__ = "memory_documents"
    __table_args__ = (Index("ix_memory_source", "source_type", "source_id", "id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[int] = mapped_column()
    operation: Mapped[str] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[dict] = mapped_column(JSON)
    previous: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    instruments: Mapped[list] = mapped_column(JSON, default=list)
    relations: Mapped[list] = mapped_column(JSON, default=list)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    known_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    time_quality: Mapped[str] = mapped_column(String(20), default="recorded")
    content_hash: Mapped[str] = mapped_column(String(64))
    indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    vector_profile: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    archived_into: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class MemoryChunk(Base):
    __tablename__ = "memory_chunks"
    __table_args__ = (UniqueConstraint("document_id", "ordinal"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("memory_documents.id"), index=True)
    ordinal: Mapped[int] = mapped_column()
    body: Mapped[str] = mapped_column(Text)


class MemoryEmbedding(Base):
    """Reusable embedding cache across retries and identical source chunks."""

    __tablename__ = "memory_embeddings"
    profile: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    vector: Mapped[list] = mapped_column(JSON)


class MemoryCheckpoint(Base):
    __tablename__ = "memory_checkpoints"
    source_type: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_id: Mapped[int] = mapped_column(default=0)


class LongTermMemory(Base):
    """Compressed long-term investment memory (design §3.2).

    One row per topic; re-compaction increments ``version`` and merges the
    new summary. ``evidence_refs`` cites short-term document ids.
    """

    __tablename__ = "long_term_memories"
    __table_args__ = (UniqueConstraint("topic", name="uq_ltm_topic"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    instruments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    time_range: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    caveats: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    compressed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    embedding_profile: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self):
        return f"<LongTermMemory(id={self.id}, topic='{self.topic}', v{self.version})>"


class MemoryCompactionRun(Base):
    """Compaction outbox state machine: pending → running → done/failed (+retry)."""

    __tablename__ = "memory_compaction_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    doc_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    result_memory_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self):
        return f"<MemoryCompactionRun(id={self.id}, topic='{self.topic}', status='{self.status}')>"


class MemoryProfile(Base):
    """Single-row digest of the whole investment memory (plan/kernel.md §1).

    ``sections`` is the only authoritative content — six canonical sections
    stored as ``[{key, content, updatedBy, updatedAt}]``. ``markdown`` is a
    deterministic render cache derived by the kernel at write time; external
    markdown/title input is rejected. ``version`` starts at 0 (= never
    generated) and bumps once per non-noop write. This table is deliberately
    absent from memory/capture.py SOURCE_TYPES: the profile is a projection
    of memory, not a memory event, so writing it never mints a document.
    """

    __tablename__ = "memory_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    sections: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_by: Mapped[str] = mapped_column(String(10), nullable=False, default="system")
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class InstrumentCatalog(Base):
    """Local instrument directory synced daily (akshare lists + CoinGecko)."""

    __tablename__ = "instrument_catalog"
    # asset_class is part of the key: 000001 is both 平安银行 (stock) and
    # 华夏成长混合 (open-end fund), and both must stay addressable.
    __table_args__ = (
        UniqueConstraint("market", "symbol", "asset_class", name="uq_catalog_market_symbol_class"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    asset_class: Mapped[str] = mapped_column(String(20), nullable=False, default="stock")
    pinyin_alias: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    def __repr__(self):
        return f"<InstrumentCatalog(market='{self.market}', symbol='{self.symbol}')>"


# Install once for every ORM write path, including UI and kernel CLI writes.
from memory.capture import install_capture  # noqa: E402 — register after models exist

install_capture()
