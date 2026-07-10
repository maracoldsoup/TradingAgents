"""Report parity: the shared writer produces the report tree for the CLI and the
programmatic API alike (#1037)."""

import json
from types import SimpleNamespace

import pytest

from tradingagents.content_snapshot import build_content_snapshot
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.reporting import build_analysis_snapshot, write_report_tree


def _state():
    return {
        "market_report": "MKT",
        "news_report": "NEWS",
        "sentiment_report": "SENT",
        "fundamentals_report": "FUND",
        "investment_debate_state": {"judge_decision": "RM PLAN"},
        "trader_investment_plan": "TRADE",
        "risk_debate_state": {"judge_decision": "PM DECISION"},
        "asset_type": "stock",
        "trade_date": "2026-07-07",
        "instrument_context": "Company: Example Inc.; Exchange: XNAS.",
        "final_trade_signal": {
            "schema_version": 1,
            "rating": "Buy",
            "action": "Buy",
            "bias": "bullish",
            "score": 2,
            "source": "portfolio_manager",
        },
    }


@pytest.mark.unit
def test_write_report_tree_creates_files(tmp_path):
    out = write_report_tree(_state(), "AAPL", tmp_path)
    assert out.name == "complete_report.md"
    assert (tmp_path / "1_analysts" / "market.md").read_text() == "MKT"
    assert (tmp_path / "1_analysts" / "news.md").read_text() == "NEWS"
    assert (tmp_path / "2_research" / "manager.md").read_text() == "RM PLAN"
    assert (tmp_path / "3_trading" / "trader.md").read_text() == "TRADE"
    assert (tmp_path / "5_portfolio" / "decision.md").read_text() == "PM DECISION"
    assert (tmp_path / "analysis_snapshot.json").exists()
    assert (tmp_path / "content_snapshot.json").exists()
    signal = json.loads((tmp_path / "5_portfolio" / "signal.json").read_text())
    assert signal["rating"] == "Buy"
    assert signal["score"] == 2
    complete = out.read_text()
    assert "Trading Analysis Report: AAPL" in complete
    assert "MKT" in complete and "PM DECISION" in complete
    content = json.loads((tmp_path / "content_snapshot.json").read_text())
    assert content["artifact"] == "content_snapshot"
    assert content["presentation"]["tone"] == "antwiki_like"
    assert any(card["id"] == "why_moved" for card in content["cards"])


@pytest.mark.unit
def test_write_report_tree_derives_signal_from_final_decision(tmp_path):
    state = _state()
    state.pop("final_trade_signal")
    state["final_trade_decision"] = "**Rating**: Hold\n\nWait for confirmation."

    write_report_tree(state, "005930.KS", tmp_path)

    signal = json.loads((tmp_path / "5_portfolio" / "signal.json").read_text())
    assert signal["rating"] == "Hold"
    assert signal["action"] == "Hold"
    assert signal["score"] == 0


@pytest.mark.unit
def test_build_analysis_snapshot_contains_ui_contract():
    state = _state()
    state["news_report"] = "## News\nNaver News and OpenDART confirmed Q2 results."
    state["sentiment_report"] = "Naver DataLab attention is rising."

    snapshot = build_analysis_snapshot(state, "005930.KS")

    assert snapshot["schema_version"] == 1
    assert snapshot["artifact"] == "analysis_snapshot"
    assert snapshot["market_adapter"] == "KR"
    assert snapshot["signal"]["rating"] == "Buy"
    assert snapshot["source_flags"]["naver_news"] is True
    assert snapshot["source_flags"]["opendart"] is True
    assert snapshot["source_flags"]["naver_datalab"] is True
    assert snapshot["files"]["complete_report"] == "complete_report.md"
    assert snapshot["files"]["content_snapshot"] == "content_snapshot.json"
    assert snapshot["content"]["snapshot_file"] == "content_snapshot.json"
    assert any(agent["id"] == "portfolio_manager" for agent in snapshot["agents"])
    assert snapshot["ui"]["recommended_view"] == "war_room"


@pytest.mark.unit
def test_build_content_snapshot_blocks_etf_without_composition_visuals():
    state = _state()
    state["asset_type"] = "etf"
    state["instrument_context"] = "The instrument to analyze is `SMH`. It is an ETF."

    content = build_content_snapshot(state, "SMH")

    assert content["content_type"] == "etf"
    assert content["publish_gate"]["status"] == "blocked"
    assert any("etf_top_holdings" in reason for reason in content["publish_gate"]["reasons"])
    assert any(v["id"] == "etf_sector_allocation" for v in content["visuals"])


@pytest.mark.unit
def test_build_content_snapshot_allows_stock_without_price_levels():
    state = _state()

    content = build_content_snapshot(state, "AAPL")

    assert content["content_type"] == "stock"
    assert content["publish_gate"]["status"] == "ready"
    assert "price_ladder_hidden_incomplete_levels" in content["publish_gate"]["warnings"]
    ladder = next(v for v in content["visuals"] if v["id"] == "price_ladder")
    assert ladder["status"] == "hidden"


@pytest.mark.unit
def test_build_content_snapshot_keeps_explicit_stock_even_when_etf_is_mentioned():
    state = _state()
    state["news_report"] = "Single-stock ETF flows amplified short-term volatility."

    content = build_content_snapshot(state, "005930.KS")

    assert content["asset_type"] == "stock"
    assert content["content_type"] == "stock"
    assert content["publish_gate"]["status"] == "ready"


@pytest.mark.unit
def test_build_content_snapshot_uses_resolved_identity_for_definition_card():
    state = _state()
    state["instrument_context"] = (
        "The instrument to analyze is `005930.KS`. Resolved identity: "
        "Company: Samsung Electronics Co., Ltd.; "
        "Business classification: Technology / Consumer Electronics; "
        "Exchange: KSC."
    )

    content = build_content_snapshot(state, "005930.KS")

    definition = next(card for card in content["cards"] if card["id"] == "what_is_it")
    assert "005930.KS" in definition["body"]
    assert "Samsung Electronics" in definition["body"]
    assert "Technology / Consumer Electronics" in definition["body"]
    assert "The instrument to analyze" not in definition["body"]


@pytest.mark.unit
def test_build_content_snapshot_filters_report_metadata_from_cards():
    state = _state()
    state["news_report"] = "---\n작성일:* 2026년 7월 9일\n실적 발표 이후 외국인 매도가 이어졌습니다."

    content = build_content_snapshot(state, "005930.KS")

    why = next(card for card in content["cards"] if card["id"] == "why_moved")
    assert why["bullets"][0] == "실적 발표 이후 외국인 매도가 이어졌습니다."
    assert "--" not in why["bullets"]


@pytest.mark.unit
def test_save_reports_explicit_path(tmp_path):
    # Unbound: with an explicit save_path, the method doesn't touch self/config.
    out = TradingAgentsGraph.save_reports(None, _state(), "AAPL", save_path=tmp_path)
    assert (tmp_path / "complete_report.md").exists()
    assert out == tmp_path / "complete_report.md"


@pytest.mark.unit
def test_save_reports_defaults_under_results_dir(tmp_path):
    mock_self = SimpleNamespace(config={"results_dir": str(tmp_path)})
    out = TradingAgentsGraph.save_reports(mock_self, _state(), "AAPL")
    assert out.exists()
    assert out.parent.parent.name == "reports"  # results_dir/reports/AAPL_<stamp>/...
    assert out.parent.name.startswith("AAPL_")
