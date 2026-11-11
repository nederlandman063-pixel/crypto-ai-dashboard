from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import market_data


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    liquidation_url = "https://collector.example/summary"

    def get(self, url, params=None, timeout=None):
        if url == market_data.SPOT_URL:
            return FakeResponse([
                {"symbol": symbol, "highPrice": "12", "lowPrice": "8", "lastPrice": "10", "volume": "42", "priceChangePercent": "2.5"}
                for symbol in market_data.SYMBOLS
            ])
        if url == market_data.FUTURES_URL:
            return FakeResponse([
                {"symbol": symbol, "lastFundingRate": "0.0001", "markPrice": "10"}
                for symbol in market_data.SYMBOLS
            ])
        if url == market_data.OPEN_INTEREST_URL:
            return FakeResponse({"symbol": params["symbol"], "openInterest": "100", "time": 2000})
        if url == market_data.OPEN_INTEREST_HISTORY_URL:
            return FakeResponse([
                {"symbol": params["symbol"], "sumOpenInterest": "80", "sumOpenInterestValue": "800", "timestamp": 1000},
                {"symbol": params["symbol"], "sumOpenInterest": "90", "sumOpenInterestValue": "900", "timestamp": 1500},
            ])
        if url == self.liquidation_url:
            return FakeResponse({
                "window_start": 1000,
                "window_end": 2000,
                "event_count": 3,
                "notional_usd": 450.0,
                "long_liquidations_usd": 150.0,
                "short_liquidations_usd": 300.0,
                "largest_event": {
                    "timestamp": 1900,
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 2.0,
                    "price": 100.0,
                    "notional_usd": 200.0,
                },
                "coverage_note": "sampled lower bound",
            })
        return FakeResponse({"data": [{"value": "61"}]})


class MarketDataTests(unittest.TestCase):
    def test_fetches_and_parses_all_required_symbols(self):
        snapshot = market_data.fetch_market_snapshot(session=FakeSession())
        self.assertEqual(set(snapshot["markets"]), set(market_data.SYMBOLS))
        self.assertEqual(snapshot["markets"]["BTCUSDT"]["last"], 10.0)
        self.assertEqual(snapshot["markets"]["LINKUSDT"]["last_funding_rate"], 0.0001)
        self.assertEqual(snapshot["markets"]["BTCUSDT"]["open_interest"], 100.0)
        self.assertEqual(snapshot["markets"]["BTCUSDT"]["open_interest_usd"], 1000.0)
        self.assertEqual(snapshot["markets"]["BTCUSDT"]["open_interest_change_24h_percent"], 25.0)
        self.assertEqual(snapshot["fear_greed"], 61)
        self.assertNotIn("liquidations_24h", snapshot)

    def test_adds_configured_liquidation_summary(self):
        snapshot = market_data.fetch_market_snapshot(
            session=FakeSession(),
            liquidation_summary_url=FakeSession.liquidation_url,
        )
        self.assertEqual(snapshot["liquidations_24h"]["event_count"], 3)
        self.assertEqual(snapshot["liquidations_24h"]["short_liquidations_usd"], 300.0)
        self.assertTrue(snapshot["liquidations_status"]["available"])

    def test_liquidation_outage_does_not_block_daily_snapshot(self):
        class BrokenLiquidationSession(FakeSession):
            def get(self, url, params=None, timeout=None):
                if url == self.liquidation_url:
                    raise market_data.requests.RequestException("offline")
                return super().get(url, params=params, timeout=timeout)

        snapshot = market_data.fetch_market_snapshot(
            session=BrokenLiquidationSession(),
            liquidation_summary_url=FakeSession.liquidation_url,
        )
        self.assertNotIn("liquidations_24h", snapshot)
        self.assertFalse(snapshot["liquidations_status"]["available"])

    def test_rejects_missing_symbols(self):
        class MissingSession(FakeSession):
            def get(self, url, params=None, timeout=None):
                response = super().get(url, params=params, timeout=timeout)
                if url == market_data.SPOT_URL:
                    response.payload.pop()
                return response

        with self.assertRaisesRegex(market_data.MarketDataError, "missing symbols"):
            market_data.fetch_market_snapshot(session=MissingSession())


if __name__ == "__main__":
    unittest.main()
