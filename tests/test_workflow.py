from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/daily_cron.yml").read_text(encoding="utf-8")


class WorkflowContractTests(unittest.TestCase):
    def test_required_schedule_permissions_and_jobs(self):
        for fragment in (
            "cron: '0 0 * * *'",
            "workflow_dispatch:",
            "contents: write",
            "pages: write",
            "id-token: write",
            "runs-on: ubuntu-latest",
            "python-version: '3.11'",
            "uses: actions/upload-pages-artifact@v3",
            "uses: actions/deploy-pages@v4",
            "python scripts/prepare_public.py",
        ):
            self.assertIn(fragment, WORKFLOW)

    def test_only_canonical_data_files_are_staged(self):
        self.assertIn("git add -- data/reports.json data/state.json", WORKFLOW)
        self.assertIn("github-actions[bot]", WORKFLOW)
        self.assertIn("git rebase", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
