"""Daily market analysis pipeline for the crypto dashboard."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from market_data import fetch_market_snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORTS_PATH = REPO_ROOT / "data" / "reports.json"
DEFAULT_STATE_PATH = REPO_ROOT / "data" / "state.json"
MODEL = "gemini-3.8-flash"
GEMINI_API_VERSION = "v1beta1"
MAX_REPORT_ATTEMPTS = 3
MIN_REPORT_CYRILLIC_CHARS = 1800
ASSET_SYMBOLS = ("BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "LINK")
SECTION_HEADINGS = (
    "## 1. Ретроспективный разбор прогноза и статус портфеля",
    "## 2. Мониторинг деривативов",
    "## 3. Макро-сантимент и ончейн-структура",
    "## 4. Сводная таблица 8 активов",
    "## 5. Практические сценарии для модели 1 BTC + $20,000 USDT",
    "## 6. Решение дня без автоматического исполнения",
    "## 7. Итоговая структура отслеживаемого портфеля",
)
TABLE_COLUMNS = (
    "Тикер",
    "Максимум 24ч",
    "Минимум 24ч",
    "Последняя цена",
    "Изменение 24ч, %",
    "Объём 24ч",
    "Фандинг",
    "Перспектива 24–72ч",
)
MODEL_BALANCE_LINE = (
    "Модельный баланс (отдельно от отслеживаемого портфеля): 1 BTC + $20,000 USDT."
)
SYSTEM_INSTRUCTION = """Вы — ведущий количественный аналитик криптовалютного портфеля. Подготовьте содержательный ежедневный отчёт уровня профессиональной инвестиционной записки: связывайте прогноз прошлого дня с фактом, объясняйте причинно-следственные связи, оценивайте влияние рынка на портфель и формулируйте конкретные сценарии с рисками. Ориентир по объёму — 1 200–1 800 русских слов; не сокращайте анализ до перечня цифр.

Используйте только предоставленный JSON. Не придумывайте цены, RSI, netflow, открытый интерес, ликвидации, карты ликвидности, макроэкономические или ончейн-метрики, новости, исполнения и факты заполнения ордеров. Если показателя нет, прямо напишите, что он недоступен во входных данных, и не заменяйте его оценкой. Границы high_24h и low_24h можно интерпретировать только как границы суточного диапазона, а не как доказанные технические уровни. Чётко разделяйте: (1) проверяемый факт из JSON, (2) аналитический вывод, (3) условную рекомендацию.

Весь аналитический текст должен быть написан на русском языке. Английский допустим только для тикеров, идентификаторов ордеров, имён полей API и общепринятых технических обозначений. Если предыдущий отчёт написан на английском, изложите его тезисы и результаты по-русски.

Верните Markdown ровно с семью следующими заголовками H2, дословно и в указанном порядке. Не добавляйте другие заголовки H1 или H2:
## 1. Ретроспективный разбор прогноза и статус портфеля
## 2. Мониторинг деривативов
## 3. Макро-сантимент и ончейн-структура
## 4. Сводная таблица 8 активов
## 5. Практические сценарии для модели 1 BTC + $20,000 USDT
## 6. Решение дня без автоматического исполнения
## 7. Итоговая структура отслеживаемого портфеля

Раздел 1. Начните с точной строки: `Достигнут означает, что уровень триггера находится внутри предоставленного диапазона максимум/минимум за 24 часа; не достигнут означает, что он находится вне диапазона; неопределённо означает, что текущих значений максимума, минимума или последней цены недостаточно. Касание не доказывает исполнение.` Сначала перескажите базовый сценарий и ключевые триггеры предыдущего отчёта. Затем сопоставьте их с фактическим суточным диапазоном. Для каждого ордера из state укажите id, статус, символ и точные high_24h, low_24h и last; классифицируйте уровень как «достигнут», «не достигнут» или «неопределённо». Отдельно дайте строки `Оценка сценария прошлого отчёта:` и `Статус отслеживаемого портфеля:`. Оценка сценария может быть только «подтверждён», «частично подтверждён», «не подтверждён» или «недостаточно данных»; не назначайте вымышленный процент точности. Объясните, как движение каждого удерживаемого актива изменило его текущую стоимость и общий PnL.

