# Project review and maintenance plan

Reviewed 2026-10-28 against upstream commit 5c77c01.

## Connection and current status

- Local checkout: `crypto-ai-dashboard` inside the `my sites` workspace; origin points to https://github.com/nederlandman063-pixel/crypto-ai-dashboard.git.
- Live site: https://nederlandman063-pixel.github.io/crypto-ai-dashboard/ (HTTP fetch succeeded; browser interaction not yet reviewed).
- Latest three public scheduled Actions runs succeeded. Latest: https://github.com/nederlandman063-pixel/crypto-ai-dashboard/actions/runs/40725965525.
- Eight archived reports, most recent Day 42 dated 2026-10-28. State records success at 16:27 UTC.
- Configured schedule: 10:00 UTC daily (11:00 Berlin in winter, 12:00 in summer). Actual runs can be delayed; recent observed runs started around 15:43–16:30 UTC.
- GitHub push permissions and repository settings access have not been verified. No ongoing monitoring is configured.

## Architecture

Public Binance spot/futures endpoints and Alternative.me sentiment feed `scripts/market_data.py`. `scripts/cron_pipeline.py` revalues fixed holdings and asks Gemini 2.5 Flash for a detailed Russian investment-note report, validates seven required sections and snapshot-backed numeric references, and retries invalid output up to three times. Canonical JSON lives in `data/`. GitHub Actions commits generated data and deploys `public/` to GitHub Pages. The Russian-language interface uses Tailwind, Three.js, Chart.js, marked, and DOMPurify via CDNs.

The application tracks a model portfolio and pending triggers. It does not submit or execute exchange orders. The separate 1 BTC + $20k model in the report is distinct from the tracked portfolio. The initial $99,960 capital and $10,000 reserved funds are accounting assumptions documented in README.

## Prioritized backlog

| Priority | Work | Completion criterion |
| --- | --- | --- |
| P1 | Add push/PR test CI | All existing tests run on pull requests and code pushes; data generation remains separate. Current workflow only runs on schedule/manual dispatch and does not execute tests. |
| P1 | Label carried-forward BTC dominance | Dashboard/report clearly distinguish historical dominance from refreshed metrics, or use a timestamped live source. |
| P1 | Make daily runs idempotent | Re-running a successful date does not silently append another day; define an explicit replacement policy. Current code always increments maximum day. |
| P1 | Improve persistence recovery | Inject failure between the two JSON replacements and prove report/state consistency can be recovered. Writes are atomic per file, not across both files. |
| P2 | Strengthen trigger validation | Tests reject incorrect touched/not-touched outcomes and mismatched symbol/value attribution; current retrospective checks primarily ensure IDs and numbers appear. |
| P2 | Pin dependencies | Reproducible Python dependency versions and versioned CDN assets; update the existing exact-requirements test accordingly. |
| P2 | Improve input validation and outages | Reject nonfinite/invalid market values before AI calls; define bounded retry and clear failure diagnostics. |
| P2 | Show freshness and operational health | Display stale-data state and distinguish scheduled time from last actual success. Investigate observed schedule delays. |
| P2 | Browser verification | Exercise archive, charts, navigation, mobile layout, missing data, and CDN failures in a real browser. |
| Deferred | Deploy the optional liquidation collector | Only after explicit approval: create one continuously running Google Cloud instance/service, a small Storage bucket, and a least-privilege service account; set the GitHub variable `LIQUIDATION_SUMMARY_URL`; verify 24-hour accumulation and cost monitoring. Until then the pipeline must continue publishing normally with liquidation data marked unavailable. |

## Deferred cloud decision

The Binance liquidation WebSocket collector is implemented under `liquidation_service/`, but no Google Cloud resources have been created and no billing has been activated for it. This work is intentionally deferred. The daily workflow treats `LIQUIDATION_SUMMARY_URL` as optional, so spot prices, volume, funding, Fear & Greed, and Binance Open Interest continue to be collected and reports continue to publish when the variable is empty.

## Maintenance routine

Before changes, fetch upstream and check status: the daily workflow also changes canonical data. Use a feature branch for implementation, run `.venv/bin/python -m unittest discover -s tests -v`, then build with `.venv/bin/python scripts/prepare_public.py`. Review diffs before pushing. Avoid invoking the live generation command just to test: it consumes Gemini requests and updates canonical data.

Check Actions failures and report timestamps during maintenance sessions. Review dependency updates and data assumptions periodically. Future automation should be configured separately with an agreed notification policy.

## Changes made during onboarding

Created an isolated `.venv` and aligned the README and workflow test with the already-configured 10:00 UTC schedule. No production workflow or portfolio data changed. Local changes are not pushed.
