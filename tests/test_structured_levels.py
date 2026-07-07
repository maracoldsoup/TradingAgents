"""Phase 4-1: structured level plumbing (schemas → state → signal → dashboard)."""

from __future__ import annotations

from tradingagents.agents.schemas import (
    PortfolioDecision,
    TraderProposal,
    render_pm_decision,
    render_trader_proposal,
)
from tradingagents.dashboard.events import DashboardEventTranslator
from tradingagents.graph.signal_processing import compose_levels, normalize_trade_signal


def test_pm_schema_carries_final_levels():
    d = PortfolioDecision(
        rating="Overweight",
        executive_summary="s",
        investment_thesis="t",
        price_target=360000,
        entry_price=296000,
        stop_loss=270000,
        position_size_pct=6,
    )
    md = render_pm_decision(d)
    assert "**Entry Price**: 296000" in md and "**Stop Loss**: 270000" in md
    assert "**Position Size**: 6" in md
    # nullish 문자열 관용 (기존 #1058 동작 유지)
    d2 = PortfolioDecision(
        rating="Hold", executive_summary="s", investment_thesis="t",
        entry_price="N/A", stop_loss="", position_size_pct="none",
    )
    assert d2.entry_price is None and d2.stop_loss is None


def test_compose_levels_pm_overrides_trader_entry_survives():
    trader = TraderProposal(action="Buy", reasoning="r", entry_price=296000, stop_loss=280000).model_dump(mode="json")
    pm = PortfolioDecision(
        rating="Overweight", executive_summary="s", investment_thesis="t",
        stop_loss=270000, price_target=360000,
    ).model_dump(mode="json")
    levels = compose_levels(trader, pm)
    assert levels == {"entry": 296000.0, "stop": 270000.0, "target": 360000.0}
    # 구조화가 전혀 없으면 빈 dict — 지어내지 않는다
    assert compose_levels({}, {}) == {}
    assert compose_levels(None, None) == {}


def test_signal_json_includes_levels():
    trader = {"entry_price": 296000, "stop_loss": 280000}
    pm = {"stop_loss": 270000, "price_target": 360000, "position_size_pct": 6}
    sig = normalize_trade_signal("**Rating**: Overweight", trader, pm)
    assert sig["rating"] == "Overweight"
    assert sig["levels"] == {
        "entry": 296000.0, "stop": 270000.0, "target": 360000.0,
        "position_size_pct": 6.0,
    }
    # 구조화 부재 시 levels 키 자체가 없다 (하위 호환)
    assert "levels" not in normalize_trade_signal("**Rating**: Hold")


def test_translator_prefers_structured_over_regex():
    tr = DashboardEventTranslator()
    chunk = {
        "trader_investment_plan": "진입은 분할 3회로 접근합니다.",  # 정규식이 물던 함정 문장
        "trader_structured": {"entry_price": 296000, "stop_loss": 280000},
    }
    ev = [e for e in tr.translate(chunk) if e["type"] == "trader"][0]
    assert ev["levels_source"] == "structured"
    assert ev["levels"]["entry"] == 296000.0 and "3" not in str(ev["levels"].values())

    tr2 = DashboardEventTranslator()
    ev2 = [e for e in tr2.translate({
        "final_trade_decision": "**Rating**: Overweight\n목표주가 360,000원",
    }) if e["type"] == "final"][0]
    # 구조화 부재 → 정규식 폴백이 여전히 동작
    assert ev2["levels_source"] == "extracted"
    assert ev2["levels"].get("target") == 360000.0
