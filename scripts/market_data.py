"""Fetch public crypto market data without API credentials."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import requests

SPOT_URL = "https://api.binance.com/api/v3/ticker/24hr"
FUTURES_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
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


def fetch_market_snapshot(
    *,
    session: requests.Session | None = None,
    timeout: tuple[int, int] = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Return validated spot, funding, and Fear & Greed data for tracked assets."""

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
        }

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "markets": markets,
        "fear_greed": fear_greed,
        "sources": {
            "spot": SPOT_URL,
            "funding": FUTURES_URL,
            "fear_greed": FNG_URL,
        },
    }


def main() -> int:
    """Fetch one live snapshot for diagnostics without writing repository data."""

    snapshot = fetch_market_snapshot()
    print(json.dumps(snapshot, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
