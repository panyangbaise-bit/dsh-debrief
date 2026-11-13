"""Verify process lifecycle without launching live providers or background jobs."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

import runtime


@pytest.fixture
def services(monkeypatch):
    from adapters import base
    from adapters.base import AdapterRegistry
    from db import migrate, repository
    from memory import indexer
    from notifier import telegram
    from scheduler import cron

    events = []
    monkeypatch.setattr(runtime, "_services", None)
    monkeypatch.setattr(runtime, "_infrastructure_ready", False)
    monkeypatch.setattr(base, "registry", AdapterRegistry())
    monkeypatch.setattr(repository, "init_db", lambda: events.append("db"))
    monkeypatch.setattr(migrate, "migrate", lambda engine: events.append("migrate"))
    for module, name, event in (
        (indexer, "start_worker", "memory+"),
        (indexer, "stop_worker", "memory-"),
        (cron, "start_scheduler", "scheduler+"),
        (cron, "stop_scheduler", "scheduler-"),
        (telegram, "send_welcome", "welcome"),
    ):
        monkeypatch.setattr(module, name, lambda *args, event=event: events.append(event))
    yield events
    runtime.stop_services()


def test_concurrent_reruns_start_only_one_service_set(services):
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: runtime.start_services(), range(20)))
    assert services == ["db", "migrate", "memory+", "scheduler+", "welcome"]
    runtime.stop_services()
    runtime.stop_services()
    assert services[-2:] == ["scheduler-", "memory-"]


def test_direct_ui_start_uses_kernel_services_only(services):
    runtime.start_services()
    assert services == ["db", "migrate", "memory+", "scheduler+", "welcome"]
    runtime.stop_services()
    assert services[-2:] == ["scheduler-", "memory-"]


def test_optional_notification_failure_keeps_services_running(services, monkeypatch):
    from notifier import telegram

    monkeypatch.setattr(telegram, "send_welcome", Mock(side_effect=OSError("offline")))
    runtime.start_services()
    assert runtime._services is not None
    assert "scheduler-" not in services


def test_memory_worker_can_stop_and_restart_without_overlapping(monkeypatch):
    import threading

    from memory import indexer

    observed = threading.Event()
    monkeypatch.setattr(indexer.config, "MEMORY_ENABLED", True)
    monkeypatch.setattr(indexer, "initialize", lambda engine: None)
    monkeypatch.setattr(indexer, "tick", lambda engine: observed.set())
    monkeypatch.setattr(indexer, "_thread", None)
    monkeypatch.setattr(indexer, "_stop", threading.Event())
    try:
        indexer.start_worker(None)
        assert observed.wait(1)
        first = indexer._thread
        indexer.stop_worker()
        assert not first.is_alive()
        observed.clear()
        indexer.start_worker(None)
        assert observed.wait(1)
        assert indexer._thread is not first
    finally:
        indexer.stop_worker()


def test_memory_thread_start_failure_is_safe_to_clean_up(monkeypatch):
    import threading

    from memory import indexer

    monkeypatch.setattr(indexer.config, "MEMORY_ENABLED", True)
    monkeypatch.setattr(indexer, "initialize", lambda engine: None)
    monkeypatch.setattr(indexer, "_thread", None)
    monkeypatch.setattr(indexer, "_stop", threading.Event())
    monkeypatch.setattr(threading.Thread, "start", Mock(side_effect=RuntimeError("no threads")))
    with pytest.raises(RuntimeError, match="no threads"):
        indexer.start_worker(None)
    indexer.stop_worker()
    assert indexer._thread is None
