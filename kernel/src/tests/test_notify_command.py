"""notify test/status: token masking, send recorder, unconfigured envelope."""

import json

import pytest

from config import config

TOKEN = "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"


@pytest.fixture
def configured_telegram(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "987654321")


def test_notify_status_masks_token(run_cli, configured_telegram):
    code, payload = run_cli(["notify", "status", "--json"])
    assert code == 0
    data = payload["data"]
    assert data == {"configured": True, "chatIdSet": True, "tokenMask": "1234…efgh"}
    assert TOKEN not in json.dumps(payload)  # never leak the token


def test_notify_status_masks_partial_config(run_cli, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "abcdef123456789")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
    code, payload = run_cli(["notify", "status", "--json"])
    assert code == 0
    data = payload["data"]
    assert data == {"configured": False, "chatIdSet": False, "tokenMask": "abcd…6789"}
    assert "abcdef123456789" not in json.dumps(payload)


def test_notify_status_unconfigured_token_mask_null(run_cli):
    code, payload = run_cli(["notify", "status", "--json"])
    assert code == 0
    assert payload["data"] == {"configured": False, "chatIdSet": False, "tokenMask": None}


def test_notify_test_sends_and_reports(run_cli, configured_telegram, monkeypatch):
    sent = []

    monkeypatch.setattr(
        "notifier.telegram.notify", lambda message: sent.append(message) or True
    )
    code, payload = run_cli(["notify", "test", "--json"])
    assert code == 0
    assert payload["data"] == {"sent": True}
    assert len(sent) == 1
    assert "debrief 推送测试" in sent[0]


def test_notify_test_unconfigured_envelope(run_cli):
    # conftest clears TELEGRAM_* env; config was read with empty values.
    code, payload = run_cli(["notify", "test", "--json"])
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "DEBRIEF_TELEGRAM_UNCONFIGURED"
    assert "TELEGRAM_BOT_TOKEN" in payload["error"]["message"]
