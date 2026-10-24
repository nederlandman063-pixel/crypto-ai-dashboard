# Crypto AI Dashboard

A cron-driven quantitative crypto analysis pipeline and a static, responsive Three.js dashboard for GitHub Pages. The pipeline reads public Binance spot/futures data and Alternative.me's Fear & Greed index, asks Gemini for a strictly validated five-section Markdown analysis, revalues holdings, and atomically updates local JSON state.

The software does not place, submit, cancel, or simulate exchange orders.

## Repository layout

- `data/reports.json` — canonical report archive, newest first
- `data/state.json` — machine-readable pending-order and pipeline metadata
- `scripts/market_data.py` — unauthenticated public market-data client
- `scripts/cron_pipeline.py` — accounting, Gemini analysis, and atomic persistence
- `scripts/prepare_public.py` — validates/copies source JSON into `public/data`
- `public/index.html` — static Tailwind/Three.js/marked SPA
- `.github/workflows/daily_cron.yml` — daily analysis and GitHub Pages workflow

## Accounting assumptions

The supplied Day 35 values imply initial capital of **$99,960.00**:

`$104,783.29 portfolio value - $4,823.29 PnL = $99,960.00`

The owner-supplied displayed allocations total **$94,783.00**, which is $10,000 below the supplied portfolio value (the remaining $0.29 is the precision difference between the displayed USDT allocation `$28,043` and canonical cash reserve `$28,043.29`). The data therefore records `reserved_for_limits_usd: 10000` separately for the pending BTC order. Portfolio NAV is calculated as:

`fresh non-cash holdings + liquid cash reserve + reserved-for-limit amount`

The liquid cash ratio uses only `cash_reserve_usd / portfolio_value`. The reserved amount is added exactly once and is not considered liquid cash. `Cash + Limits` is the required historical allocation label; its Day 35 displayed value remains the supplied `$28,043`, while the precise accounting field remains `$28,043.29`. Future generated entries value its cash allocation at that precise amount.

BTC dominance is carried forward because none of the required public endpoints supplies a total-market dominance series. The generated report receives that fact as prior/current structured input and must not invent a replacement. Active-order statuses stay `pending`; the pipeline only updates its execution metadata and explicitly records `orders_executed_by_pipeline: false`.

## Setup

Python 3.11 is used in CI.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r scripts/requirements.txt
```

No Binance or Alternative.me key is needed. To use Gemini, set the secret only in your shell or GitHub settings; never commit it:

```sh
export GEMINI_API_KEY='your-key-from-a-secure-secret-store'
python scripts/cron_pipeline.py
```

The command is path-safe when invoked from the repository root or the `scripts/` directory. It fails before producing a report when `GEMINI_API_KEY` is missing, and it does not fabricate fallback AI text.

## Local dashboard

Build the same static data layout used by Pages, then serve `public/` over HTTP:

```sh
python scripts/prepare_public.py
python -m http.server 8000 --directory public
```

Open <http://localhost:8000/>. Do not open `index.html` through `file://`, because browsers restrict its JSON fetch. `public/data/` is generated and ignored by Git; `data/` remains the source of truth.

## Tests and validation

```sh
python -m compileall -q scripts tests
python -m unittest discover -s tests -v
python -m json.tool data/reports.json >/dev/null
python -m json.tool data/state.json >/dev/null
```

The test suite uses deterministic HTTP/Gemini doubles and runs the next-day pipeline in a temporary directory. It covers exact headings, snapshot-backed table/funding values, bounded repair, rejection of the legacy Day 36 shape, and failure before persistence. It never calls Gemini or modifies canonical report data.

## GitHub Actions and Pages

1. Push the repository to GitHub.
2. In **Settings → Secrets and variables → Actions**, create the repository secret `GEMINI_API_KEY`.
3. In **Settings → Pages**, select **GitHub Actions** as the source.
4. Run **Actions → Daily crypto analysis and Pages → Run workflow** once, or wait for the `0 0 * * *` UTC schedule.

The workflow serializes runs, commits only `data/reports.json` and `data/state.json` as `github-actions[bot]`, rebases/retries pushes, copies data into the Pages artifact, and deploys `public/`. The local implementation does not deploy anything by itself.

For an initial Pages-only publication before the Gemini secret is available, manually run the workflow with `deploy_only` enabled. That mode deploys the current canonical report archive without generating or labeling a new AI report; scheduled runs and normal manual runs always execute the full analysis pipeline.

## Disclaimer

This project is an educational research interface, not financial advice or an execution system. Public endpoints may be delayed, unavailable, or regionally blocked. AI analysis may be wrong. Independently verify data and consult a qualified professional before making financial decisions.