Раздел 2. Для каждого доступного значения фандинга приведите один пункт строго в формате `- BTCUSDT ставка фандинга (lastFundingRate): 0.00001`, подставив точные исходные символ и значение. После списка добавьте `Интерпретация фандинга:` и сравните знак и относительную величину ставок между восемью активами без внешних порогов. Обязательно включите точные строки `Данные о ликвидациях: недоступны (не предоставлены во входных данных).` и `Открытый интерес: недоступен (не предоставлен во входных данных).` Не упоминайте Coinglass или CoinAnk как источник, поскольку их данных нет во входном JSON.

Раздел 3. Используйте строки `Индекс страха и жадности: <точное значение>` и `Доминирование BTC: <точное значение>%`, если значения доступны. Обязательно добавьте `Дополнительные макроданные: недоступны (не предоставлены во входных данных).` и `Ончейн-данные: недоступны (не предоставлены во входных данных).` Затем дайте строку `Рыночный режим:` и сформулируйте режим только из суточной динамики восьми активов, положения последних цен внутри диапазонов, фандинга и индекса настроений. Явно отметьте, что доминирование BTC перенесено из предыдущего отчёта, если у него нет свежей временной метки.

Раздел 4. Включите одну Markdown-таблицу без списков активов. Используйте точный заголовок: `| Тикер | Максимум 24ч | Минимум 24ч | Последняя цена | Изменение 24ч, % | Объём 24ч | Фандинг | Перспектива 24–72ч |`. Точно скопируйте исходные значения снимка и добавьте ровно следующие строки в этом порядке: BTC, ETH, SOL, BNB, XRP, ADA, DOGE, LINK. В столбце перспективы дайте краткую русскую оценку, основанную только на этих полях. После таблицы добавьте `Сравнительный вывод:` и назовите лидеров и аутсайдеров по фактическому процентному изменению, не приписывая несуществующие драйверы.

Раздел 5. Начните с точной строки `Модельный баланс (отдельно от отслеживаемого портфеля): 1 BTC + $20,000 USDT.` Рассчитайте его текущую оценку как 1 BTC по last + $20,000 USDT и явно не смешивайте с отслеживаемым портфелем. Дайте ровно три сценария: покупка на снижении, фиксация прибыли и защитное сокращение риска. Каждый сценарий должен начинаться отдельной строкой `- Если`, содержать цену условия, точный размер в BTC или USDT, цель сценария и главный риск. Используйте только уровни, выводимые из предоставленного суточного диапазона; не называйте их гарантированной поддержкой или сопротивлением.

Раздел 6. Начните со строки `Решение дня:`. Дайте не менее трёх нумерованных рекомендаций по отслеживаемому портфелю и активным ордерам: что сохранить, что пересмотреть и при каком проверяемом условии. Это рекомендации, они не меняют state и не являются исполненными сделками. Укажите `Статусы ордеров не изменены.` и завершите раздел точной строкой `Этот отчёт не исполняет сделки.`

Раздел 7. Начните со строки `Стоимость отслеживаемого портфеля: <точное portfolio_value> USD.` Затем дословно используйте строки `PnL: <точное pnl_usd> USD (<точное pnl_percent>%).`, `Свободный денежный резерв: <точное cash_reserve_usd> USD.`, `Зарезервировано под лимитные заявки: <точное reserved_for_limits_usd> USD.` и `Доля ликвидного резерва: <точное cash_ratio>%.` Включите Markdown-таблицу по всем allocations с символом, количеством, ценой (если есть), стоимостью и ролью в портфеле. Не меняйте количества и не считайте зарезервированные средства второй раз. Завершите кратким выводом о концентрации и ликвидности портфеля.

