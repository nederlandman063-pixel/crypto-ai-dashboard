from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "public" / "index.html").read_text(encoding="utf-8")


class InlineScriptParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_inline_script = False
        self.scripts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script" and "src" not in attributes:
            self.in_inline_script = True
            self.scripts.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_inline_script = False

    def handle_data(self, data):
        if self.in_inline_script:
            self.scripts[-1] += data


class FrontendContractTests(unittest.TestCase):
    def test_required_assets_loader_and_metrics_are_present(self):
        for asset in (
            "https://cdn.jsdelivr.net/npm/marked/marked.min.js",
            "https://cdn.jsdelivr.net/npm/chart.js",
            "three.min.js",
            "cdn.tailwindcss.com",
        ):
            self.assertIn(asset, HTML)
        self.assertIn("fetch('./data/reports.json?v=' + Date.now())", HTML)
        for element_id in (
            "metric-portfolio-val",
            "metric-pnl-val",
            "pnl-percent",
            "metric-cash-val",
            "cash-ratio",
            "metric-fng-val",
            "btc-dominance",
            "reserved-for-limits-usd",
            "current-day",
            "report-content",
        ):
            self.assertIn(f'id="{element_id}"', HTML)

    def test_nexus_views_and_stable_test_hooks_are_present(self):
        self.assertIn('lang="ru"', HTML)
        self.assertIn("NEXUS<span class=\"neon\">_TRADER</span>", HTML)
        self.assertIn("Главная", HTML)
        self.assertIn("Аналитика и Архив", HTML)
        for test_id in (
            "hud",
            "primary-nav",
            "dashboard-view",
            "analytics-view",
            "hero-panel",
            "kpi-grid",
            "performance-panel",
            "performance-chart-fallback",
            "allocation-panel",
            "allocation-chart-fallback",
            "holdings-panel",
            "derivatives-panel",
            "archive-panel",
            "archive-empty",
            "report-panel",
        ):
            self.assertIn(f'data-testid="{test_id}"', HTML)

    def test_report_markdown_uses_marked_and_is_sanitized(self):
        self.assertIn("marked.parse(report.content", HTML)
        self.assertIn("DOMPurify.sanitize", HTML)
        self.assertIn("FORBID_TAGS", HTML)
        self.assertIn("report-table-scroll", HTML)

    def test_archive_and_charts_are_derived_from_loaded_reports(self):
        self.assertIn("state.reports = documentData.reports", HTML)
        self.assertIn("state.reports.filter", HTML)
        self.assertIn("item.metrics.portfolio_value", HTML)
        self.assertIn("report?.metrics?.allocations", HTML)
        self.assertIn("report?.market_snapshot?.markets", HTML)
        self.assertIn("archive-search", HTML)
        self.assertIn("filterArchive", HTML)
        self.assertNotIn("Пассивный HODL", HTML)

    def test_reference_mocks_and_false_market_claims_are_absent(self):
        for forbidden in (
            "reportsDB",
            "Fill remaining historical mock archives",
            "Coinglass",
            "$103,801.86",
            "$148.0M",
            "$84,650",
            "RSI 1D",
            "Alpha vs HODL",
        ):
            self.assertNotIn(forbidden, HTML)
        self.assertIn("Ликвидации:</strong> Недоступно", HTML)
        self.assertIn("данные не поступают", HTML)
        self.assertIn("1 BTC + $20k", HTML)
        self.assertIn("Триггеры в отчетах не означают исполнение ордеров", HTML)

    def test_motion_and_failure_states_are_explicit(self):
        self.assertIn("prefers-reduced-motion: reduce", HTML)
        self.assertIn("visibilitychange", HTML)
        self.assertIn("renderer.setSize", HTML)
        self.assertIn("renderError", HTML)
        self.assertIn("архив пуст", HTML)

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_inline_javascript_parses(self):
        parser = InlineScriptParser()
        parser.feed(HTML)
        self.assertTrue(parser.scripts)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", encoding="utf-8") as script:
            script.write("\n".join(parser.scripts))
            script.flush()
            result = subprocess.run(
                ["node", "--check", script.name],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
