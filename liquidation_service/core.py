"""Dependency-free parsing and aggregation for Binance liquidation events."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

STREAM_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"
WINDOW_MS = 24 * 60 * 60 * 1000
TRACKED_SYMBOLS = {
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "LINKUSDT",
}


@dataclass(frozen=True)
class LiquidationEvent:
    timestamp: int
    symbol: str
    side: str
    quantity: float
    price: float
    notional_usd: float


def parse_liquidation_event(payload: Any) -> LiquidationEvent | None:
    if not isinstance(payload, dict) or payload.get("e") != "forceOrder":
        return None
    order = payload.get("o")
    if not isinstance(order, dict):
        return None
    symbol = order.get("s")
    side = order.get("S")
    if symbol not in TRACKED_SYMBOLS or side not in {"BUY", "SELL"}:
        return None
    try:
        timestamp = int(order.get("T") or payload["E"])
        quantity = float(order.get("z") or order.get("q"))
        price = float(order.get("ap") or order.get("p"))
    except (KeyError, TypeError, ValueError):
        return None
    if timestamp <= 0 or quantity <= 0 or price <= 0:
        return None
    return LiquidationEvent(
        timestamp=timestamp,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        notional_usd=round(quantity * price, 2),
    )


def summarize_events(
    events: list[LiquidationEvent],
    *,
    now_ms: int,
) -> dict[str, Any]:
    cutoff = now_ms - WINDOW_MS
    active = [event for event in events if cutoff <= event.timestamp <= now_ms]
    by_symbol: dict[str, dict[str, float | int]] = {
        symbol: {
            "event_count": 0,
            "notional_usd": 0.0,
            "long_liquidations_usd": 0.0,
            "short_liquidations_usd": 0.0,
        }
        for symbol in sorted(TRACKED_SYMBOLS)
    }
    for event in active:
        item = by_symbol[event.symbol]
        item["event_count"] = int(item["event_count"]) + 1
        item["notional_usd"] = float(item["notional_usd"]) + event.notional_usd
        key = "long_liquidations_usd" if event.side == "SELL" else "short_liquidations_usd"
        item[key] = float(item[key]) + event.notional_usd
    for item in by_symbol.values():
        for key in ("notional_usd", "long_liquidations_usd", "short_liquidations_usd"):
            item[key] = round(float(item[key]), 2)
    total = round(sum(event.notional_usd for event in active), 2)
    long_total = round(sum(event.notional_usd for event in active if event.side == "SELL"), 2)
    short_total = round(sum(event.notional_usd for event in active if event.side == "BUY"), 2)
    largest = max(active, key=lambda event: event.notional_usd, default=None)
    return {
        "window_start": cutoff,
        "window_end": now_ms,
        "event_count": len(active),
        "notional_usd": total,
        "long_liquidations_usd": long_total,
        "short_liquidations_usd": short_total,
        "largest_event": asdict(largest) if largest else None,
        "by_symbol": by_symbol,
        "source": STREAM_URL,
        "coverage_note": (
            "Binance publishes at most the latest liquidation event per symbol "
            "within each 1000 ms interval; totals are a sampled lower bound."
        ),
    }
