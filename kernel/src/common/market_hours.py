"""Regular trading sessions per market (weekday-only, exchange timezones).

Used by the watchlist reminder job: a price target is only announced while the
instrument's own market is in its regular session, so a US-listed stock no
longer pings at 21:00 Beijing time (US pre-market) or on weekends. Crypto has
no session and is always open.

Exchange holidays are not modelled yet: on a holiday the worker still sees a
(freshly fetched but unchanged) last price, so the cost is at most one
reminder per cooldown window instead of a fully silent day. Early closes are
likewise ignored.
"""

from datetime import datetime, time, timezone
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from config import config


def _parse_hm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


# Regular-session windows in the market's exchange timezone: (open, close).
# CN and HK have a lunch break; US is one continuous session. CRYPTO trades
# 24/7 and is therefore absent (see is_market_open).
MARKET_SESSIONS: Dict[str, Tuple[Tuple[time, time], ...]] = {
    "US": ((_parse_hm("09:30"), _parse_hm("16:00")),),
    "CN": ((_parse_hm("09:30"), _parse_hm("11:30")), (_parse_hm("13:00"), _parse_hm("15:00"))),
    "HK": ((_parse_hm("09:30"), _parse_hm("12:00")), (_parse_hm("13:00"), _parse_hm("16:00"))),
}


def is_market_open(market: str, now: Optional[datetime] = None) -> bool:
    """Return True when ``market`` is inside its regular trading session.

    ``now`` may be timezone-aware (converted to the market timezone) or naive
    (interpreted as UTC, matching the DB timestamps). Weekends are closed.
    Unknown markets fail open so a newly added market never silently loses
    reminders; supported markets all have an explicit window here.
    """
    market = (market or "").upper()
    if market == "CRYPTO":
        return True

    info = config.TRADING_MARKETS.get(market)
    windows = MARKET_SESSIONS.get(market)
    if not info or not windows:
        return True

    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    local = now.astimezone(ZoneInfo(info["timezone"]))
    if local.weekday() >= 5:
        return False
    current = local.time()
    return any(start <= current < end for start, end in windows)
