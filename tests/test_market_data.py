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
    def get(self, url, params=None, timeout=None):
        if url == market_data.SPOT_URL:
            return FakeResponse([
                {"symbol": symbol, "highPrice": "12", "lowPrice": "8", "lastPrice": "10", "volume": "42", "priceChangePercent": "2.5"}
                for symbol in market_data.SYMBOLS
            ])
        if url == market_data.FUTURES_URL:
            return FakeResponse([{"symbol": symbol, "lastFundingRate": "0.0001"} for symbol in market_data.SYMBOLS])
        return FakeResponse({"data": [{"value": "61"}]})


class MarketDataTests(unittest.TestCase):
    def test_fetches_and_parses_all_required_symbols(self):
        snapshot = market_data.fetch_market_snapshot(session=FakeSession())
        self.assertEqual(set(snapshot["markets"]), set(market_data.SYMBOLS))
        self.assertEqual(snapshot["markets"]["BTCUSDT"]["last"], 10.0)
        self.assertEqual(snapshot["markets"]["LINKUSDT"]["last_funding_rate"], 0.0001)
        self.assertEqual(snapshot["fear_greed"], 61)

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
