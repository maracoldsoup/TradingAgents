from datetime import datetime

import pytest

from tradingagents.dataflows.toss_rankings import (
    collect_toss_rankings_snapshot,
    notable_symbols,
)


def _ok(result, *, limit="5"):
    return {
        "ok": True,
        "status": 200,
        "stage": "read_only_get",
        "body": {"result": result},
        "rate_limit": {"limit": limit, "remaining": "4", "reset": "1"},
    }


def _ranking_result(rows, ranked_at="2026-07-10T09:00:00+09:00"):
    return {"rankedAt": ranked_at, "rankings": rows}


@pytest.mark.unit
def test_collect_toss_rankings_snapshot_batches_market_and_type():
    calls = []

    def getter(path, params=None):
        calls.append((path, dict(params or {})))
        params = params or {}
        if path == "/api/v1/stocks":
            return _ok([{"symbol": "005930", "name": "삼성전자"}])
        if params.get("marketCountry") == "KR" and params.get("type") == "TOP_GAINERS":
            return _ok(_ranking_result([
                {"rank": 1, "symbol": "005930", "currency": "KRW",
                 "price": {"lastPrice": "56500", "basePrice": "55800", "changeRate": "0.0125"},
                 "tradingVolume": "18432100", "tradingAmount": "1041436650000"},
            ]))
        return _ok(_ranking_result([]))

    snapshot = collect_toss_rankings_snapshot(
        env={},
        market_countries=("KR", "US"),
        ranking_types=("TOP_GAINERS", "TOP_LOSERS"),
        duration="1d",
        count=10,
        getter=getter,
        generated_at=datetime(2026, 7, 10, 9, 30),
    )

    assert snapshot["artifact"] == "toss_rankings_snapshot"
    assert snapshot["source_policy"]["llm_used"] is False
    assert snapshot["coverage"]["KR"]["TOP_GAINERS"] is True
    assert snapshot["coverage"]["KR"]["TOP_LOSERS"] is False
    assert snapshot["coverage"]["US"]["TOP_GAINERS"] is False
    assert snapshot["errors"] == []
    assert snapshot["stock_names"]["KR"] == {"005930": "삼성전자"}
    assert snapshot["stock_names"]["US"] == {}
    # 4 ranking calls + 1 /api/v1/stocks call for KR only (US had no ranked symbols)
    assert len(calls) == 5
    assert (
        "/api/v1/rankings",
        {
            "type": "TOP_GAINERS",
            "marketCountry": "KR",
            "duration": "1d",
            "excludeInvestmentCaution": True,
            "count": 10,
        },
    ) in calls


@pytest.mark.unit
def test_collect_toss_rankings_snapshot_records_endpoint_errors():
    def getter(path, params=None):
        if params.get("type") == "TOP_GAINERS":
            return {"ok": False, "status": 429, "stage": "read_only_get", "body": "rate limited"}
        return _ok(_ranking_result([]))

    snapshot = collect_toss_rankings_snapshot(
        env={},
        market_countries=("KR",),
        ranking_types=("TOP_GAINERS", "TOP_LOSERS"),
        getter=getter,
    )

    assert snapshot["coverage"]["KR"]["TOP_GAINERS"] is False
    assert snapshot["errors"][0]["status"] == 429
    assert snapshot["errors"][0]["params"]["type"] == "TOP_GAINERS"


@pytest.mark.unit
def test_collect_toss_rankings_snapshot_rejects_realtime_for_gainers_losers():
    with pytest.raises(ValueError, match="realtime"):
        collect_toss_rankings_snapshot(
            env={},
            ranking_types=("TOP_GAINERS",),
            duration="realtime",
            getter=lambda path, params=None: _ok(_ranking_result([])),
        )


@pytest.mark.unit
def test_collect_toss_rankings_snapshot_rejects_unknown_type():
    with pytest.raises(ValueError, match="Unknown ranking type"):
        collect_toss_rankings_snapshot(
            env={},
            ranking_types=("NOT_A_REAL_TYPE",),
            getter=lambda path, params=None: _ok(_ranking_result([])),
        )


@pytest.mark.unit
def test_collect_toss_rankings_snapshot_tolerates_failed_stock_lookup():
    def getter(path, params=None):
        if path == "/api/v1/stocks":
            return {"ok": False, "status": 500, "stage": "read_only_get", "body": "boom"}
        if params.get("type") == "TOP_GAINERS":
            return _ok(_ranking_result([{"rank": 1, "symbol": "005930", "currency": "KRW"}]))
        return _ok(_ranking_result([]))

    snapshot = collect_toss_rankings_snapshot(
        env={},
        market_countries=("KR",),
        ranking_types=("TOP_GAINERS",),
        getter=getter,
    )

    # A failed name lookup never fabricates a name — just comes back empty.
    assert snapshot["stock_names"]["KR"] == {}
    assert snapshot["coverage"]["KR"]["TOP_GAINERS"] is True


@pytest.mark.unit
def test_notable_symbols_flattens_rankings_without_recomputing():
    snapshot = {
        "rankings": {
            "KR": {
                "TOP_GAINERS": [
                    {"rank": 1, "symbol": "005930", "currency": "KRW",
                     "price": {"changeRate": "0.05"}, "tradingVolume": "100", "tradingAmount": "200"},
                ],
                "TOP_LOSERS": [],
            },
            "US": {
                "TOP_GAINERS": [
                    {"rank": 1, "symbol": "NVDA", "currency": "USD",
                     "price": {"changeRate": "0.03"}, "tradingVolume": "10", "tradingAmount": "20"},
                ],
                "TOP_LOSERS": [],
            },
        },
        "stock_names": {
            "KR": {"005930": "삼성전자"},
            "US": {},
        },
    }

    rows = notable_symbols(snapshot)

    assert {row["symbol"] for row in rows} == {"005930", "NVDA"}
    kr_row = next(row for row in rows if row["symbol"] == "005930")
    assert kr_row["market_country"] == "KR"
    assert kr_row["ranking_type"] == "TOP_GAINERS"
    assert kr_row["rank"] == 1
    assert kr_row["name"] == "삼성전자"

    us_row = next(row for row in rows if row["symbol"] == "NVDA")
    assert us_row["name"] is None
