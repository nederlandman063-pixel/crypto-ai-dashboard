"""Daily market analysis pipeline for the crypto dashboard."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_data import fetch_market_snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORTS_PATH = REPO_ROOT / "data" / "reports.json"
DEFAULT_STATE_PATH = REPO_ROOT / "data" / "state.json"
MODEL = "gemini-2.5-flash"
SECTION_HEADINGS = (
    "## 1. Executive Summary",
    "## 2. Market Snapshot",
    "## 3. Portfolio Performance",
    "## 4. Risk & Active Orders",
    "## 5. Quantitative Outlook",
)
SYSTEM_INSTRUCTION = """You are a quantitative crypto portfolio analyst. Use only the supplied market snapshot, prior metrics, and state. Never claim an order filled or executed unless the state explicitly says so. Return concise Markdown with exactly these five section headings, in this order:
## 1. Executive Summary
## 2. Market Snapshot
## 3. Portfolio Performance
## 4. Risk & Active Orders
## 5. Quantitative Outlook
Discuss uncertainty and risk. Do not invent prices, metrics, events, or news. Do not add any other H1 or H2 headings."""


class PipelineError(RuntimeError):
    """Raised for a clear, actionable pipeline failure."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"Unable to load valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"Expected a JSON object in {path}")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def next_day(reports_document: dict[str, Any]) -> int:
    reports = reports_document.get("reports")
    if not isinstance(reports, list):
        raise PipelineError("reports.json must contain a reports array")
    days = [item.get("day") for item in reports if isinstance(item, dict)]
    if not days or any(not isinstance(day, int) or day < 1 for day in days):
        raise PipelineError("Every historical report must have a positive integer day")
    return max(days) + 1


def latest_report(reports_document: dict[str, Any]) -> dict[str, Any]:
    reports = reports_document.get("reports")
    if not isinstance(reports, list) or not reports:
        raise PipelineError("reports.json must contain at least one report")
    valid = [item for item in reports if isinstance(item, dict) and isinstance(item.get("day"), int)]
    if not valid:
        raise PipelineError("reports.json has no valid report objects")
    return max(valid, key=lambda item: item["day"])


def build_metrics(
    previous: dict[str, Any],
    snapshot: dict[str, Any],
    initial_capital_usd: float,
) -> dict[str, Any]:
    previous_metrics = previous.get("metrics")
    if not isinstance(previous_metrics, dict):
        raise PipelineError("Previous report has no metrics object")
    previous_allocations = previous_metrics.get("allocations")
    if not isinstance(previous_allocations, list):
        raise PipelineError("Previous report metrics has no allocations array")
    markets = snapshot.get("markets")
    if not isinstance(markets, dict):
        raise PipelineError("Market snapshot has no markets object")

    allocations: list[dict[str, Any]] = []
    holdings_total = 0.0
    cash_reserve = float(previous_metrics.get("cash_reserve_usd", 0.0))
    reserved_for_limits = float(previous_metrics.get("reserved_for_limits_usd", 0.0))

    for allocation in previous_allocations:
        if not isinstance(allocation, dict):
            raise PipelineError("Allocation entries must be objects")
        updated = deepcopy(allocation)
        symbol = updated.get("symbol")
        if symbol == "USDT":
            updated["value_usd"] = round(cash_reserve, 2)
        else:
            quantity = updated.get("quantity")
            market = markets.get(f"{symbol}USDT")
            if not isinstance(quantity, (int, float)) or not isinstance(market, dict):
                raise PipelineError(f"Cannot value allocation {symbol!r}")
            try:
                price = float(market["last"])
            except (KeyError, TypeError, ValueError) as exc:
                raise PipelineError(f"Snapshot has no valid last price for {symbol}USDT") from exc
            updated["price_usd"] = round(price, 8)
            updated["value_usd"] = round(float(quantity) * price, 2)
            holdings_total += updated["value_usd"]
        allocations.append(updated)

    portfolio_value = round(holdings_total + cash_reserve + reserved_for_limits, 2)
    pnl_usd = round(portfolio_value - initial_capital_usd, 2)
    pnl_percent = round((pnl_usd / initial_capital_usd) * 100, 2)
    cash_ratio = round((cash_reserve / portfolio_value) * 100, 2) if portfolio_value else 0.0
    fear_greed = snapshot.get("fear_greed")
    if not isinstance(fear_greed, int):
        raise PipelineError("Snapshot has no integer Fear & Greed score")

    return {
        "portfolio_value": portfolio_value,
        "pnl_usd": pnl_usd,
        "pnl_percent": pnl_percent,
        "cash_reserve_usd": round(cash_reserve, 2),
        "reserved_for_limits_usd": round(reserved_for_limits, 2),
        "cash_ratio": cash_ratio,
        "fear_greed": fear_greed,
        "btc_dominance": previous_metrics.get("btc_dominance"),
        "allocations": allocations,
    }


