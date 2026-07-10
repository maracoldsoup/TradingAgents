import json
from datetime import datetime

import pytest

from tradingagents.toss_report_snapshots import (
    collect_toss_market_snapshots_for_reports,
    report_symbol_plan,
)


def _write_report(tmp_path, name, *, ticker=None):
    report_dir = tmp_path / name
    (report_dir / "5_portfolio").mkdir(parents=True)
    snapshot = {
        "schema_version": 1,
        "artifact": "analysis_snapshot",
        "ticker": ticker or name.split("_", 1)[0],
        "asset_type": "stock",
    }
    (report_dir / "analysis_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (report_dir / "5_portfolio" / "signal.json").write_text("{}", encoding="utf-8")
    return report_dir


def _ok(result, *, limit="10"):
    return {
        "ok": True,
        "status": 200,
        "stage": "read_only_get",
        "body": {"result": result},
        "rate_limit": {"limit": limit, "remaining": "9", "reset": "1"},
    }


@pytest.mark.unit
def test_report_symbol_plan_dedupes_korean_tickers(tmp_path):
    _write_report(tmp_path, "005930.KS_20260709_090000")
    _write_report(tmp_path, "005930.KS_20260709_091000")
    _write_report(tmp_path, "AAPL_20260709_090000")

    plan = report_symbol_plan(tmp_path, limit=10)

    assert [row["symbol"] for row in plan] == ["AAPL", "005930"]
    samsung = next(row for row in plan if row["symbol"] == "005930")
    assert samsung["tickers"] == ["005930.KS"]
    assert len(samsung["reports"]) == 2


@pytest.mark.unit
def test_collect_report_snapshots_dry_run_does_not_call_network(tmp_path):
    _write_report(tmp_path, "005930.KS_20260709_090000")

    payload = collect_toss_market_snapshots_for_reports(
        env={},
        reports_dir=tmp_path,
        dry_run=True,
        generated_at=datetime(2026, 7, 9, 10, 0),
    )

    assert payload["artifact"] == "toss_market_snapshot_plan"
    assert payload["symbols"] == ["005930"]
    assert payload["source_policy"]["network_used"] is False


@pytest.mark.unit
def test_collect_report_snapshots_writes_batch_snapshot(tmp_path):
    _write_report(tmp_path / "reports", "005930.KS_20260709_090000")

    def getter(path, params=None):
        if path == "/api/v1/stocks":
            return _ok([{"symbol": "005930", "market": "KOSPI", "currency": "KRW"}], limit="5")
        if path == "/api/v1/prices":
            return _ok([{"symbol": "005930", "lastPrice": "290500", "currency": "KRW"}])
        if path == "/api/v1/candles":
            return _ok({"candles": [{"closePrice": "291000", "volume": "9674466"}]}, limit="5")
        if path == "/api/v1/market-calendar/KR":
            return _ok({"today": {"date": "2026-07-09"}}, limit="3")
        raise AssertionError(f"unexpected path: {path}")

    snapshot = collect_toss_market_snapshots_for_reports(
        env={},
        reports_dir=tmp_path / "reports",
        output_dir=tmp_path / "out",
        getter=getter,
        generated_at=datetime(2026, 7, 9, 10, 0),
    )

    assert snapshot["artifact"] == "toss_market_snapshot"
    assert snapshot["symbols"] == ["005930"]
    assert snapshot["coverage"]["candles"] == {"005930": True}
    assert snapshot["report_symbol_map"][0]["reports"] == ["005930.KS_20260709_090000"]
    assert (tmp_path / "out" / "reports_005930_20260709_100000.json").exists()
