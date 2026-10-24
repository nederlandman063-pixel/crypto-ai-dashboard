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


def snapshot():
    prices = {"BTC": 90000, "ETH": 3000, "SOL": 120, "LINK": 18}
    markets = {}
    for symbol in cron_pipeline.ASSET_SYMBOLS:
        markets[f"{symbol}USDT"] = {
            "high_24h": 1.0,
            "low_24h": 1.0,
            "last": float(prices.get(symbol, 1.0)),
            "volume_24h": 1.0,
            "percent_change_24h": 0.0,
            "last_funding_rate": 0.0,
        }
    return {
        "as_of": "2026-10-24T00:00:00+00:00",
        "markets": markets,
        "fear_greed": 59,
        "sources": {},
    }


def valid_report(snapshot_value, state):
    trigger_lines = "\n".join(
        f"- `{order['id']}`: not touched; range comparison does not prove execution."
        for order in state["orders"]
    )
    funding_lines = "\n".join(
        f"- {symbol}USDT lastFundingRate: {snapshot_value['markets'][f'{symbol}USDT']['last_funding_rate']}"
        for symbol in cron_pipeline.ASSET_SYMBOLS
    )
    table_lines = [
        "| Symbol | High 24h | Low 24h | Last | 24h Change % | Volume 24h |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for symbol in cron_pipeline.ASSET_SYMBOLS:
        market = snapshot_value["markets"][f"{symbol}USDT"]
        table_lines.append(
            f"| {symbol} | {market['high_24h']} | {market['low_24h']} | "
            f"{market['last']} | {market['percent_change_24h']} | {market['volume_24h']} |"
        )
    return f"""## 1. Retrospective check against Day N-1 triggers
Touched means the trigger lies inside the supplied 24h high/low range; not touched means it lies outside; indeterminate means the current high, low, or last is insufficient. A touch does not prove execution.
{trigger_lines}

## 2. Derivatives / Funding / Liquidations
{funding_lines}
Liquidation data: unavailable (not provided in supplied data).

## 3. Macro / Onchain sentiment
Fear & Greed: {snapshot_value['fear_greed']}
BTC dominance: 58.8%
Additional macro data: unavailable (not provided in supplied data).
Onchain data: unavailable (not provided in supplied data).

## 4. 8-asset comparative summary table
{chr(10).join(table_lines)}

## 5. Practical trading triggers for 1 BTC + $20k USDT model balance
Model balance (separate from tracked portfolio): 1 BTC + $20,000 USDT.
- If BTC trades above $91,000, sell 0.10 BTC from the model balance.
- If BTC trades below $89,000, deploy $2,000 USDT from the model balance.
No trades are executed by this report."""


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.document = cron_pipeline.load_json(ROOT / "data" / "reports.json")
        self.state = cron_pipeline.load_json(ROOT / "data" / "state.json")
        self.snapshot = snapshot()
        self.previous = cron_pipeline.latest_report(self.document)
        self.metrics = cron_pipeline.build_metrics(
            self.previous, self.snapshot, self.document["initial_capital_usd"]
        )
        self.conforming_report = valid_report(self.snapshot, self.state)

    def test_official_sdk_and_model_configuration(self):
        from google import genai

        self.assertIsNotNone(genai.Client)
        self.assertEqual(cron_pipeline.MODEL, "gemini-2.5-flash")

    def test_missing_api_key_fails_without_calling_network(self):
        with self.assertRaisesRegex(cron_pipeline.PipelineError, "GEMINI_API_KEY"):
            cron_pipeline.generate_with_gemini("prompt", "")

    def test_revalues_without_double_counting_reserved_cash(self):
        holdings = round(0.5 * 90000 + 5.5866 * 3000 + 333.33 * 18 + 44.56 * 120, 2)
        expected = round(holdings + 28043.29 + 10000.0, 2)
        self.assertEqual(self.metrics["portfolio_value"], expected)
        self.assertEqual(self.metrics["cash_reserve_usd"], 28043.29)
        self.assertEqual(self.metrics["reserved_for_limits_usd"], 10000.0)

    def test_structural_validation_accepts_exact_five_part_report(self):
        cron_pipeline.validate_report_markdown(
            self.conforming_report,
            snapshot=self.snapshot,
            current_metrics=self.metrics,
            state=self.state,
        )

    def test_structural_validation_rejects_current_day_36_shape(self):
        day_36 = next(report for report in self.document["reports"] if report["day"] == 36)
        with self.assertRaisesRegex(cron_pipeline.PipelineError, "exactly the five required"):
            cron_pipeline.validate_report_markdown(
                day_36["content"],
                snapshot=self.snapshot,
                current_metrics=self.metrics,
                state=self.state,
            )

    def test_validation_rejects_table_value_not_in_snapshot(self):
        invalid = self.conforming_report.replace("| BTC | 1.0 |", "| BTC | 2.0 |", 1)
        with self.assertRaisesRegex(cron_pipeline.PipelineError, "BTC table high_24h"):
            cron_pipeline.validate_report_markdown(
                invalid,
                snapshot=self.snapshot,
                current_metrics=self.metrics,
                state=self.state,
            )

    def test_invalid_first_response_is_repaired_with_bounded_retry(self):
        prompts = []

        def generator(prompt):
            prompts.append(prompt)
            return "## 1. Executive Summary\nInvalid" if len(prompts) == 1 else self.conforming_report

        result = cron_pipeline.generate_validated_report(
            "original prompt",
            generator,
            snapshot=self.snapshot,
            current_metrics=self.metrics,
            state=self.state,
        )
        self.assertEqual(result, self.conforming_report)
        self.assertEqual(len(prompts), 2)
        self.assertIn("deterministic validation", prompts[1])
        self.assertIn("PREVIOUS INVALID RESPONSE", prompts[1])

    def test_persistent_invalid_output_fails_before_json_write(self):
        with tempfile.TemporaryDirectory() as temp:
            reports_path = Path(temp) / "reports.json"
            state_path = Path(temp) / "state.json"
            shutil.copy2(ROOT / "data" / "reports.json", reports_path)
            shutil.copy2(ROOT / "data" / "state.json", state_path)
            reports_before = reports_path.read_bytes()
            state_before = state_path.read_bytes()
            calls = []

            def invalid_generator(prompt):
                calls.append(prompt)
                return "## 1. Executive Summary\nStill invalid"

            with self.assertRaisesRegex(
                cron_pipeline.PipelineError, "failed structural validation after 3 attempts"
            ):
                cron_pipeline.run_pipeline(
                    reports_path=reports_path,
                    state_path=state_path,
                    snapshot_fetcher=lambda: self.snapshot,
                    report_generator=invalid_generator,
                    now=datetime(2026, 10, 24, tzinfo=timezone.utc),
                )
            self.assertEqual(len(calls), cron_pipeline.MAX_REPORT_ATTEMPTS)
            self.assertEqual(reports_path.read_bytes(), reports_before)
            self.assertEqual(state_path.read_bytes(), state_before)

    def test_end_to_end_appends_next_day_in_temporary_copy(self):
        canonical_before = (ROOT / "data" / "reports.json").read_bytes()
        expected_day = cron_pipeline.next_day(self.document)
        with tempfile.TemporaryDirectory() as temp:
            reports_path = Path(temp) / "reports.json"
            state_path = Path(temp) / "state.json"
            shutil.copy2(ROOT / "data" / "reports.json", reports_path)
            shutil.copy2(ROOT / "data" / "state.json", state_path)
            report = cron_pipeline.run_pipeline(
                reports_path=reports_path,
                state_path=state_path,
                snapshot_fetcher=lambda: self.snapshot,
                report_generator=lambda prompt: self.conforming_report,
                now=datetime(2026, 10, 24, tzinfo=timezone.utc),
            )
            saved_reports = json.loads(reports_path.read_text(encoding="utf-8"))
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(report["day"], expected_day)
            self.assertIsInstance(report["metrics"]["portfolio_value"], float)
            self.assertEqual(saved_reports["reports"][0]["day"], expected_day)
            self.assertEqual(saved_state["execution"]["last_report_day"], expected_day)
            self.assertFalse(saved_state["execution"]["orders_executed_by_pipeline"])
            self.assertTrue(all(order["status"] == "pending" for order in saved_state["orders"]))
        self.assertEqual((ROOT / "data" / "reports.json").read_bytes(), canonical_before)


if __name__ == "__main__":
    unittest.main()
