from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BaselineContractTests(unittest.TestCase):
    def test_day_35_metrics_and_allocations_are_preserved(self):
        document = json.loads((ROOT / "data" / "reports.json").read_text(encoding="utf-8"))
        report = next(item for item in document["reports"] if item["day"] == 35)
        metrics = report["metrics"]
        self.assertEqual(report["day"], 35)
        self.assertEqual(document["initial_capital_usd"], 99960.0)
        expected = {
            "portfolio_value": 104783.29,
            "pnl_usd": 4823.29,
            "pnl_percent": 4.83,
            "cash_reserve_usd": 28043.29,
            "reserved_for_limits_usd": 10000.0,
            "cash_ratio": 26.8,
            "fear_greed": 62,
            "btc_dominance": 58.8,
        }
        for key, value in expected.items():
            self.assertEqual(metrics[key], value)
        allocations = {item["symbol"]: item for item in metrics["allocations"]}
        self.assertEqual((allocations["BTC"]["quantity"], allocations["BTC"]["value_usd"]), (0.5, 42325.0))
        self.assertEqual((allocations["USDT"]["label"], allocations["USDT"]["value_usd"]), ("Cash + Limits", 28043.0))
        self.assertEqual((allocations["ETH"]["quantity"], allocations["ETH"]["value_usd"]), (5.5866, 14190.0))
        self.assertEqual((allocations["LINK"]["quantity"], allocations["LINK"]["value_usd"]), (333.33, 5150.0))
        self.assertEqual((allocations["SOL"]["quantity"], allocations["SOL"]["value_usd"]), (44.56, 5075.0))

    def test_required_pending_orders_are_machine_readable(self):
        state = json.loads((ROOT / "data" / "state.json").read_text(encoding="utf-8"))
        orders = {item["id"]: item for item in state["orders"]}
        self.assertEqual(orders["btc-limit-buy-84280"]["limit_price_usd"], 84280.0)
        self.assertEqual(orders["btc-limit-buy-84280"]["quote_amount_usdt"], 10000.0)
        self.assertEqual(orders["sol-tp-11740"]["trigger_price_usd"], 117.4)
        self.assertEqual(orders["sol-stop-11220"]["stop_price_usd"], 112.2)
        self.assertEqual(orders["link-tp-1590"]["trigger_price_usd"], 15.9)
        self.assertEqual(orders["link-stop-1520"]["stop_price_usd"], 15.2)
        self.assertTrue(all(order["status"] == "pending" for order in orders.values()))
        self.assertTrue(all(order["executed_at"] is None for order in orders.values()))

    def test_requirements_are_exact(self):
        lines = (ROOT / "scripts" / "requirements.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines, ["google-genai", "requests"])


if __name__ == "__main__":
    unittest.main()
