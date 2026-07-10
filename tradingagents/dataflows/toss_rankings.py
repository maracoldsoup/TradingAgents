"""Build no-LLM Toss Securities ranking snapshots (top gainers/losers, volume).

This is the read-only "notable mover" source for the content pipeline. It
never derives its own gainer/loser judgment from candles — it quotes the
ranking Toss already computed for `TOP_GAINERS` / `TOP_LOSERS` and friends.

Endpoint reference (developers.tossinvest.com, `GET /api/v1/rankings`):

- `type`: MARKET_TRADING_AMOUNT, MARKET_TRADING_VOLUME, TOP_GAINERS,
  TOP_LOSERS, TOSS_SECURITIES_TRADING_AMOUNT, TOSS_SECURITIES_TRADING_VOLUME
- `marketCountry`: KR, US
- `duration`: realtime, 1d, 1w, 1mo, 3mo, 6mo, 1y
  (`TOP_GAINERS` / `TOP_LOSERS` do not support `realtime`)
- `excludeInvestmentCaution`: bool
- `count`: 1-100
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from tradingagents.dataflows.toss_securities import issue_access_token, read_only_get


ReadOnlyGetter = Callable[[str, Mapping[str, Any] | None], dict[str, Any]]

MARKET_COUNTRIES = ("KR", "US")
DEFAULT_RANKING_TYPES = ("TOP_GAINERS", "TOP_LOSERS")
REALTIME_UNSUPPORTED_TYPES = {"TOP_GAINERS", "TOP_LOSERS"}
VALID_RANKING_TYPES = {
    "MARKET_TRADING_AMOUNT",
    "MARKET_TRADING_VOLUME",
    "TOP_GAINERS",
    "TOP_LOSERS",
    "TOSS_SECURITIES_TRADING_AMOUNT",
    "TOSS_SECURITIES_TRADING_VOLUME",
}
VALID_DURATIONS = {"realtime", "1d", "1w", "1mo", "3mo", "6mo", "1y"}


def _result(probe: dict[str, Any]) -> Any:
    body = probe.get("body")
    if isinstance(body, dict):
        return body.get("result")
    return None


def _error(endpoint: str, params: Mapping[str, Any], probe: dict[str, Any]) -> dict[str, Any] | None:
    if probe.get("ok"):
        return None
    return {
        "endpoint": endpoint,
        "params": dict(params),
        "status": probe.get("status"),
        "stage": probe.get("stage"),
        "body": probe.get("body") or probe.get("error"),
    }


def _rate_limit(endpoint: str, probe: dict[str, Any]) -> dict[str, Any] | None:
    rate_limit = probe.get("rate_limit")
    if not isinstance(rate_limit, dict):
        return None
    return {"endpoint": endpoint, **rate_limit}


def _ranking_rows(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, dict) and isinstance(result.get("rankings"), list):
        return [row for row in result["rankings"] if isinstance(row, dict)]
    return []


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


def collect_toss_rankings_snapshot(
    *,
    env: Mapping[str, str],
    market_countries: tuple[str, ...] = MARKET_COUNTRIES,
    ranking_types: tuple[str, ...] = DEFAULT_RANKING_TYPES,
    duration: str = "1d",
    count: int = 50,
    exclude_investment_caution: bool = True,
    timeout: float = 10,
    getter: ReadOnlyGetter | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Collect ranking snapshots (top gainers/losers, volume, trading amount).

    Every gainer/loser judgment here is Toss's own ranking result, quoted
    as-is. No thresholding or derived "notable mover" logic lives here.
    """
    if not market_countries:
        raise ValueError("At least one market country is required")
    if not ranking_types:
        raise ValueError("At least one ranking type is required")
    unknown_types = set(ranking_types) - VALID_RANKING_TYPES
    if unknown_types:
        raise ValueError(f"Unknown ranking type(s): {sorted(unknown_types)}")
    if duration not in VALID_DURATIONS:
        raise ValueError(f"Unknown duration: {duration}")
    if duration == "realtime" and set(ranking_types) & REALTIME_UNSUPPORTED_TYPES:
        raise ValueError(
            "TOP_GAINERS/TOP_LOSERS do not support duration=realtime (Toss returns "
            "400 unsupported-ranking-duration)"
        )

    generated_at = generated_at or datetime.now()
    get = getter or _live_getter(env, timeout)
    errors: list[dict[str, Any]] = []
    rate_limits: list[dict[str, Any]] = []
    rankings: dict[str, dict[str, list[dict[str, Any]]]] = {}
    ranked_at: dict[str, dict[str, str | None]] = {}
    coverage: dict[str, dict[str, bool]] = {}

    count = min(max(int(count), 1), 100)

    for market_country in market_countries:
        rankings[market_country] = {}
        ranked_at[market_country] = {}
        coverage[market_country] = {}
        for ranking_type in ranking_types:
            params = {
                "type": ranking_type,
                "marketCountry": market_country,
                "duration": duration,
                "excludeInvestmentCaution": exclude_investment_caution,
                "count": count,
            }
            probe = get("/api/v1/rankings", params)
            error = _error("/api/v1/rankings", params, probe)
            if error:
                errors.append(error)
            rate_limit = _rate_limit("/api/v1/rankings", probe)
            if rate_limit:
                rate_limits.append(rate_limit)

            result = _result(probe)
            rows = _ranking_rows(result)
            rankings[market_country][ranking_type] = rows
            ranked_at[market_country][ranking_type] = (
                result.get("rankedAt") if isinstance(result, dict) else None
            )
            coverage[market_country][ranking_type] = bool(rows)

    return {
        "schema_version": 1,
        "artifact": "toss_rankings_snapshot",
        "source": "toss_securities_openapi",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "duration": duration,
        "count": count,
        "market_countries": list(market_countries),
        "ranking_types": list(ranking_types),
        "rankings": rankings,
        "ranked_at": ranked_at,
        "coverage": coverage,
        "rate_limits": rate_limits,
        "errors": errors,
        "source_policy": {
            "llm_used": False,
            "path_scope": "read-only ranking endpoint only",
            "blocked_scope": "account, asset, order, conditional-order, buy, sell, transfer",
        },
    }


def notable_symbols(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a rankings snapshot into a symbol -> ranking-membership list.

    Each row quotes the ranking(s) a symbol appeared in; it does not compute
    a new judgment. A symbol can appear once per (market_country, ranking_type)
    it was ranked under.
    """
    rows: list[dict[str, Any]] = []
    rankings = snapshot.get("rankings") if isinstance(snapshot.get("rankings"), dict) else {}
    for market_country, by_type in rankings.items():
        if not isinstance(by_type, dict):
            continue
        for ranking_type, ranking_rows in by_type.items():
            if not isinstance(ranking_rows, list):
                continue
            for row in ranking_rows:
                if not isinstance(row, dict) or not row.get("symbol"):
                    continue
                rows.append({
                    "symbol": str(row.get("symbol")),
                    "market_country": market_country,
                    "ranking_type": ranking_type,
                    "rank": row.get("rank"),
                    "currency": row.get("currency"),
                    "price": row.get("price"),
                    "trading_volume": row.get("tradingVolume"),
                    "trading_amount": row.get("tradingAmount"),
                })
    return rows
