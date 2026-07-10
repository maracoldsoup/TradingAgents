"""Build no-LLM market snapshots from Toss Securities read-only APIs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from tradingagents.dataflows.toss_securities import (
    issue_access_token,
    read_only_get,
)

ReadOnlyGetter = Callable[[str, Mapping[str, Any] | None], dict[str, Any]]

KR_MARKETS = {"KOSPI", "KOSDAQ", "KONEX", "KRX", "NXT"}
US_MARKETS = {"NASDAQ", "NYSE", "AMEX", "ARCA", "NYSEARCA", "BATS"}


def normalize_toss_symbol(symbol: str) -> str:
    value = str(symbol or "").strip().upper()
    if not value:
        raise ValueError("symbol is required")
    if value.startswith("KR-"):
        value = value[3:]
    for suffix in (".KS", ".KQ", ".KR"):
        if value.endswith(suffix) and value[: -len(suffix)].isdigit():
            return value[: -len(suffix)]
    return value


def _result(probe: dict[str, Any]) -> Any:
    body = probe.get("body")
    if isinstance(body, dict):
        return body.get("result")
    return None


def _error(endpoint: str, probe: dict[str, Any]) -> dict[str, Any] | None:
    if probe.get("ok"):
        return None
    return {
        "endpoint": endpoint,
        "status": probe.get("status"),
        "stage": probe.get("stage"),
        "body": probe.get("body") or probe.get("error"),
    }


def _rate_limit(endpoint: str, probe: dict[str, Any]) -> dict[str, Any] | None:
    rate_limit = probe.get("rate_limit")
    if not isinstance(rate_limit, dict):
        return None
    return {"endpoint": endpoint, **rate_limit}


def _stock_rows(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    return []


def _price_rows(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    return []


def _candle_rows(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, dict) and isinstance(result.get("candles"), list):
        return [row for row in result["candles"] if isinstance(row, dict)]
    return []


def _calendar_family(stock: dict[str, Any], symbol: str) -> str | None:
    market = str(stock.get("market") or "").upper().replace(" ", "")
    currency = str(stock.get("currency") or "").upper()
    if market in KR_MARKETS or symbol.isdigit():
        return "KR"
    if market in US_MARKETS or currency == "USD":
        return "US"
    return None


def _live_getter(env: Mapping[str, str], timeout: float) -> ReadOnlyGetter:
    token_response = issue_access_token(env, timeout=timeout)
    access_token = token_response.get("access_token")
    if not access_token:
        raise RuntimeError(f"Toss token issuance failed: {token_response}")

    def getter(path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return read_only_get(
            env=env,
            access_token=access_token,
            path=path,
            params=params,
            timeout=timeout,
        )

    return getter


def collect_toss_market_snapshot(
    *,
    env: Mapping[str, str],
    symbols: list[str],
    candle_count: int = 60,
    trade_date: str | None = None,
    timeout: float = 10,
    getter: ReadOnlyGetter | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Collect stock, price, candle, FX, and calendar data without using an LLM."""
    normalized_symbols = [normalize_toss_symbol(symbol) for symbol in symbols]
    if not normalized_symbols:
        raise ValueError("At least one symbol is required")

    generated_at = generated_at or datetime.now()
    get = getter or _live_getter(env, timeout)
    errors: list[dict[str, Any]] = []
    rate_limits: list[dict[str, Any]] = []
    coverage: dict[str, Any] = {}

    def call(endpoint: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        probe = get(endpoint, params)
        error = _error(endpoint, probe)
        if error:
            errors.append(error)
        rate_limit = _rate_limit(endpoint, probe)
        if rate_limit:
            rate_limits.append(rate_limit)
        return probe

    symbols_param = ",".join(normalized_symbols)
    stocks_probe = call("/api/v1/stocks", {"symbols": symbols_param})
    prices_probe = call("/api/v1/prices", {"symbols": symbols_param})
    stocks = _stock_rows(_result(stocks_probe))
    prices = _price_rows(_result(prices_probe))
    coverage["stocks"] = bool(stocks)
    coverage["prices"] = bool(prices)

    candles: dict[str, list[dict[str, Any]]] = {}
    candle_coverage: dict[str, bool] = {}
    for symbol in normalized_symbols:
        candle_probe = call(
            "/api/v1/candles",
            {
                "symbol": symbol,
                "interval": "1d",
                "count": min(max(int(candle_count), 1), 200),
            },
        )
        rows = _candle_rows(_result(candle_probe))
        candles[symbol] = rows
        candle_coverage[symbol] = bool(rows)
    coverage["candles"] = candle_coverage

    by_symbol = {str(row.get("symbol") or "").upper(): row for row in stocks}
    families = sorted({
        family
        for symbol in normalized_symbols
        for family in [_calendar_family(by_symbol.get(symbol, {}), symbol)]
        if family
    })
    calendars: dict[str, Any] = {}
    for family in families:
        params = {"date": trade_date} if trade_date else None
        calendar_probe = call(f"/api/v1/market-calendar/{family}", params)
        calendars[family] = _result(calendar_probe)
    coverage["market_calendars"] = {key: bool(value) for key, value in calendars.items()}

    exchange_rate = None
    if any(str(row.get("currency") or "").upper() == "USD" for row in prices):
        fx_probe = call(
            "/api/v1/exchange-rate",
            {"baseCurrency": "USD", "quoteCurrency": "KRW"},
        )
        exchange_rate = _result(fx_probe)
    coverage["exchange_rate"] = bool(exchange_rate)

    return {
        "schema_version": 1,
        "artifact": "toss_market_snapshot",
        "source": "toss_securities_openapi",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "trade_date": trade_date,
        "symbols_requested": symbols,
        "symbols": normalized_symbols,
        "stocks": stocks,
        "prices": prices,
        "candles": candles,
        "exchange_rate": exchange_rate,
        "market_calendars": calendars,
        "coverage": coverage,
        "rate_limits": rate_limits,
        "errors": errors,
        "source_policy": {
            "llm_used": False,
            "path_scope": "read-only market, stock, FX, and calendar endpoints only",
            "blocked_scope": "account, asset, order, conditional-order, buy, sell, transfer",
        },
    }
