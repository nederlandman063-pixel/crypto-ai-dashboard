"""Fetch public crypto market data without API credentials."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import requests

SPOT_URL = "https://data-api.binance.vision/api/v3/ticker/24hr"
FUTURES_URL = "https://www.binance.com/fapi/v1/premiumIndex"
OPEN_INTEREST_URL = "https://www.binance.com/fapi/v1/openInterest"
OPEN_INTEREST_HISTORY_URL = "https://www.binance.com/futures/data/openInterestHist"
FNG_URL = "https://api.alternative.me/fng/"
SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "LINKUSDT",
)
DEFAULT_TIMEOUT = (5, 20)
OPEN_INTEREST_PERIOD = "1h"
OPEN_INTEREST_LIMIT = 25


class MarketDataError(RuntimeError):
    """Raised when a public market-data response is unavailable or malformed."""


def _request_json(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: tuple[int, int] = DEFAULT_TIMEOUT,
) -> Any:
    try:
        response = session.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise MarketDataError(f"Request failed for {url}: {exc}") from exc
    except ValueError as exc:
        raise MarketDataError(f"Invalid JSON returned by {url}") from exc


def _number(record: dict[str, Any], field: str, symbol: str) -> float:
    try:
        value = float(record[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise MarketDataError(f"Invalid or missing {field!r} for {symbol}") from exc
    return value


def _index_by_symbol(payload: Any, source: str) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, list):
        raise MarketDataError(f"{source} response must be a list")
    indexed: dict[str, dict[str, Any]] = {}
    for item in payload:
        if isinstance(item, dict) and isinstance(item.get("symbol"), str):
            indexed[item["symbol"]] = item
    missing = [symbol for symbol in SYMBOLS if symbol not in indexed]
    if missing:
        raise MarketDataError(f"{source} response missing symbols: {', '.join(missing)}")
    return indexed


def _open_interest_metrics(
    symbol: str,
    current_payload: Any,
    history_payload: Any,
    mark_price: float,
) -> dict[str, float | int]:
    if not isinstance(current_payload, dict):
        raise MarketDataError(f"Binance open interest response must be an object for {symbol}")
    current = _number(current_payload, "openInterest", symbol)
    try:
        timestamp = int(current_payload["time"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MarketDataError(f"Invalid or missing open-interest time for {symbol}") from exc
    if not isinstance(history_payload, list) or not history_payload:
        raise MarketDataError(f"Binance open-interest history is empty for {symbol}")
    history = [item for item in history_payload if isinstance(item, dict)]
    if not history:
        raise MarketDataError(f"Binance open-interest history has no records for {symbol}")
    try:
        oldest = min(history, key=lambda item: int(item["timestamp"]))
        oldest_value = float(oldest["sumOpenInterest"])
        oldest_timestamp = int(oldest["timestamp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MarketDataError(f"Invalid open-interest history for {symbol}") from exc
    if oldest_value <= 0:
        raise MarketDataError(f"Open-interest history must be positive for {symbol}")
    return {
        "open_interest": current,
        "open_interest_usd": round(current * mark_price, 2),
        "open_interest_change_24h_percent": round(
            ((current - oldest_value) / oldest_value) * 100,
            6,
        ),
        "open_interest_time": timestamp,
        "open_interest_reference_time": oldest_timestamp,
    }


def _liquidation_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise MarketDataError("Liquidation summary response must be an object")
    normalized = dict(payload)
    numeric_fields = (
        "window_start",
        "window_end",
        "event_count",
        "notional_usd",
        "long_liquidations_usd",
        "short_liquidations_usd",
    )
    for field in numeric_fields:
        try:
            value = float(payload[field])
        except (KeyError, TypeError, ValueError) as exc:
            raise MarketDataError(f"Liquidation summary has invalid {field!r}") from exc
        if value < 0:
            raise MarketDataError(f"Liquidation summary {field!r} must be non-negative")
        normalized[field] = int(value) if field in {"window_start", "window_end", "event_count"} else value
    largest = payload.get("largest_event")
    if largest is not None:
        if not isinstance(largest, dict):
            raise MarketDataError("Liquidation summary largest_event must be an object or null")
        required = ("timestamp", "symbol", "side", "quantity", "price", "notional_usd")
        if any(field not in largest for field in required):
            raise MarketDataError("Liquidation summary largest_event is incomplete")
    return normalized


def fetch_market_snapshot(
    *,
    session: requests.Session | None = None,
    timeout: tuple[int, int] = DEFAULT_TIMEOUT,
    liquidation_summary_url: str | None = None,
) -> dict[str, Any]:
    """Return validated spot, derivatives, and Fear & Greed data for tracked assets."""

    http = session or requests.Session()
    spot_payload = _request_json(
        http,
        SPOT_URL,
        params={"symbols": json.dumps(SYMBOLS, separators=(",", ":"))},
        timeout=timeout,
    )
    futures_payload = _request_json(http, FUTURES_URL, timeout=timeout)
    fng_payload = _request_json(http, FNG_URL, params={"limit": 1}, timeout=timeout)

    spot = _index_by_symbol(spot_payload, "Binance spot")
    futures = _index_by_symbol(futures_payload, "Binance futures")

    open_interest: dict[str, dict[str, float | int]] = {}
    for symbol in SYMBOLS:
        current_payload = _request_json(
            http,
            OPEN_INTEREST_URL,
            params={"symbol": symbol},
            timeout=timeout,
        )
        history_payload = _request_json(
            http,
            OPEN_INTEREST_HISTORY_URL,
            params={
                "symbol": symbol,
                "period": OPEN_INTEREST_PERIOD,
                "limit": OPEN_INTEREST_LIMIT,
            },
            timeout=timeout,
        )
        mark_price = _number(futures[symbol], "markPrice", symbol)
        open_interest[symbol] = _open_interest_metrics(
            symbol,
            current_payload,
            history_payload,
            mark_price,
        )

    try:
        fng_raw = fng_payload["data"][0]["value"]
        fear_greed = int(fng_raw)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise MarketDataError("Alternative.me response has no valid Fear & Greed score") from exc
    if not 0 <= fear_greed <= 100:
        raise MarketDataError("Alternative.me Fear & Greed score is outside 0..100")

    markets: dict[str, dict[str, float]] = {}
    for symbol in SYMBOLS:
        ticker = spot[symbol]
        markets[symbol] = {
            "high_24h": _number(ticker, "highPrice", symbol),
            "low_24h": _number(ticker, "lowPrice", symbol),
            "last": _number(ticker, "lastPrice", symbol),
            "volume_24h": _number(ticker, "volume", symbol),
            "percent_change_24h": _number(ticker, "priceChangePercent", symbol),
            "last_funding_rate": _number(futures[symbol], "lastFundingRate", symbol),
            **open_interest[symbol],
        }

    snapshot: dict[str, Any] = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "markets": markets,
        "fear_greed": fear_greed,
        "sources": {
            "spot": SPOT_URL,
            "funding": FUTURES_URL,
            "open_interest": OPEN_INTEREST_URL,
            "open_interest_history": OPEN_INTEREST_HISTORY_URL,
            "fear_greed": FNG_URL,
        },
    }
    configured_liquidation_url = (
        liquidation_summary_url
        if liquidation_summary_url is not None
        else os.environ.get("LIQUIDATION_SUMMARY_URL", "")
    ).strip()
    if configured_liquidation_url:
        snapshot["sources"]["liquidations"] = configured_liquidation_url
        try:
            payload = _request_json(http, configured_liquidation_url, timeout=timeout)
            snapshot["liquidations_24h"] = _liquidation_summary(payload)
            snapshot["liquidations_status"] = {"available": True}
        except MarketDataError as exc:
            snapshot["liquidations_status"] = {
                "available": False,
                "reason": str(exc),
            }
    return snapshot


def main() -> int:
    """Fetch one live snapshot for diagnostics without writing repository data."""

    snapshot = fetch_market_snapshot()
    print(json.dumps(snapshot, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
