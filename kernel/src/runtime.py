"""Process lifecycle shared by the kernel service entry points.

Importing this module is inert. Explicit startup serializes initialization and
owns background-service cleanup. The debrief kernel keeps only the
data/scheduler/memory layers — no agent, no A2A, no LLM.
"""

import atexit
import logging
import threading
from contextlib import ExitStack

logger = logging.getLogger(__name__)
_lock = threading.RLock()
_infrastructure_ready = False
_services: ExitStack | None = None


def initialize_infrastructure() -> None:
    """Create/migrate storage and register providers once per process."""
    global _infrastructure_ready
    with _lock:
        if _infrastructure_ready:
            return
        from adapters.base import registry
        from adapters.cn_market import CNMarketAdapter, HKMarketAdapter
        from adapters.crypto import CryptoAdapter
        from adapters.us_market import USMarketAdapter
        from db.migrate import migrate
        from db.repository import engine, init_db

        init_db()
        migrate(engine)
        for market, adapter in (
            ("US", USMarketAdapter()),
            ("CN", CNMarketAdapter()),
            ("HK", HKMarketAdapter()),
            ("CRYPTO", CryptoAdapter()),
        ):
            registry.register(market, adapter)
        _infrastructure_ready = True
        logger.info("Storage ready; market adapters: %s", registry.markets)


def start_services() -> None:
    """Start background services once; unwind resources if startup fails.

    Kernel services = memory indexing worker + APScheduler data collection.
    """
    global _services
    with _lock:
        if _services is not None:
            return
        initialize_infrastructure()
        from db.repository import engine
        from memory.indexer import start_worker, stop_worker
        from notifier.telegram import send_welcome
        from scheduler.cron import start_scheduler, stop_scheduler

        with ExitStack() as pending:
            pending.callback(stop_worker)
            start_worker(engine)
            pending.callback(stop_scheduler)
            start_scheduler()
            try:
                send_welcome()
            except Exception:
                logger.exception("Startup notification failed")
            _services = pending.pop_all()
        atexit.register(stop_services)
        logger.info("Background services ready")


def stop_services() -> None:
    """Release owned resources in reverse order; repeated calls are harmless."""
    global _services
    with _lock:
        if _services is None:
            return
        services, _services = _services, None
        atexit.unregister(stop_services)
        services.close()
