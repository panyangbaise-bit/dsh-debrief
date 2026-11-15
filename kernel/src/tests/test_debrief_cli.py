"""CLI contract tests: canonical envelope + per-command JSON schema.

Read commands must be isomorphic to dsh-debrief/mock/debrief.js; write
commands take stdin JSON and return {id, ...} envelopes.
"""

import json

import pytest


@pytest.fixture(autouse=True)
def no_live_suggest(monkeypatch):
    """Instruments fallbacks never touch the network in tests."""
    from debrief import catalog

    monkeypatch.setattr(catalog, "eastmoney_suggest", lambda *a, **k: [])
    monkeypatch.setattr(catalog, "coingecko_search", lambda *a, **k: [])


def test_envelope_success_shape(seeded_db, run_cli):
    code, payload = run_cli(["--db", str(seeded_db), "holdings", "--json", ])
    assert code == 0
    assert payload == {
        "ok": True,
        "schemaVersion": 1,
        "data": payload["data"],
    }


def test_envelope_failure_and_exit_code(seeded_db, run_cli):
    code, payload = run_cli(
        ["--db", str(seeded_db), "report", "latest", ]
    )
    assert code == 1
    assert payload["ok"] is False
    assert payload["schemaVersion"] == 1
    assert payload["error"]["code"] == "DEBRIEF_NOT_FOUND"


def test_unknown_command_usage_error(seeded_db, run_cli):
    code, payload = run_cli(["frobnicate", "--json"])
    assert code == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "DEBRIEF_USAGE"


def test_holdings_schema(seeded_db, run_cli):
    code, payload = run_cli(["--db", str(seeded_db), "holdings", "--json", ])
    assert code == 0
    data = payload["data"]
    assert set(data) == {
        "asOf", "currency", "totalMarketValue", "dayPnl", "dayPnlPct", "totalPnl",
        "totalPnlPct", "positions", "pricesRefreshed",
    }
    assert data["currency"] == "CNY"
    assert data["pricesRefreshed"] is True  # auto-refresh ran on the seed
    assert data["totalMarketValue"] > 0
    symbols = {p["symbol"] for p in data["positions"]}
    assert symbols == {"600519", "AAPL"}
    position = next(p for p in data["positions"] if p["symbol"] == "600519")
    assert set(position) == {
        "market", "symbol", "name", "quantity", "cost", "price", "marketValue",
        "pnlPct", "weight", "currency",
    }
    assert position["market"] == "CN"
    assert position["currency"] == "CNY"
    assert position["quantity"] == 200
    assert position["price"] == 1412.0
    assert position["marketValue"] == 282400.0
    assert round(position["pnlPct"], 2) == round((1412 - 1450) / 1450 * 100, 2)


def test_transactions_schema(seeded_db, run_cli):
    code, payload = run_cli(["--db", str(seeded_db), "transactions", "--limit", "5", ],
    )
    assert code == 0
    data = payload["data"]
    assert set(data) == {"total", "limit", "offset", "items"}
    assert data["limit"] == 5
    assert data["total"] >= 3  # two opening buys + two apply_trade rows
    item = data["items"][0]
    assert set(item) == {"time", "side", "market", "symbol", "name", "quantity", "price", "amount", "status"}
    assert item["status"] == "filled"
    assert item["side"] in ("buy", "sell")


def test_transactions_ticker_filter(seeded_db, run_cli):
    code, payload = run_cli(["--db", str(seeded_db), "transactions", "--ticker", "AAPL", ],
    )
    assert code == 0
    data = payload["data"]
    assert data["total"] >= 2
    assert all(item["symbol"] == "AAPL" for item in data["items"])


def test_watchlist_schema(seeded_db, run_cli):
    code, payload = run_cli(["--db", str(seeded_db), "watchlist", ])
    assert code == 0
    data = payload["data"]
    assert set(data) == {"count", "items", "pricesRefreshed"}
    assert data["pricesRefreshed"] is True
    item = data["items"][0]
    assert set(item) == {
        "market", "symbol", "name", "price", "changePct", "targetPrice",
        "distancePct", "alert", "currency",
    }
    assert item["symbol"] == "00700"
    assert item["market"] == "HK"
    assert item["currency"] == "HKD"
    assert item["targetPrice"] == 380.0


