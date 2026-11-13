"""news latest: refresh + dedupe + limit, --no-refresh, refresh failure, --notify."""

import pytest

from config import config

FAKE_ITEMS = [
    {
        "title": "美联储按兵不动",
        "url": "https://wallstreetcn.com/articles/1",
        "summary": "维持利率不变",
        "published_at": "2026-11-13T08:00:00+00:00",
    },
    {
        "title": "美联储按兵不动",  # duplicate headline → deduped
        "url": "https://wallstreetcn.com/articles/1b",
        "summary": "duplicate",
        "published_at": "2026-11-13T08:05:00+00:00",
    },
    {
        "title": "A股放量上行",
        "url": "https://wallstreetcn.com/articles/2",
        "summary": "两市成交破万亿",
        "published_at": None,
    },
]


@pytest.fixture
def fake_news_adapter(monkeypatch):
    from adapters.news import WallStreetCNAdapter

    def fake_get_latest_news(self, limit=10):
        return list(FAKE_ITEMS)

    monkeypatch.setattr(WallStreetCNAdapter, "get_latest_news", fake_get_latest_news)


def test_news_latest_refresh_dedupes_and_limits(seeded_db, run_cli, fake_news_adapter):
    code, payload = run_cli(
        ["--db", str(seeded_db), "news", "latest", "--limit", "1", "--json"]
    )
    assert code == 0
    data = payload["data"]
    assert set(data) == {"items", "total", "fetched", "newCount", "asOf", "notified"}
    assert data["fetched"] is True
    assert data["newCount"] == 2  # 3 fetched, 1 duplicate headline deduped
    assert data["total"] == 2
    assert len(data["items"]) == 1  # --limit 1
    assert data["notified"] is False
    assert data["items"][0]["title"] == "美联储按兵不动"
    item = data["items"][0]
    assert set(item) == {"id", "title", "source", "url", "summary", "publishedAt"}
    assert item["source"] == "wallstreetcn"
    assert item["url"] == "https://wallstreetcn.com/articles/1"

    # Second run: everything already persisted → nothing new.
    code, payload = run_cli(["--db", str(seeded_db), "news", "latest", "--json"])
    assert code == 0
    assert payload["data"]["newCount"] == 0
    assert payload["data"]["fetched"] is True
    assert payload["data"]["total"] == 2


def test_news_no_refresh_empty_db(seeded_db, run_cli):
    code, payload = run_cli(
        ["--db", str(seeded_db), "news", "latest", "--no-refresh", "--json"]
    )
    assert code == 0
    data = payload["data"]
    assert data["fetched"] is False
    assert data["newCount"] == 0
    assert data["items"] == []
    assert data["total"] == 0


def test_news_refresh_failure_degrades(seeded_db, run_cli, monkeypatch):
    from adapters.news import WallStreetCNAdapter

    def boom(self, limit=10):
        raise ConnectionError("upstream down")

    monkeypatch.setattr(WallStreetCNAdapter, "get_latest_news", boom)
    code, payload = run_cli(["--db", str(seeded_db), "news", "latest", "--json"])
    assert code == 0
    assert payload["data"]["fetched"] is False
    assert payload["data"]["newCount"] == 0
    assert payload["data"]["items"] == []


def test_news_notify_digest(seeded_db, run_cli, fake_news_adapter, monkeypatch):
    sent = []
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "123")
    # The handler's explicit --notify is under test; the worker's own push off.
    monkeypatch.setattr(config, "TELEGRAM_NEWS_PUSH", False)
    monkeypatch.setattr(
        "notifier.telegram.notify", lambda message: sent.append(message) or True
    )
    code, payload = run_cli(
        ["--db", str(seeded_db), "news", "latest", "--notify", "--json"]
    )
    assert code == 0
    data = payload["data"]
    assert data["notified"] is True
    assert data["newCount"] == 2
    assert len(sent) == 1
    assert "新增 2 条" in sent[0]
    assert "美联储按兵不动" in sent[0]
    assert "A股放量上行" not in sent[0]  # no published time → skipped


def test_news_notify_requested_but_unconfigured(seeded_db, run_cli, fake_news_adapter):
    code, payload = run_cli(
        ["--db", str(seeded_db), "news", "latest", "--notify", "--json"]
    )
    assert code == 0
    assert payload["data"]["newCount"] == 2
    assert payload["data"]["notified"] is False  # degraded, not an error
