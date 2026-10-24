from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cron_pipeline


REPORT_MARKDOWN = """## 1. Executive Summary
Deterministic test report.
## 2. Market Snapshot
Mock prices only.
## 3. Portfolio Performance
Values were recomputed.
## 4. Risk & Active Orders
All orders remain pending.
## 5. Quantitative Outlook
No forecast in this fixture."""


def snapshot():
    prices = {"BTC": 90000, "ETH": 3000, "SOL": 120, "LINK": 18}
    markets = {}
    for symbol in ("BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "LINK"):
        markets[f"{symbol}USDT"] = {
            "high_24h": 1.0,
            "low_24h": 1.0,
            "last": float(prices.get(symbol, 1.0)),
            "volume_24h": 1.0,
            "percent_change_24h": 0.0,
            "last_funding_rate": 0.0,
        }
    return {"as_of": "2026-10-24T00:00:00+00:00", "markets": markets, "fear_greed": 59, "sources": {}}


class PipelineTests(unittest.TestCase):
    def test_official_sdk_and_model_configuration(self):
        from google import genai

        self.assertIsNotNone(genai.Client)
        self.assertEqual(cron_pipeline.MODEL, "gemini-2.5-flash")

    def test_missing_api_key_fails_without_calling_network(self):
        with self.assertRaisesRegex(cron_pipeline.PipelineError, "GEMINI_API_KEY"):
            cron_pipeline.generate_with_gemini("prompt", "")

    def test_revalues_without_double_counting_reserved_cash(self):
        document = cron_pipeline.load_json(ROOT / "data" / "reports.json")
        previous = cron_pipeline.latest_report(document)
        metrics = cron_pipeline.build_metrics(previous, snapshot(), document["initial_capital_usd"])
        holdings = round(0.5 * 90000 + 5.5866 * 3000 + 333.33 * 18 + 44.56 * 120, 2)
        expected = round(holdings + 28043.29 + 10000.0, 2)
        self.assertEqual(metrics["portfolio_value"], expected)
        self.assertEqual(metrics["cash_reserve_usd"], 28043.29)
        self.assertEqual(metrics["reserved_for_limits_usd"], 10000.0)

    def test_end_to_end_appends_day_36_in_temporary_copy(self):
        canonical_before = (ROOT / "data" / "reports.json").read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            reports_path = Path(temp) / "reports.json"
            state_path = Path(temp) / "state.json"
            shutil.copy2(ROOT / "data" / "reports.json", reports_path)
            shutil.copy2(ROOT / "data" / "state.json", state_path)
            report = cron_pipeline.run_pipeline(
                reports_path=reports_path,
                state_path=state_path,
                snapshot_fetcher=snapshot,
                report_generator=lambda prompt: REPORT_MARKDOWN,
                now=datetime(2026, 10, 24, tzinfo=timezone.utc),
            )
            saved_reports = json.loads(reports_path.read_text(encoding="utf-8"))
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(report["day"], 36)
            self.assertIsInstance(report["metrics"]["portfolio_value"], float)
            self.assertEqual(saved_reports["reports"][0]["day"], 36)
            self.assertEqual(saved_state["execution"]["last_report_day"], 36)
            self.assertFalse(saved_state["execution"]["orders_executed_by_pipeline"])
            self.assertTrue(all(order["status"] == "pending" for order in saved_state["orders"]))
        self.assertEqual((ROOT / "data" / "reports.json").read_bytes(), canonical_before)


if __name__ == "__main__":
    unittest.main()