def test_instruments_ranked_search(seeded_db, run_cli):
    from sqlalchemy.orm import Session

    from debrief.catalog import _upsert_rows
    from debrief.context import open_engine

    engine = open_engine(seeded_db)
    with Session(engine) as db:
        _upsert_rows(
            db,
            [
                {"market": "CN", "symbol": "600519", "name": "贵州茅台", "currency": "CNY", "asset_class": "stock", "pinyin_alias": "maotai gzmt"},
                {"market": "CN", "symbol": "601318", "name": "中国平安", "currency": "CNY", "asset_class": "stock", "pinyin_alias": "zgpa"},
                {"market": "US", "symbol": "AAPL", "name": "苹果", "currency": "USD", "asset_class": "stock", "pinyin_alias": ""},
            ],
        )
    engine.dispose()

    code, payload = run_cli(["--db", str(seeded_db), "instruments", "search", "--market", "cn", "--query", "600519", ],
    )
    assert code == 0
    data = payload["data"]
    assert set(data) == {"query", "market", "source", "items"}
    assert data["market"] == "cn"
    assert data["items"][0]["symbol"] == "600519"

    # Pinyin alias fallback finds the same instrument.
    code, payload = run_cli(["--db", str(seeded_db), "instruments", "search", "--market", "cn", "--query", "maotai", ],
    )
    assert code == 0
    assert payload["data"]["items"][0]["symbol"] == "600519"

    # held flag on a held instrument.
    code, payload = run_cli(["--db", str(seeded_db), "instruments", "search", "--market", "us", "--query", "aapl", ],
    )
    assert code == 0
    assert payload["data"]["items"][0]["held"] is True


def test_instruments_requires_query_length(seeded_db, run_cli):
    code, payload = run_cli(["--db", str(seeded_db), "instruments", "search", "--market", "us", "--query", "a", ],
    )
    assert code == 1
    assert payload["error"]["code"] == "DEBRIEF_ARGS"


def test_report_lifecycle(seeded_db, run_cli):
    # Create → read latest → read by id → latest filtered by market.
    payload_stdin = json.dumps(
        {
            "market": "us",
            "title": "盘后分析",
            "summary": "组合内 AAPL 温和跟涨。",
            "fullText": "更完整的正文。",
            "metrics": [{"label": "波动率", "value": "18.6%"}],
            "chart": {"title": "60 日走势", "unit": "", "points": [100.0, 101.2, 103.4]},
        }
    )
    code, payload = run_cli(
        ["--db", str(seeded_db), "report", "create", "--json", ], stdin=payload_stdin
    )
    assert code == 0
    assert set(payload["data"]) == {"id", "status", "notified"}
    assert payload["data"]["notified"] is False  # Telegram unconfigured in tests
    report_id = payload["data"]["id"]
    assert report_id.startswith("rpt-")

    code, payload = run_cli(
        ["--db", str(seeded_db), "report", "latest", "--market", "us", ]
    )
    assert code == 0
    data = payload["data"]
    assert set(data) == {"id", "market", "title", "generatedAt", "summary", "fullText", "metrics", "chart"}
    assert data["market"] == "US"
    assert data["summary"] == "组合内 AAPL 温和跟涨。"
    assert data["metrics"] == [{"label": "波动率", "value": "18.6%"}]
    assert data["chart"]["points"] == [100.0, 101.2, 103.4]

    code, payload = run_cli(
        ["--db", str(seeded_db), "report", "--id", report_id, ]
    )
    assert code == 0
    assert payload["data"]["id"] == report_id


def test_report_create_links_job(seeded_db, run_cli):
    code, start = run_cli(["--db", str(seeded_db), "job", "start", "--kind", "after-market-us", ],
    )
    assert code == 0
    job_id = start["data"]["id"]
    stdin = json.dumps({"market": "us", "title": "t", "summary": "s", "jobId": job_id})
    code, payload = run_cli(
        ["--db", str(seeded_db), "report", "create", "--json", ], stdin=stdin
    )
    assert code == 0
    assert payload["data"]["status"] == "succeeded"
    code, status = run_cli(
        ["--db", str(seeded_db), "job", "status", "--id", str(job_id), ]
    )
    assert code == 0
    assert status["data"]["status"] == "succeeded"


def test_memory_add_and_search(seeded_db, run_cli):
    stdin = json.dumps(
        {
            "sourceType": "decision",
            "content": "建仓理由：服务收入连续超预期，等待端侧 AI 催化。",
            "instruments": ["US:AAPL"],
        }
    )
    code, payload = run_cli(
        ["--db", str(seeded_db), "memory", "add", "--json", ], stdin=stdin
    )
    assert code == 0
    doc_id = payload["data"]["docId"]
    assert isinstance(doc_id, int)

    code, payload = run_cli(["--db", str(seeded_db), "memory", "search", "--query", "服务收入", ],
    )
    assert code == 0
    data = payload["data"]
    assert set(data) == {"query", "items"}
    assert any(item["layer"] == "short" and item["evidence"][0]["docId"] == doc_id for item in data["items"])


