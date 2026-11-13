import os
from pathlib import Path

from dotenv import load_dotenv

if os.environ.get("PYTHON_DOTENV_DISABLED", "").lower() not in ("1", "true", "yes"):
    load_dotenv()

PROJECT_ROOT = Path(__file__).parent


class Config:
    # Portfolio memory: local lexical search works without external credentials.
    MEMORY_ENABLED = os.environ.get("MEMORY_ENABLED", "true").lower() in ("1", "true", "yes")
    MEMORY_VECTOR_ENABLED = os.environ.get("MEMORY_VECTOR_ENABLED", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    MEMORY_EMBEDDING_BASE_URL = os.environ.get("MEMORY_EMBEDDING_BASE_URL", "").rstrip("/")
    MEMORY_EMBEDDING_API_KEY = os.environ.get("MEMORY_EMBEDDING_API_KEY", "") or os.environ.get(
        "DASHSCOPE_API_KEY", ""
    )
    MEMORY_EMBEDDING_MODEL = os.environ.get(
        "MEMORY_EMBEDDING_MODEL", "qwen3.7-text-embedding-flash"
    )
    MEMORY_EMBEDDING_DIMENSIONS = int(os.environ.get("MEMORY_EMBEDDING_DIMENSIONS", "1024"))
    MEMORY_QDRANT_URL = os.environ.get("MEMORY_QDRANT_URL", "http://127.0.0.1:6333").rstrip("/")
    MEMORY_QDRANT_API_KEY = os.environ.get("MEMORY_QDRANT_API_KEY", "")
    MEMORY_COLLECTION = os.environ.get("MEMORY_COLLECTION", "portfolio_memory")
    MEMORY_BATCH_SIZE = max(1, min(20, int(os.environ.get("MEMORY_BATCH_SIZE", "20"))))
    MEMORY_INTERVAL_SECONDS = max(5, int(os.environ.get("MEMORY_INTERVAL_SECONDS", "10")))
    MEMORY_IMPORT_BATCH_SIZE = max(
        1, min(200, int(os.environ.get("MEMORY_IMPORT_BATCH_SIZE", "50")))
    )
    MEMORY_LEXICAL_BATCH_SIZE = max(
        1, min(200, int(os.environ.get("MEMORY_LEXICAL_BATCH_SIZE", "50")))
    )
    MEMORY_VECTOR_DOCUMENT_BATCH_SIZE = max(
        1, min(20, int(os.environ.get("MEMORY_VECTOR_DOCUMENT_BATCH_SIZE", "4")))
    )
    MEMORY_EMBEDDING_SEND_DIMENSIONS = os.environ.get(
        "MEMORY_EMBEDDING_SEND_DIMENSIONS", "true"
    ).lower() in ("1", "true", "yes")

    # Database
    DATABASE_URL: str = os.environ.get("DATABASE_URL", f"sqlite:///{PROJECT_ROOT / 'portfolio.db'}")

    # The debrief kernel performs no model calls (design §1.2). These settings
    # remain for the optional legacy UI but never gate the kernel.
    DEEPSEEK_API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    DEEPSEEK_MODEL: str = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    # Max output tokens (model allows up to 384K; 64K is a practical agent default).
    DEEPSEEK_MAX_TOKENS: int = int(os.environ.get("DEEPSEEK_MAX_TOKENS", "65536"))
    # Thinking intensity: high | max (agent workloads use max).
    DEEPSEEK_REASONING_EFFORT: str = os.environ.get("DEEPSEEK_REASONING_EFFORT", "max")
    DEEPSEEK_THINKING: bool = os.environ.get("DEEPSEEK_THINKING", "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    # Per-request HTTP timeout for chat/completions (seconds). Prevents indefinite hangs.
    DEEPSEEK_TIMEOUT: float = float(os.environ.get("DEEPSEEK_TIMEOUT", "300"))

    # Telegram (send-only — no getUpdates long-poll; Accept/Dismiss on dashboard)
    TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")
    TELEGRAM_POLL_TIMEOUT: int = int(os.environ.get("TELEGRAM_POLL_TIMEOUT", "30"))
    TELEGRAM_POLL_MAX_BACKOFF: int = int(os.environ.get("TELEGRAM_POLL_MAX_BACKOFF", "60"))
    # Automatic push switches (opt-out via env).
    TELEGRAM_NEWS_PUSH: bool = os.environ.get("TELEGRAM_NEWS_PUSH", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    TELEGRAM_REPORT_PUSH: bool = os.environ.get("TELEGRAM_REPORT_PUSH", "true").lower() in (
        "1",
        "true",
        "yes",
    )

    # A PriceCache row is considered stale for on-read refresh when fetched_at
    # is NULL or older than this many seconds.
    PRICE_STALE_SECONDS: int = max(10, int(os.environ.get("PRICE_STALE_SECONDS", "120")))

    # Display / logging timezone (DB timestamps stay UTC; UI converts for display).
    # Default Beijing time. Override with e.g. APP_TIMEZONE=America/New_York
    APP_TIMEZONE: str = os.environ.get("APP_TIMEZONE", "Asia/Shanghai")

    # Google login is fail-closed by default; disable only for local development.
    # OAuth client/cookie secrets live in .streamlit/secrets.toml.
    AUTH_ENABLED: bool = os.environ.get("AUTH_ENABLED", "true").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    AUTH_ALLOWED_EMAILS: str = os.environ.get("AUTH_ALLOWED_EMAILS", "")

    # Default news poll: 08:00–22:00 Asia/Shanghai every 2 hours (editable on Jobs page).
    # 5-field crontab: minute hour day month day_of_week
    DEFAULT_NEWS_CRONTAB: str = os.environ.get("NEWS_CRONTAB", "0 8-22/2 * * *")
    # Price collection covers all market sessions (US after-hours, HK close,
    # CN, crypto 24/7): every 30 minutes around the clock (Asia/Shanghai).
    # Overridable via env PRICES_CRONTAB or the persisted scheduler settings
    # (data/scheduler_settings.json → prices_crontab).
    DEFAULT_PRICES_CRONTAB: str = os.environ.get("PRICES_CRONTAB", "*/30 * * * *")

    # News API
    WALLSTREETCN_BASE_URL: str = "https://api-one-wscn.awtmt.com/apiv1"
    # Optional Brave web search (kept for the legacy UI; the kernel never calls it).
    BRAVE_SEARCH_API_KEY: str = os.environ.get("BRAVE_SEARCH_API_KEY", "")
    BRAVE_SEARCH_BASE_URL: str = os.environ.get(
        "BRAVE_SEARCH_BASE_URL",
        "https://api.search.brave.com/res/v1/web/search",
    )

    # Markets that require trading-day checks (crypto is 24/7)
    TRADING_MARKETS: dict = {
        "US": {"timezone": "America/New_York", "close_hour": 16, "close_minute": 0},
        "CN": {"timezone": "Asia/Shanghai", "close_hour": 15, "close_minute": 0},
        "HK": {"timezone": "Asia/Hong_Kong", "close_hour": 16, "close_minute": 0},
    }


config = Config()
