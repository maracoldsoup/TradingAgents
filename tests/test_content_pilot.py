import json

import pytest

from tradingagents.content_pilot import (
    build_content_snapshot_from_report_dir,
    final_state_from_report_dir,
    find_report_dirs,
    load_market_snapshot_index,
    run_content_pilot,
)


def _write_report_tree(tmp_path, name="AAPL_20260709_090000", *, asset_type="stock"):
    report_dir = tmp_path / name
    (report_dir / "1_analysts").mkdir(parents=True)
    (report_dir / "2_research").mkdir()
    (report_dir / "3_trading").mkdir()
    (report_dir / "4_risk").mkdir()
    (report_dir / "5_portfolio").mkdir()

    snapshot = {
        "schema_version": 1,
        "artifact": "analysis_snapshot",
        "ticker": name.split("_", 1)[0],
        "asset_type": asset_type,
        "trade_date": "2026-07-09",
        "generated_at": "2026-07-09T09:00:00",
        "instrument_context": "Example is a global semiconductor company.",
    }
    signal = {
        "schema_version": 1,
        "rating": "Buy",
        "action": "Buy",
        "bias": "bullish",
        "score": 2,
        "levels": {
            "entry": 100,
            "stop": 90,
            "target": 120,
            "position_size_pct": 5,
        },
    }

    (report_dir / "analysis_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (report_dir / "5_portfolio" / "signal.json").write_text(json.dumps(signal), encoding="utf-8")
    (report_dir / "1_analysts" / "market.md").write_text("Price rose on higher volume.", encoding="utf-8")
    (report_dir / "1_analysts" / "sentiment.md").write_text("Retail attention improved.", encoding="utf-8")
    (report_dir / "1_analysts" / "news.md").write_text("New product news supported the move.", encoding="utf-8")
    (report_dir / "1_analysts" / "fundamentals.md").write_text("Revenue comes from chips and services.", encoding="utf-8")
    (report_dir / "2_research" / "bull.md").write_text("Demand is improving.", encoding="utf-8")
    (report_dir / "2_research" / "bear.md").write_text("Valuation is high.", encoding="utf-8")
    (report_dir / "2_research" / "manager.md").write_text("Prefer a small starter position.", encoding="utf-8")
    (report_dir / "3_trading" / "trader.md").write_text("Wait for confirmation.", encoding="utf-8")
    (report_dir / "4_risk" / "neutral.md").write_text("Keep size moderate.", encoding="utf-8")
    (report_dir / "5_portfolio" / "decision.md").write_text("Buy, but control risk.", encoding="utf-8")
    return report_dir


@pytest.mark.unit
def test_final_state_from_report_dir_reconstructs_saved_reports(tmp_path):
    report_dir = _write_report_tree(tmp_path, "AAPL_20260709_090000")

    state, ticker, generated_at = final_state_from_report_dir(report_dir)

    assert ticker == "AAPL"
    assert generated_at.isoformat() == "2026-07-09T09:00:00"
    assert state["market_report"] == "Price rose on higher volume."
    assert state["investment_debate_state"]["bull_history"] == "Demand is improving."
    assert state["risk_debate_state"]["judge_decision"] == "Buy, but control risk."
    assert state["final_trade_signal"]["levels"]["entry"] == 100


@pytest.mark.unit
def test_build_content_snapshot_from_report_dir_uses_antwiki_contract(tmp_path):
    report_dir = _write_report_tree(tmp_path, "AAPL_20260709_090000")

    content = build_content_snapshot_from_report_dir(report_dir)

    assert content["ticker"] == "AAPL"
    assert content["presentation"]["tone"] == "antwiki_like"
    assert content["publish_gate"]["status"] == "ready"
    assert any(card["id"] == "why_moved" for card in content["cards"])
    assert next(v for v in content["visuals"] if v["id"] == "price_ladder")["status"] == "ready"


@pytest.mark.unit
def test_run_content_pilot_writes_optional_outputs(tmp_path):
    _write_report_tree(tmp_path, "AAPL_20260709_090000")
    _write_report_tree(tmp_path, "SMH_20260709_090001", asset_type="etf")
    output_dir = tmp_path / "pilot"

    result = run_content_pilot(tmp_path, limit=10, output_dir=output_dir)

    assert result["summary"]["reports"] == 2
    assert result["summary"]["statuses"]["ready"] == 1
    assert result["summary"]["statuses"]["blocked"] == 1
    assert result["summary"]["missing_visuals"]["etf_top_holdings"] == 1
    assert (output_dir / "content_pilot_summary.json").exists()
    assert (output_dir / "AAPL_20260709_090000" / "content_snapshot.json").exists()
    assert not (tmp_path / "AAPL_20260709_090000" / "content_snapshot.json").exists()


@pytest.mark.unit
def test_find_report_dirs_ignores_auxiliary_directories(tmp_path):
    report_dir = _write_report_tree(tmp_path, "AAPL_20260709_090000")
    (tmp_path / "market").mkdir()
    (tmp_path / "pilot").mkdir()

    assert find_report_dirs(tmp_path, limit=10) == [report_dir]


@pytest.mark.unit
def test_run_content_pilot_attaches_saved_toss_market_snapshot(tmp_path):
    _write_report_tree(tmp_path, "005930.KS_20260709_090000")
    market_dir = tmp_path / "market"
    market_dir.mkdir()
    snapshot = {
        "schema_version": 1,
        "artifact": "toss_market_snapshot",
        "source": "toss_securities_openapi",
        "symbols": ["005930"],
        "prices": [{"symbol": "005930", "lastPrice": "290500", "currency": "KRW"}],
        "candles": {
            "005930": [
                {
                    "timestamp": "2026-07-09T00:00:00.000+09:00",
                    "closePrice": "291000",
                    "volume": "9674466",
                }
            ]
        },
        "coverage": {"prices": True, "candles": {"005930": True}},
    }
    (market_dir / "005930_20260709.json").write_text(
        json.dumps(snapshot, ensure_ascii=False),
        encoding="utf-8",
    )

    result = run_content_pilot(
        tmp_path,
        limit=10,
        output_dir=tmp_path / "pilot",
        market_snapshot_dir=market_dir,
    )

    row = result["rows"][0]
    content = result["snapshots"][0]
    assert row["market_data_source"] == "toss_securities_openapi"
    assert row["market_candle_count"] == 1
    assert row["price_trend_status"] == "ready"
    assert result["summary"]["market_snapshots_attached"] == 1
    assert result["summary"]["price_trend_ready"] == 1
    assert content["market_data"]["snapshot_file"].endswith("005930_20260709.json")
    assert next(v for v in content["visuals"] if v["id"] == "volume_change")["status"] == "ready"


@pytest.mark.unit
def test_load_market_snapshot_index_ignores_non_snapshot_json(tmp_path):
    market_dir = tmp_path / "market"
    market_dir.mkdir()
    (market_dir / "other.json").write_text('{"artifact":"other"}', encoding="utf-8")

    assert load_market_snapshot_index(market_dir) == {}