def test_analysis_prepare_schema_and_reentrancy(seeded_db, run_cli):
    code, payload = run_cli(["--db", str(seeded_db), "analysis", "prepare", "--market", "us", ],
    )
    assert code == 0
    data = payload["data"]
    assert set(data) == {"market", "preparedAt", "jobId", "inputs", "guidance", "pricesRefreshed"}
    assert set(data["inputs"]) == {"quotes", "news", "memoryCandidates"}
    assert data["market"] == "us"
    assert data["pricesRefreshed"] is True
    assert data["inputs"]["quotes"][0]["symbol"] == "AAPL"
    job_id = data["jobId"]

    # Re-entrancy lock: a running job for the same market must be rejected.
    code, payload = run_cli(["--db", str(seeded_db), "analysis", "prepare", "--market", "us", ],
    )
    assert code == 1
    assert payload["error"]["code"] == "DEBRIEF_JOB_ALREADY_RUNNING"
    assert str(job_id) in payload["error"]["message"]


def test_job_state_machine(seeded_db, run_cli):
    code, payload = run_cli(["--db", str(seeded_db), "job", "start", "--kind", "weekly-review", ],
    )
    assert code == 0
    assert payload["data"] == {"id": payload["data"]["id"], "status": "running"}
    job_id = payload["data"]["id"]

    code, payload = run_cli(
        ["--db", str(seeded_db), "job", "status", "--id", str(job_id), ]
    )
    assert code == 0
    assert set(payload["data"]) == {"id", "kind", "status", "durationSec"}
    assert payload["data"]["kind"] == "周复盘"
    assert payload["data"]["status"] == "running"
    assert payload["data"]["durationSec"] is None

    code, payload = run_cli(["--db", str(seeded_db), "job", "finish", "--id", str(job_id), "--status", "done", ],
    )
    assert code == 0
    assert payload["data"] == {"id": job_id, "status": "succeeded"}

    # Idempotent finish of a terminal job.
    code, payload = run_cli(["--db", str(seeded_db), "job", "finish", "--id", str(job_id), "--status", "failed", ],
    )
    assert code == 0
    assert payload["data"]["status"] == "succeeded"


def test_job_finish_with_error_code(seeded_db, run_cli):
    code, payload = run_cli(
        ["--db", str(seeded_db), "job", "start", "--kind", "prices", ]
    )
    job_id = payload["data"]["id"]
    code, payload = run_cli([
            "--db", str(seeded_db), "job", "finish", "--id", str(job_id), "--status", "failed",
            "--error-code", "DEBRIEF_UPSTREAM_PRICE",
        ],
    )
    assert code == 0
    assert payload["data"]["status"] == "failed"
    code, payload = run_cli(
        ["--db", str(seeded_db), "job", "status", "--id", str(job_id), ]
    )
    assert payload["data"]["errorCode"] == "DEBRIEF_UPSTREAM_PRICE"


def test_job_list_schema(seeded_db, run_cli):
    code, payload = run_cli(
        ["--db", str(seeded_db), "job", "list", "--limit", "10", ]
    )
    assert code == 0
    assert set(payload["data"]) == {"items"}
    for item in payload["data"]["items"]:
        assert set(item) <= {"id", "kind", "at", "status", "durationSec", "errorCode"}
        assert item["status"] in ("succeeded", "running", "failed")


def test_dashboard_schema(seeded_db, run_cli):
    code, payload = run_cli(
        ["--db", str(seeded_db), "dashboard", "--range", "30", ]
    )
    assert code == 0
    data = payload["data"]
    assert set(data) == {
        "kpis", "series", "composition", "holdings", "watchlist", "fx", "pricesAsOf", "memories", "pricesRefreshed",
    }
    assert isinstance(data["memories"], list)
    assert data["pricesAsOf"] is None or isinstance(data["pricesAsOf"], str)
    assert data["pricesRefreshed"] is True
    assert data["fx"]["base"] == "CNY"
    assert set(data["fx"]) == {"base", "asOf", "rates", "source"}
    assert data["fx"]["source"] == "open.er-api.com"
    assert set(data["kpis"]) == {
        "totalAssets", "currency", "dayPnl", "dayPnlPct", "totalPnl", "totalPnlPct", "annualPct",
    }
    assert data["series"]["range"] == 30
    assert len(data["series"]["equity"]) == len(data["series"]["returns"]) >= 1
    composition = {item["name"]: item["value"] for item in data["composition"]}
    assert composition["贵州茅台"] > 0
    assert composition["苹果"] > 0


def test_dashboard_range_validation(seeded_db, run_cli):
    code, payload = run_cli(
        ["--db", str(seeded_db), "dashboard", "--range", "15", ]
    )
    assert code == 2
    assert payload["error"]["code"] == "DEBRIEF_USAGE"


def test_migrate_command_idempotent(seeded_db, run_cli):
    code, payload = run_cli(["--db", str(seeded_db), "migrate", ])
    assert code == 0
    assert payload["data"]["applied"] == []  # already migrated by open_engine
    assert payload["data"]["totalMigrations"] >= 16