Во всём отчёте обсуждайте неопределённость и риск без неподтверждённых фактов. Сохраняйте профессиональный, конкретный и численно насыщенный стиль примера, но не копируйте его цифры, источники или торговые решения."""


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
    previous_report: dict[str, Any],
    state: dict[str, Any],
    current_metrics: dict[str, Any],
) -> str:
    payload = {
        "day": day,
        "market_snapshot": snapshot,
        "previous_report": previous_report,
        "current_revalued_metrics": current_metrics,
        "portfolio_and_order_state": state,
    }
    return (
        "Подготовьте углублённый сегодняшний аналитический отчёт на русском языке по этим входным данным JSON. "
        "Соблюдайте все требования к формату и фактам из системной инструкции. Копируйте "
        "числовые значения снимка без округления и отличайте касание уровня в диапазоне "
        "от факта исполнения.\n\n"
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
        client = genai.Client(
            vertexai=True,
            api_key=api_key,
            http_options=types.HttpOptions(api_version=GEMINI_API_VERSION),
        )
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


def _split_markdown_row(line: str) -> list[str]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    return [cell.strip() for cell in value.split("|")]


def _decimal(value: Any, label: str) -> Decimal:
    cleaned = str(value).strip()
    for token in ("`", "**", "$", ",", "%"):
        cleaned = cleaned.replace(token, "")
    try:
        result = Decimal(cleaned)
    except InvalidOperation as exc:
        raise PipelineError(f"{label} must be an unrounded numeric value, got {value!r}") from exc
    if not result.is_finite():
        raise PipelineError(f"{label} must be finite")
    return result


def _require_matching_number(actual: Any, expected: Any, label: str) -> None:
    if _decimal(actual, label) != _decimal(expected, label):
        raise PipelineError(f"{label} does not match the supplied snapshot value")


def _numbers_in_text(content: str) -> set[Decimal]:
    values: set[Decimal] = set()
    pattern = r"(?<![A-Za-z0-9.])\$?[-+]?(?:\d[\d,]*\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
    for match in re.finditer(pattern, content):
        values.add(_decimal(match.group(0), "report number"))
    return values


def _extract_sections(content: str) -> dict[str, str]:
    if re.search(r"(?m)^```", content):
        raise PipelineError("AI report must be renderable Markdown, not a fenced code block")
    matches = list(re.finditer(r"(?m)^#{1,2}\s+.+?\s*$", content))
    headings = [match.group(0).strip() for match in matches]
    if headings != list(SECTION_HEADINGS):
        raise PipelineError(
            "AI report must contain exactly the seven required H2 section headings in order"
        )
    return {
        heading: content[match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(content)].strip()
        for index, (heading, match) in enumerate(zip(SECTION_HEADINGS, matches, strict=True))
    }


def _validate_russian_language(content: str) -> None:
    cyrillic_count = len(re.findall(r"[А-Яа-яЁё]", content))
    latin_count = len(re.findall(r"[A-Za-z]", content))
    if cyrillic_count < MIN_REPORT_CYRILLIC_CHARS or cyrillic_count <= latin_count:
        raise PipelineError("AI report must be written predominantly in Russian")

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("|"):
            continue
        if re.search(
            r"\b[A-Za-z]{2,}\b(?:\s+\b[A-Za-z]{2,}\b){2,}", stripped
        ):
            raise PipelineError("AI report contains an English-language prose line")


def _validate_comparative_table(section: str, snapshot: dict[str, Any]) -> None:
    lines = section.splitlines()
    table_start: int | None = None
    for index in range(len(lines) - 1):
        header = _split_markdown_row(lines[index])
        separator = _split_markdown_row(lines[index + 1])
        if (
            len(header) == len(TABLE_COLUMNS)
            and tuple(header) == TABLE_COLUMNS
            and len(separator) == len(header)
            and all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator)
        ):
            if table_start is not None:
                raise PipelineError("Section 4 must contain exactly one comparative table")
            table_start = index
    if table_start is None:
        raise PipelineError("Section 4 must contain the required valid Markdown table")

    rows: list[list[str]] = []
    for line in lines[table_start + 2 :]:
        if not line.strip() or "|" not in line:
            break
        row = _split_markdown_row(line)
        if len(row) != len(TABLE_COLUMNS):
            raise PipelineError("Every comparative table row must have exactly eight cells")
        rows.append(row)

    symbols = [row[0].replace("`", "").replace("**", "").strip() for row in rows]
    if symbols != list(ASSET_SYMBOLS):
        raise PipelineError(
            "Comparative table must have exactly BTC, ETH, SOL, BNB, XRP, ADA, DOGE, LINK rows in order"
        )

    markets = snapshot.get("markets")
    if not isinstance(markets, dict):
        raise PipelineError("Cannot validate report table without snapshot markets")
    fields = ("high_24h", "low_24h", "last", "percent_change_24h", "volume_24h")
    for row, symbol in zip(rows, ASSET_SYMBOLS, strict=True):
        market = markets.get(f"{symbol}USDT")
        if not isinstance(market, dict):
            raise PipelineError(f"Snapshot is missing {symbol}USDT for table validation")
        for cell, field in zip(row[1:6], fields, strict=True):
            if field not in market:
                raise PipelineError(f"Snapshot is missing {symbol}USDT {field}")
            _require_matching_number(cell, market[field], f"{symbol} table {field}")
        funding = market.get("last_funding_rate")
        if funding is None:
            if not re.search(r"(?i)недоступ", row[6]):
                raise PipelineError(f"{symbol} table funding must identify unavailable data")
        else:
            _require_matching_number(row[6], funding, f"{symbol} table last_funding_rate")
        if not re.search(r"[А-Яа-яЁё]", row[7]):
            raise PipelineError(f"{symbol} table outlook must be written in Russian")
    if not re.search(r"(?im)^Сравнительный вывод:", section):
        raise PipelineError("Section 4 must include a comparative conclusion")


def _validate_funding(section: str, snapshot: dict[str, Any]) -> None:
    markets = snapshot.get("markets")
    if not isinstance(markets, dict):
        raise PipelineError("Cannot validate funding references without snapshot markets")
    pattern = re.compile(
        r"(?im)^\s*[-*]\s*([A-Z]+USDT)\s+ставка фандинга "
        r"\(lastFundingRate\):\s*`?([-+0-9.eE]+)`?\s*$"
    )
    references = pattern.findall(section)
    actual = {symbol: value for symbol, value in references}
    expected = {
        f"{symbol}USDT": markets[f"{symbol}USDT"]["last_funding_rate"]
        for symbol in ASSET_SYMBOLS
        if isinstance(markets.get(f"{symbol}USDT"), dict)
        and markets[f"{symbol}USDT"].get("last_funding_rate") is not None
    }
    if len(references) != len(actual) or set(actual) != set(expected):
        raise PipelineError("Section 2 must cite every available lastFundingRate exactly once")
    for symbol, expected_value in expected.items():
        _require_matching_number(actual[symbol], expected_value, f"{symbol} lastFundingRate")
    if not re.search(r"(?i)Данные о ликвидациях:\s*недоступны", section):
        raise PipelineError("Section 2 must explicitly state that liquidation data is unavailable")
    if not re.search(r"(?i)Открытый интерес:\s*недоступен", section):
        raise PipelineError("Section 2 must explicitly state that open-interest data is unavailable")
    if not re.search(r"(?im)^Интерпретация фандинга:", section):
        raise PipelineError("Section 2 must interpret the supplied funding rates")


def _validate_sentiment(section: str, current_metrics: dict[str, Any]) -> None:
    fear_greed = current_metrics.get("fear_greed")
    fear_match = re.search(
        r"(?im)^Индекс страха и жадности:\s*([-+0-9.eE]+)\s*$", section
    )
    if fear_match is None:
        raise PipelineError("Section 3 must cite the supplied Fear & Greed value")
    _require_matching_number(fear_match.group(1), fear_greed, "Fear & Greed")

    dominance = current_metrics.get("btc_dominance")
    dominance_match = re.search(
        r"(?im)^Доминирование BTC:\s*([-+0-9.eE]+)%?\s*$", section
    )
    if dominance is None:
        if not re.search(r"(?i)Доминирование BTC:\s*недоступно", section):
            raise PipelineError("Section 3 must identify unavailable BTC dominance")
    elif dominance_match is None:
        raise PipelineError("Section 3 must cite the supplied BTC dominance value")
    else:
        _require_matching_number(dominance_match.group(1), dominance, "BTC dominance")

    if not re.search(r"(?i)Дополнительные макроданные:\s*недоступны", section):
        raise PipelineError("Section 3 must identify unavailable additional macro data")
    if not re.search(r"(?i)Ончейн-данные:\s*недоступны", section):
        raise PipelineError("Section 3 must identify unavailable onchain data")
    if not re.search(r"(?im)^Рыночный режим:", section):
        raise PipelineError("Section 3 must state the market regime")


def _validate_portfolio_summary(section: str, current_metrics: dict[str, Any]) -> None:
    patterns = (
        (r"(?im)^Стоимость отслеживаемого портфеля:\s*([-+0-9.eE]+)\s+USD\.\s*$", "portfolio_value", "portfolio value"),
        (r"(?im)^PnL:\s*([-+0-9.eE]+)\s+USD\s*\(([-+0-9.eE]+)%\)\.\s*$", "pnl_usd", "PnL"),
        (r"(?im)^Свободный денежный резерв:\s*([-+0-9.eE]+)\s+USD\.\s*$", "cash_reserve_usd", "cash reserve"),
        (r"(?im)^Зарезервировано под лимитные заявки:\s*([-+0-9.eE]+)\s+USD\.\s*$", "reserved_for_limits_usd", "reserved limit cash"),
        (r"(?im)^Доля ликвидного резерва:\s*([-+0-9.eE]+)%\.\s*$", "cash_ratio", "cash ratio"),
    )
    for pattern, metric, label in patterns:
        match = re.search(pattern, section)
        if match is None:
            raise PipelineError(f"Section 7 must cite the exact {label}")
        _require_matching_number(match.group(1), current_metrics.get(metric), label)
        if metric == "pnl_usd":
            _require_matching_number(match.group(2), current_metrics.get("pnl_percent"), "PnL percent")

    allocations = current_metrics.get("allocations")
    if not isinstance(allocations, list) or not allocations:
        raise PipelineError("Current metrics must contain portfolio allocations")
    section_numbers = _numbers_in_text(section)
    for allocation in allocations:
        if not isinstance(allocation, dict) or not isinstance(allocation.get("symbol"), str):
            raise PipelineError("Current metrics contain an invalid allocation")
        symbol = allocation["symbol"]
        if not re.search(rf"(?m)^\|\s*{re.escape(symbol)}\s*\|", section):
            raise PipelineError(f"Section 7 must include the {symbol} allocation row")
        for field in ("quantity", "value_usd"):
            expected = allocation.get(field)
            if _decimal(expected, f"{symbol} allocation {field}") not in section_numbers:
                raise PipelineError(f"Section 7 must cite exact {symbol} allocation {field}")


def validate_report_markdown(
    content: str,
    *,
    snapshot: dict[str, Any],
    current_metrics: dict[str, Any],
    state: dict[str, Any],
) -> None:
    sections = _extract_sections(content)
    _validate_russian_language(content)
    retrospective = sections[SECTION_HEADINGS[0]]
    for definition in (
        r"Достигнут означает\b",
        r"не достигнут означает\b",
        r"неопределённо означает\b",
    ):
        if not re.search(definition, retrospective, re.IGNORECASE):
            raise PipelineError("Section 1 must define touched, not touched, and indeterminate")
    for field in ("максимум", "минимум", "последняя цена"):
        if not re.search(rf"\b{field}\b", retrospective, re.IGNORECASE):
            raise PipelineError(f"Section 1 must compare current {field} data")
    if not re.search(r"(?i)(?:не доказывает|не означает).{0,30}исполнени", retrospective):
        raise PipelineError("Section 1 must not represent a range touch as execution")
    if not re.search(r"(?im)^Оценка сценария прошлого отчёта:", retrospective):
        raise PipelineError("Section 1 must evaluate the previous report scenario")
    if not re.search(r"(?im)^Статус отслеживаемого портфеля:", retrospective):
        raise PipelineError("Section 1 must state the tracked portfolio status")
    orders = state.get("orders")
    referenced_symbols: set[str] = set()
    if isinstance(orders, list):
        for order in orders:
            if isinstance(order, dict) and isinstance(order.get("id"), str):
                if order["id"] not in retrospective:
                    raise PipelineError(f"Section 1 must assess prior trigger {order['id']}")
                symbol = order.get("symbol")
                if isinstance(symbol, str):
                    referenced_symbols.add(symbol)
    markets = snapshot.get("markets")
    if not isinstance(markets, dict):
        raise PipelineError("Cannot validate retrospective values without snapshot markets")
    retrospective_numbers = _numbers_in_text(retrospective)
    for symbol in referenced_symbols:
        market = markets.get(symbol)
        if not isinstance(market, dict):
            raise PipelineError(f"Snapshot is missing {symbol} for retrospective validation")
        for field in ("high_24h", "low_24h", "last"):
            expected = market.get(field)
            if _decimal(expected, f"{symbol} {field}") not in retrospective_numbers:
                raise PipelineError(
                    f"Section 1 must cite exact current {symbol} {field} value"
                )

    _validate_funding(sections[SECTION_HEADINGS[1]], snapshot)
    _validate_sentiment(sections[SECTION_HEADINGS[2]], current_metrics)
    _validate_comparative_table(sections[SECTION_HEADINGS[3]], snapshot)

    practical = sections[SECTION_HEADINGS[4]]
    if MODEL_BALANCE_LINE not in practical:
        raise PipelineError("Section 5 must identify the separate 1 BTC + $20,000 USDT model balance")
    trigger_lines = re.findall(r"(?im)^\s*[-*]\s+Если\b.*$", practical)
    if len(trigger_lines) != 3:
        raise PipelineError("Section 5 must provide exactly three conditional '- If' scenarios with sizing")
    for trigger in trigger_lines:
        if len(re.findall(r"[-+]?\d[\d,.]*", trigger)) < 2 or not re.search(
            r"\b(?:BTC|USDT)\b", trigger
        ):
            raise PipelineError("Every Section 5 trigger must include a price and explicit BTC/USDT sizing")

    decision = sections[SECTION_HEADINGS[5]]
    if not re.search(r"(?im)^Решение дня:", decision):
        raise PipelineError("Section 6 must begin with the daily decision")
    recommendations = re.findall(r"(?m)^\s*\d+[.)]\s+.+$", decision)
    if len(recommendations) < 3:
        raise PipelineError("Section 6 must contain at least three numbered recommendations")
    if "Статусы ордеров не изменены." not in decision:
        raise PipelineError("Section 6 must preserve order statuses")
    if not re.search(r"(?m)^Этот отчёт не исполняет сделки\.\s*$", decision):
        raise PipelineError("Section 6 must state that the report executes no trades")

    _validate_portfolio_summary(sections[SECTION_HEADINGS[6]], current_metrics)


def generate_validated_report(
    prompt: str,
    generator: Callable[[str], str],
    *,
    snapshot: dict[str, Any],
    current_metrics: dict[str, Any],
    state: dict[str, Any],
    max_attempts: int = MAX_REPORT_ATTEMPTS,
) -> str:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least one")
    attempt_prompt = prompt
    last_error: PipelineError | None = None
    for attempt in range(1, max_attempts + 1):
        content = generator(attempt_prompt)
        if not isinstance(content, str) or not content.strip():
            last_error = PipelineError("Report generator returned no Markdown")
        else:
            content = content.strip()
            try:
                validate_report_markdown(
                    content,
                    snapshot=snapshot,
                    current_metrics=current_metrics,
                    state=state,
                )
                return content
            except PipelineError as exc:
                last_error = exc
        if attempt < max_attempts:
            attempt_prompt = (
                "Исправьте предыдущий ответ, полностью переписав отчёт на русском языке. "
                f"Он не прошёл детерминированную проверку: {last_error}. Верните только "
                "исправленный Markdown.\n\n"
                f"ПРЕДЫДУЩИЙ НЕКОРРЕКТНЫЙ ОТВЕТ:\n"
                f"{content if isinstance(content, str) else ''}\n\n"
                f"ИСХОДНЫЕ ВХОДНЫЕ ДАННЫЕ:\n{prompt}"
            )
    raise PipelineError(
        f"AI report failed structural validation after {max_attempts} attempts: {last_error}"
    )


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
    prompt = build_prompt(day, snapshot, previous, state, metrics)
    if report_generator is None:
        generator = lambda value: generate_with_gemini(value, api_key or "")
    else:
        generator = report_generator
    content = generate_validated_report(
        prompt,
        generator,
        snapshot=snapshot,
        current_metrics=metrics,
        state=state,
    )

    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    report = {
        "day": day,
        "date": timestamp.date().isoformat(),
        "title": f"День {day}: количественный обзор крипторынка",
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