def build_prompt(
    day: int,
    snapshot: dict[str, Any],
    previous_metrics: dict[str, Any],
    state: dict[str, Any],
    current_metrics: dict[str, Any],
) -> str:
    payload = {
        "day": day,
        "market_snapshot": snapshot,
        "previous_metrics": previous_metrics,
        "current_revalued_metrics": current_metrics,
        "portfolio_and_order_state": state,
    }
    return (
        "Produce today's report from this JSON input. Preserve the exact five required "
        "headings and distinguish pending orders from executions.\n\n"
        + json.dumps(payload, indent=2, sort_keys=True)
    )


def generate_with_gemini(prompt: str, api_key: str) -> str:
    if not api_key:
        raise PipelineError("GEMINI_API_KEY is required; no report was generated")
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise PipelineError("google-genai is not installed; install scripts/requirements.txt") from exc

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION),
        )
        text = response.text
    except Exception as exc:
        raise PipelineError(f"Gemini report generation failed: {exc}") from exc
    if not isinstance(text, str) or not text.strip():
        raise PipelineError("Gemini returned an empty report")
    return text.strip()


def validate_report_markdown(content: str) -> None:
    positions = [content.find(heading) for heading in SECTION_HEADINGS]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise PipelineError("AI report must contain the five required section headings in order")


def run_pipeline(
    *,
    reports_path: Path = DEFAULT_REPORTS_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    snapshot_fetcher: Callable[[], dict[str, Any]] = fetch_market_snapshot,
    report_generator: Callable[[str], str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    reports_document = load_json(reports_path)
    state = load_json(state_path)
    previous = latest_report(reports_document)
    day = next_day(reports_document)
    initial_capital = reports_document.get("initial_capital_usd")
    if not isinstance(initial_capital, (int, float)) or initial_capital <= 0:
        raise PipelineError("reports.json must define a positive initial_capital_usd")

    api_key: str | None = None
    if report_generator is None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise PipelineError("GEMINI_API_KEY is required; no report was generated")

    snapshot = snapshot_fetcher()
    metrics = build_metrics(previous, snapshot, float(initial_capital))
    prompt = build_prompt(day, snapshot, previous["metrics"], state, metrics)
    if report_generator is None:
        content = generate_with_gemini(prompt, api_key or "")
    else:
        content = report_generator(prompt)
    if not isinstance(content, str) or not content.strip():
        raise PipelineError("Report generator returned no Markdown")
    content = content.strip()
    validate_report_markdown(content)

    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    report = {
        "day": day,
        "date": timestamp.date().isoformat(),
        "title": f"Day {day} Quantitative Crypto Brief",
        "content": content,
        "metrics": metrics,
        "market_snapshot": snapshot,
    }
    reports_document["reports"].insert(0, report)

    state["updated_at"] = timestamp.isoformat()
    execution = state.setdefault("execution", {})
    if not isinstance(execution, dict):
        raise PipelineError("state.execution must be an object")
    execution.update(
        {
            "last_success_at": timestamp.isoformat(),
            "last_report_day": day,
            "last_snapshot_at": snapshot.get("as_of"),
            "model": MODEL,
            "orders_executed_by_pipeline": False,
        }
    )

    # Generate and validate both documents before replacing either destination.
    json.dumps(reports_document, allow_nan=False)
    json.dumps(state, allow_nan=False)
    atomic_write_json(reports_path, reports_document)
    atomic_write_json(state_path, state)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS_PATH)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = run_pipeline(reports_path=args.reports, state_path=args.state)
    except PipelineError as exc:
        raise SystemExit(f"Pipeline failed: {exc}") from exc
    print(f"Created Day {report['day']} report for {report['date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
