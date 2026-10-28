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
        f"- `{order['id']}`: {order['symbol']}, максимум "
        f"{snapshot_value['markets'][order['symbol']]['high_24h']}, минимум "
        f"{snapshot_value['markets'][order['symbol']]['low_24h']}, последняя цена "
        f"{snapshot_value['markets'][order['symbol']]['last']}; не достигнут; "
        "сравнение с диапазоном не доказывает исполнение."
        for order in state["orders"]
    )
    funding_lines = "\n".join(
        f"- {symbol}USDT ставка фандинга (lastFundingRate): "
        f"{snapshot_value['markets'][f'{symbol}USDT']['last_funding_rate']}"
        for symbol in cron_pipeline.ASSET_SYMBOLS
    )
    table_lines = [
        "| Символ | Максимум 24ч | Минимум 24ч | Последняя цена | Изменение 24ч, % | Объём 24ч |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for symbol in cron_pipeline.ASSET_SYMBOLS:
        market = snapshot_value["markets"][f"{symbol}USDT"]
        table_lines.append(
            f"| {symbol} | {market['high_24h']} | {market['low_24h']} | "
            f"{market['last']} | {market['percent_change_24h']} | {market['volume_24h']} |"
        )
    return f"""## 1. Проверка триггеров за День N-1
Достигнут означает, что уровень триггера находится внутри предоставленного диапазона максимум/минимум за 24 часа; не достигнут означает, что он находится вне диапазона; неопределённо означает, что текущих значений максимума, минимума или последней цены недостаточно. Касание не доказывает исполнение.
{trigger_lines}

## 2. Деривативы / Фандинг / Ликвидации
{funding_lines}
Данные о ликвидациях: недоступны (не предоставлены во входных данных).

## 3. Макроэкономика / Ончейн-настроения
Индекс страха и жадности: {snapshot_value['fear_greed']}
Доминирование BTC: 58.8%
Дополнительные макроданные: недоступны (не предоставлены во входных данных).
Ончейн-данные: недоступны (не предоставлены во входных данных).

## 4. Сводная таблица по 8 активам
{chr(10).join(table_lines)}

## 5. Практические торговые триггеры для модельного баланса 1 BTC + $20k USDT
Модельный баланс (отдельно от отслеживаемого портфеля): 1 BTC + $20,000 USDT.
- Если BTC торгуется выше $91,000, продать 0.10 BTC из модельного баланса.
- Если BTC торгуется ниже $89,000, использовать $2,000 USDT из модельного баланса.
Этот отчёт не исполняет сделки."""


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

    def test_prompt_requires_russian_analysis(self):
        prompt = cron_pipeline.build_prompt(
            43, self.snapshot, self.previous, self.state, self.metrics
        )
        self.assertIn("отчёт на русском языке", prompt)
        self.assertIn(
            "Весь аналитический текст должен быть написан на русском языке",
            cron_pipeline.SYSTEM_INSTRUCTION,
        )

    def test_english_report_is_rejected(self):
        english = self.conforming_report.replace(
            "сравнение с диапазоном не доказывает исполнение.",
            "This trigger was not touched and does not prove execution.",
            1,
        )
        with self.assertRaisesRegex(cron_pipeline.PipelineError, "English-language prose"):
            cron_pipeline.validate_report_markdown(
                english,
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
        self.assertIn("детерминированную проверку", prompts[1])
        self.assertIn("ПРЕДЫДУЩИЙ НЕКОРРЕКТНЫЙ ОТВЕТ", prompts[1])

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
            self.assertEqual(
                report["title"],
                f"День {expected_day}: количественный обзор крипторынка",
            )
            self.assertIsInstance(report["metrics"]["portfolio_value"], float)
            self.assertEqual(saved_reports["reports"][0]["day"], expected_day)
            self.assertEqual(saved_state["execution"]["last_report_day"], expected_day)
            self.assertFalse(saved_state["execution"]["orders_executed_by_pipeline"])
            self.assertTrue(all(order["status"] == "pending" for order in saved_state["orders"]))
        self.assertEqual((ROOT / "data" / "reports.json").read_bytes(), canonical_before)


if __name__ == "__main__":
    unittest.main()
