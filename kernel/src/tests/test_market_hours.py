"""Regular trading sessions: reminder pushes must respect the market clock."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from common.market_hours import is_market_open


def _at(zone: str, year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(zone))


def test_us_regular_session_and_premarket():
    # 2026-11-25 is a Wednesday.
    assert is_market_open("US", _at("America/New_York", 2026, 11, 25, 10, 0)) is True
    assert is_market_open("US", _at("America/New_York", 2026, 11, 25, 8, 0)) is False
    assert is_market_open("US", _at("America/New_York", 2026, 11, 25, 16, 0)) is False
    assert is_market_open("US", _at("America/New_York", 2026, 11, 25, 9, 29)) is False
    assert is_market_open("US", _at("America/New_York", 2026, 11, 25, 9, 30)) is True


def test_cn_and_hk_lunch_breaks():
    assert is_market_open("CN", _at("Asia/Shanghai", 2026, 11, 25, 10, 0)) is True
    assert is_market_open("CN", _at("Asia/Shanghai", 2026, 11, 25, 12, 0)) is False
    assert is_market_open("CN", _at("Asia/Shanghai", 2026, 11, 25, 14, 0)) is True
    assert is_market_open("CN", _at("Asia/Shanghai", 2026, 11, 25, 15, 0)) is False
    assert is_market_open("HK", _at("Asia/Hong_Kong", 2026, 11, 25, 11, 59)) is True
    assert is_market_open("HK", _at("Asia/Hong_Kong", 2026, 11, 25, 12, 30)) is False
    assert is_market_open("HK", _at("Asia/Hong_Kong", 2026, 11, 25, 13, 0)) is True


def test_weekend_is_closed_for_equities_but_crypto_trades():
    saturday = _at("America/New_York", 2026, 11, 28, 10, 0)
    assert is_market_open("US", saturday) is False
    assert is_market_open("CRYPTO", saturday) is True
    assert is_market_open("CRYPTO", datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc)) is True


def test_naive_datetime_is_interpreted_as_utc():
    # 14:00 UTC == 09:00 America/New_York (EST) — one hour before the open.
    assert is_market_open("US", datetime(2026, 11, 25, 14, 0)) is False
    # 15:00 UTC == 10:00 ET — inside the session.
    assert is_market_open("US", datetime(2026, 11, 25, 15, 0)) is True


@pytest.mark.parametrize("market", ["US", "CN", "HK"])
def test_supported_markets_are_never_unknown(market):
    # Unknown markets fail open; these three must be explicitly modelled.
    from common.market_hours import MARKET_SESSIONS

    assert market in MARKET_SESSIONS
