"""Currency conversion helpers (no Streamlit dependency — safe for agent/jobs)."""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import requests

from domain.markets import currency_for_market

logger = logging.getLogger(__name__)

# Process-local last-known rates (fallback after transient FX failures).
FX_RATES: Dict[str, float] = {}

_FX_URL = "https://open.er-api.com/v6/latest/{}"
_FX_TIMEOUT = float(os.environ.get("DEBRIEF_FX_TIMEOUT", "5"))

# One dashboard build asks for the same table three times (holdings, rates,
# fx panel). Caching the provider answer keeps that at exactly one HTTP call;
# the TTL also keeps a long-lived worker process from hammering the provider.
FX_CACHE_TTL_SECONDS = float(os.environ.get("DEBRIEF_FX_CACHE_SECONDS", "3600"))

# (monotonic seconds at fetch, UTC ISO timestamp, units_per_1_cny)
_units_cache: Optional[Tuple[float, str, Dict[str, float]]] = None


def reset_cache() -> None:
    """Drop the process-local provider cache (tests, forced refresh)."""
    global _units_cache
    _units_cache = None


def _provider_units() -> Tuple[str, Dict[str, float]]:
    """(asOf, units_per_1_cny) from open.er-api.com, cached for the TTL.

    Raises ValueError when the provider is unreachable or unsuccessful; a
    failed refresh never poisons the cache.
    """
    global _units_cache
    if _units_cache is not None:
        fetched_at, as_of, units = _units_cache
        if (time.monotonic() - fetched_at) < FX_CACHE_TTL_SECONDS:
            return as_of, units
    try:
        response = requests.get(_FX_URL.format("CNY"), timeout=_FX_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise ValueError(f"FX provider unavailable: {exc}") from None
    if payload.get("result") != "success":
        raise ValueError("FX provider returned an unsuccessful response")

    units: Dict[str, float] = {"CNY": 1.0}
    for ccy, rate in (payload.get("rates") or {}).items():
        try:
            units[str(ccy).upper()] = float(rate)
        except (TypeError, ValueError):
            continue
    as_of = datetime.now(timezone.utc).isoformat()
    _units_cache = (time.monotonic(), as_of, units)
    return as_of, units


def _fetch_rate(base_currency: str) -> float:
    """CNY per 1 unit of `base_currency` (shares the provider cache)."""
    ccy = (base_currency or "").upper()
    _, units = _provider_units()
    rate = units.get(ccy)
    if rate is None or rate <= 0:
        raise ValueError(f"no FX rate for {ccy}")
    return 1.0 / rate


def get_rates(base: str = "CNY") -> Dict:
    """Fetch cross rates for `base` from open.er-api.com (single /latest/CNY call).

    Returns {"base": BASE, "asOf": iso-utc, "rates": {CCY: units_per_1_base},
             "source": "open.er-api.com"}.

    Env overrides follow the kernel semantics: ``DEBRIEF_FX_USD=7.2`` means
    7.2 CNY per 1 USD, i.e. units_of_CCY_per_1_CNY = 1/7.2. CNY, USD, HKD and
    EUR are always present when the provider (or an override) supplies them.
    Raises ValueError when the provider fails or the base is unavailable.
    """
    base = (base or "CNY").upper()
    as_of, units = _provider_units()
    units_per_1_cny: Dict[str, float] = dict(units)

    # Env overrides applied to the CNY base: DEBRIEF_FX_<CCY> = CNY per 1 CCY.
    for key, value in os.environ.items():
        if not key.startswith("DEBRIEF_FX_") or key == "DEBRIEF_FX_":
            continue
        ccy = key[len("DEBRIEF_FX_"):].strip().upper()
        if not ccy or not value:
            continue
        try:
            units_per_1_cny[ccy] = 1.0 / float(value)
        except (ValueError, ZeroDivisionError):
            continue

    if base not in units_per_1_cny:
        raise ValueError(f"no FX rate for base currency {base}")
    base_units = units_per_1_cny[base]
    rates = {
        ccy: round(units_ / base_units, 8)
        for ccy, units_ in units_per_1_cny.items()
    }
    return {
        "base": base,
        "asOf": as_of,
        "rates": rates,
        "source": "open.er-api.com",
    }


def get_cny_rates(markets: Tuple[str, ...]) -> Dict[str, float]:
    """Fetch CNY conversion rates required by the supplied markets.

    A transient provider failure uses the most recent process-local rate. A
    market is omitted when it has no usable rate, allowing callers to avoid
    presenting an unconverted value as CNY.
    """
    normalized_markets = {market.upper() for market in markets}
    rates: Dict[str, float] = {}

    if "CN" in normalized_markets:
        rates["CN"] = 1.0

    base_rates: Dict[str, float] = {}
    for market in normalized_markets - {"CN"}:
        base_currency = currency_for_market(market)
        if base_currency not in base_rates:
            try:
                base_rates[base_currency] = _fetch_rate(base_currency)
            except Exception as exc:
                logger.warning("Unable to fetch %s/CNY rate: %s", base_currency, exc)

        rate = base_rates.get(base_currency)
        if rate is not None:
            FX_RATES[market] = rate
        else:
            rate = FX_RATES.get(market)
        if rate is None:
            rate = next(
                (
                    saved_rate
                    for saved_market, saved_rate in FX_RATES.items()
                    if currency_for_market(saved_market) == base_currency
                ),
                None,
            )

        if rate is not None:
            rates[market] = rate

    return rates
