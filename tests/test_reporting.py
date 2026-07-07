"""Report parity: the shared writer produces the report tree for the CLI and the
programmatic API alike (#1037)."""

import json
from types import SimpleNamespace

import pytest

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
    signal = json.loads((tmp_path / "5_portfolio" / "signal.json").read_text())
    assert signal["rating"] == "Buy"
    assert signal["score"] == 2
    complete = out.read_text()
    assert "Trading Analysis Report: AAPL" in complete
    assert "MKT" in complete and "PM DECISION" in complete


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
    assert any(agent["id"] == "portfolio_manager" for agent in snapshot["agents"])
    assert snapshot["ui"]["recommended_view"] == "war_room"


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
