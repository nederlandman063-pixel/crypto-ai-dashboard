from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "liquidation_service"))

from core import LiquidationEvent, parse_liquidation_event, summarize_events


class LiquidationServiceTests(unittest.TestCase):
    def test_parses_tracked_force_order(self):
        event = parse_liquidation_event(
            {
                "e": "forceOrder",
                "E": 1_700_000_000_000,
                "o": {
                    "s": "BTCUSDT",
                    "S": "SELL",
                    "q": "2",
                    "z": "1.5",
                    "p": "90",
                    "ap": "100",
                    "T": 1_700_000_000_000,
                },
            }
        )
        self.assertEqual(event.symbol, "BTCUSDT")
        self.assertEqual(event.notional_usd, 150.0)

    def test_rejects_untracked_or_malformed_event(self):
        self.assertIsNone(parse_liquidation_event({"e": "trade"}))
        self.assertIsNone(
            parse_liquidation_event(
                {"e": "forceOrder", "E": 1, "o": {"s": "OTHERUSDT", "S": "BUY"}}
            )
        )

    def test_summarizes_long_and_short_liquidations(self):
        now = 2_000_000_000_000
        events = [
            LiquidationEvent(now - 1000, "BTCUSDT", "SELL", 1, 100, 100),
            LiquidationEvent(now - 500, "BTCUSDT", "BUY", 2, 100, 200),
            LiquidationEvent(now - 25 * 60 * 60 * 1000, "ETHUSDT", "SELL", 9, 100, 900),
        ]
        summary = summarize_events(events, now_ms=now)
        self.assertEqual(summary["event_count"], 2)
        self.assertEqual(summary["notional_usd"], 300.0)
        self.assertEqual(summary["long_liquidations_usd"], 100.0)
        self.assertEqual(summary["short_liquidations_usd"], 200.0)
        self.assertEqual(summary["largest_event"]["side"], "BUY")


if __name__ == "__main__":
    unittest.main()
