from datetime import datetime

import pytest

from tradingagents.content_snapshot import build_content_snapshot
from tradingagents.dataflows.toss_market_snapshot import (
    collect_toss_market_snapshot,
    normalize_toss_symbol,
)


def _ok(result, *, limit="10"):
    return {
        "ok": True,
        "status": 200,
        "stage": "read_only_get",
        "body": {"result": result},
        "rate_limit": {"limit": limit, "remaining": "9", "reset": "1"},
    }


@pytest.mark.unit
def test_normalize_toss_symbol_removes_korean_suffixes():
    assert normalize_toss_symbol("005930.KS") == "005930"
    assert normalize_toss_symbol("kr-000660") == "000660"
    assert normalize_toss_symbol("aapl") == "AAPL"


@pytest.mark.unit
def test_collect_toss_market_snapshot_batches_read_only_data():
    calls = []

    def getter(path, params=None):
        calls.append((path, dict(params or {})))
        if path == "/api/v1/stocks":
            return _ok([
                {"symbol": "005930", "name": "삼성전자", "market": "KOSPI", "currency": "KRW"},
                {"symbol": "AAPL", "name": "애플", "market": "NASDAQ", "currency": "USD"},
            ], limit="5")
        if path == "/api/v1/prices":
            return _ok([
                {"symbol": "005930", "lastPrice": "290500", "currency": "KRW"},
                {"symbol": "AAPL", "lastPrice": "313.32", "currency": "USD"},
            ])
        if path == "/api/v1/candles":
            return _ok({"candles": [
                {"timestamp": "2026-07-09T00:00:00.000+09:00", "closePrice": "1", "volume": "10"}
            ]}, limit="5")
        if path == "/api/v1/exchange-rate":
            return _ok({"baseCurrency": "USD", "quoteCurrency": "KRW", "rate": "1500"}, limit="3")
        if path.startswith("/api/v1/market-calendar/"):
            return _ok({"today": {"date": "2026-07-09"}}, limit="3")
        raise AssertionError(f"unexpected path: {path}")

    snapshot = collect_toss_market_snapshot(
        env={},
        symbols=["005930.KS", "AAPL"],
        candle_count=5,
        trade_date="2026-07-09",
        getter=getter,
        generated_at=datetime(2026, 7, 9, 9, 30),
    )

    assert snapshot["artifact"] == "toss_market_snapshot"
    assert snapshot["source_policy"]["llm_used"] is False
    assert snapshot["symbols"] == ["005930", "AAPL"]
    assert snapshot["coverage"]["stocks"] is True
    assert snapshot["coverage"]["prices"] is True
    assert snapshot["coverage"]["candles"] == {"005930": True, "AAPL": True}
    assert snapshot["coverage"]["exchange_rate"] is True
    assert snapshot["coverage"]["market_calendars"] == {"KR": True, "US": True}
    assert snapshot["errors"] == []
    assert ("/api/v1/stocks", {"symbols": "005930,AAPL"}) in calls
    assert ("/api/v1/prices", {"symbols": "005930,AAPL"}) in calls
    assert ("/api/v1/exchange-rate", {"baseCurrency": "USD", "quoteCurrency": "KRW"}) in calls


@pytest.mark.unit
def test_collect_toss_market_snapshot_records_endpoint_errors():
    def getter(path, params=None):
        if path == "/api/v1/stocks":
            return _ok([{"symbol": "AAPL", "market": "NASDAQ", "currency": "USD"}])
        if path == "/api/v1/prices":
            return {"ok": False, "status": 429, "stage": "read_only_get", "body": "rate limited"}
        if path == "/api/v1/candles":
            return _ok({"candles": []})
        if path == "/api/v1/market-calendar/US":
            return _ok({"today": {"date": "2026-07-09"}})
        raise AssertionError(f"unexpected path: {path}")

    snapshot = collect_toss_market_snapshot(env={}, symbols=["AAPL"], getter=getter)

    assert snapshot["coverage"]["prices"] is False
    assert snapshot["errors"][0]["endpoint"] == "/api/v1/prices"
    assert snapshot["errors"][0]["status"] == 429


@pytest.mark.unit
def test_content_snapshot_marks_price_visuals_ready_from_market_snapshot():
    state = {
        "asset_type": "stock",
        "trade_date": "2026-07-09",
        "instrument_context": "Company: Apple; Exchange: XNAS.",
        "news_report": "실적 기대가 주가 흐름을 지지했습니다.",
        "fundamentals_report": "Apple은 소비자 전자제품과 서비스를 판매합니다.",
        "risk_debate_state": {"judge_decision": "환율과 밸류에이션을 확인합니다."},
        "market_snapshot_file": ".pilot/toss_market/AAPL.json",
        "market_snapshot": {
            "source": "toss_securities_openapi",
            "symbols": ["AAPL"],
            "coverage": {"prices": True, "candles": {"AAPL": True}},
            "prices": [{"symbol": "AAPL", "lastPrice": "313.32", "currency": "USD"}],
            "candles": {
                "AAPL": [
                    {"timestamp": "2026-07-08T13:00:00.000+09:00", "closePrice": "310.00", "volume": "100"},
                    {"timestamp": "2026-07-09T13:00:00.000+09:00", "closePrice": "313.10", "volume": "200"},
                ]
            },
        },
    }

    content = build_content_snapshot(state, "AAPL")

    price_trend = next(visual for visual in content["visuals"] if visual["id"] == "price_trend")
    volume_change = next(visual for visual in content["visuals"] if visual["id"] == "volume_change")
    assert price_trend["status"] == "ready"
    assert volume_change["status"] == "ready"
    assert content["market_data"]["source"] == "toss_securities_openapi"
    assert content["market_data"]["candle_count"] == 2
    assert content["market_data"]["metrics"]["return_1d_pct"] == 1.0
    assert content["market_data"]["metrics"]["high_60d"] == 313.1
