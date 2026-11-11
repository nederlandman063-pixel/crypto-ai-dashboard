# Binance liquidation collector

This small Cloud Run service keeps a rolling 24-hour sample of public Binance
USD-M liquidation events for the eight assets tracked by the dashboard. It does
not require a Binance API key.

Endpoints:

- `GET /health` — connection and collector status.
- `GET /summary` — aggregate totals consumed by the daily GitHub Actions job.

Runtime configuration:

- `LIQUIDATION_BUCKET` — Google Cloud Storage bucket used to survive restarts.
- `LIQUIDATION_OBJECT` — optional object name; defaults to
  `liquidations/events.json`.

The service needs exactly one continuously allocated instance. Running multiple
instances would double-count the same public stream. Binance emits at most the
latest liquidation event per symbol in each 1000 ms interval, so the aggregate
is explicitly reported as a sampled lower bound rather than exchange-wide
ground truth.
