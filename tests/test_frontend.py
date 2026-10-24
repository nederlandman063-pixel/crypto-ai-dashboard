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
        self.assertIn("https://cdn.jsdelivr.net/npm/marked/marked.min.js", HTML)
        self.assertIn("three.min.js", HTML)
        self.assertIn("cdn.tailwindcss.com", HTML)
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

    def test_report_markdown_uses_marked_and_is_sanitized(self):
        self.assertIn("marked.parse(report.content)", HTML)
        self.assertIn("DOMPurify.sanitize", HTML)

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
