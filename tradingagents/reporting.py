"""Reusable report-tree writer shared by the CLI and the programmatic API.

Writes a run's per-section markdown (analysts, research, trading, risk,
portfolio) plus a consolidated ``complete_report.md`` under ``save_path``. The
CLI and ``TradingAgentsGraph.save_reports`` both call this, so a headless / API
run produces the same on-disk report tree a CLI run does.
"""

import json
from datetime import datetime
from pathlib import Path

from tradingagents.agents.utils.rating import parse_rating
from tradingagents.graph.signal_processing import normalize_trade_signal


def _preview(text: str, limit: int = 420) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "..."


def _word_count(text: str) -> int:
    return len(str(text or "").split())


def _section_payload(
    *,
    agent_id: str,
    name: str,
    team: str,
    report: str | None,
    path: str,
    decision_label: str = "rating",
) -> dict:
    payload = {
        "id": agent_id,
        "name": name,
        "team": team,
        "status": "completed" if report else "missing",
        "report_file": path,
        "word_count": _word_count(report or ""),
        "preview": _preview(report or ""),
    }
    if report:
        payload[decision_label] = parse_rating(report)
    return payload


def _source_flags(final_state: dict) -> dict[str, bool]:
    text = "\n".join(
        str(final_state.get(key, ""))
        for key in ("market_report", "sentiment_report", "news_report", "fundamentals_report")
    )
    return {
        "naver_news": "Naver News" in text or "Korean News via Naver" in text,
        "opendart": "OpenDART" in text or "DART" in text,
        "naver_datalab": "Naver DataLab" in text or "네이버 데이터랩" in text,
        "fred": "FRED" in text or "Fed Funds" in text or "FEDFUNDS" in text,
        "polymarket": "Polymarket" in text,
        "yfinance": "Yahoo Finance" in text or "YFinance" in text,
        "reddit": "Reddit" in text,
        "stocktwits": "StockTwits" in text,
    }


def _market_adapter(ticker: str) -> str:
    normalized = ticker.upper()
    if normalized.endswith((".KS", ".KQ")) or normalized.split(".", 1)[0].isdigit():
        return "KR"
    if normalized.endswith((".T", ".HK", ".L", ".TO")):
        return "GLOBAL"
    return "US"


def build_analysis_snapshot(
    final_state: dict,
    ticker: str,
    generated_at: datetime | None = None,
) -> dict:
    """Build a compact UI/replay contract for the report tree."""
    generated_at = generated_at or datetime.now()
    risk = final_state.get("risk_debate_state") or {}
    debate = final_state.get("investment_debate_state") or {}
    final_decision = final_state.get("final_trade_decision") or risk.get("judge_decision", "")
    trade_signal = final_state.get("final_trade_signal")
    if not trade_signal and final_decision:
        trade_signal = normalize_trade_signal(final_decision)

    agents = [
        _section_payload(
            agent_id="market",
            name="Market Analyst",
            team="analysts",
            report=final_state.get("market_report"),
            path="1_analysts/market.md",
        ),
        _section_payload(
            agent_id="sentiment",
            name="Sentiment Analyst",
            team="analysts",
            report=final_state.get("sentiment_report"),
            path="1_analysts/sentiment.md",
        ),
        _section_payload(
            agent_id="news",
            name="News Analyst",
            team="analysts",
            report=final_state.get("news_report"),
            path="1_analysts/news.md",
        ),
        _section_payload(
            agent_id="fundamentals",
            name="Fundamentals Analyst",
            team="analysts",
            report=final_state.get("fundamentals_report"),
            path="1_analysts/fundamentals.md",
        ),
        _section_payload(
            agent_id="research_manager",
            name="Research Manager",
            team="research",
            report=debate.get("judge_decision"),
            path="2_research/manager.md",
            decision_label="recommendation",
        ),
        _section_payload(
            agent_id="trader",
            name="Trader",
            team="trading",
            report=final_state.get("trader_investment_plan"),
            path="3_trading/trader.md",
            decision_label="action",
        ),
        _section_payload(
            agent_id="portfolio_manager",
            name="Portfolio Manager",
            team="portfolio",
            report=risk.get("judge_decision") or final_decision,
            path="5_portfolio/decision.md",
            decision_label="rating",
        ),
    ]

    return {
        "schema_version": 1,
        "artifact": "analysis_snapshot",
        "ticker": ticker,
        "asset_type": final_state.get("asset_type", "stock"),
        "market_adapter": _market_adapter(ticker),
        "trade_date": final_state.get("trade_date"),
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "instrument_context": final_state.get("instrument_context"),
        "signal": trade_signal,
        "source_flags": _source_flags(final_state),
        "files": {
            "complete_report": "complete_report.md",
            "signal": "5_portfolio/signal.json",
            "snapshot": "analysis_snapshot.json",
        },
        "agents": agents,
        "debates": {
            "research": {
                "bull_word_count": _word_count(debate.get("bull_history", "")),
                "bear_word_count": _word_count(debate.get("bear_history", "")),
                "manager_file": "2_research/manager.md",
            },
            "risk": {
                "aggressive_word_count": _word_count(risk.get("aggressive_history", "")),
                "neutral_word_count": _word_count(risk.get("neutral_history", "")),
                "conservative_word_count": _word_count(risk.get("conservative_history", "")),
                "portfolio_file": "5_portfolio/decision.md",
            },
        },
        "ui": {
            "recommended_view": "war_room",
            "primary_decision_agent": "portfolio_manager",
            "primary_signal": (trade_signal or {}).get("rating"),
            "summary": _preview(final_decision, 520),
        },
    }


def write_report_tree(final_state: dict, ticker: str, save_path) -> Path:
    """Save a completed run's reports to ``save_path``; return the complete-report path."""
    save_path = Path(save_path)
    save_path.mkdir(parents=True, exist_ok=True)
    sections = []
    generated_at = datetime.now()

    # 1. Analysts
    analysts_dir = save_path / "1_analysts"
    analyst_parts = []
    if final_state.get("market_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "market.md").write_text(final_state["market_report"], encoding="utf-8")
        analyst_parts.append(("Market Analyst", final_state["market_report"]))
    if final_state.get("sentiment_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "sentiment.md").write_text(final_state["sentiment_report"], encoding="utf-8")
        analyst_parts.append(("Sentiment Analyst", final_state["sentiment_report"]))
    if final_state.get("news_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "news.md").write_text(final_state["news_report"], encoding="utf-8")
        analyst_parts.append(("News Analyst", final_state["news_report"]))
    if final_state.get("fundamentals_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "fundamentals.md").write_text(final_state["fundamentals_report"], encoding="utf-8")
        analyst_parts.append(("Fundamentals Analyst", final_state["fundamentals_report"]))
    if analyst_parts:
        content = "\n\n".join(f"### {name}\n{text}" for name, text in analyst_parts)
        sections.append(f"## I. Analyst Team Reports\n\n{content}")

    # 2. Research
    if final_state.get("investment_debate_state"):
        research_dir = save_path / "2_research"
        debate = final_state["investment_debate_state"]
        research_parts = []
        if debate.get("bull_history"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "bull.md").write_text(debate["bull_history"], encoding="utf-8")
            research_parts.append(("Bull Researcher", debate["bull_history"]))
        if debate.get("bear_history"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "bear.md").write_text(debate["bear_history"], encoding="utf-8")
            research_parts.append(("Bear Researcher", debate["bear_history"]))
        if debate.get("judge_decision"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "manager.md").write_text(debate["judge_decision"], encoding="utf-8")
            research_parts.append(("Research Manager", debate["judge_decision"]))
        if research_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in research_parts)
            sections.append(f"## II. Research Team Decision\n\n{content}")

    # 3. Trading
    if final_state.get("trader_investment_plan"):
        trading_dir = save_path / "3_trading"
        trading_dir.mkdir(exist_ok=True)
        (trading_dir / "trader.md").write_text(final_state["trader_investment_plan"], encoding="utf-8")
        sections.append(f"## III. Trading Team Plan\n\n### Trader\n{final_state['trader_investment_plan']}")

    # 4. Risk Management
    if final_state.get("risk_debate_state"):
        risk_dir = save_path / "4_risk"
        risk = final_state["risk_debate_state"]
        risk_parts = []
        if risk.get("aggressive_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "aggressive.md").write_text(risk["aggressive_history"], encoding="utf-8")
            risk_parts.append(("Aggressive Analyst", risk["aggressive_history"]))
        if risk.get("conservative_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "conservative.md").write_text(risk["conservative_history"], encoding="utf-8")
            risk_parts.append(("Conservative Analyst", risk["conservative_history"]))
        if risk.get("neutral_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "neutral.md").write_text(risk["neutral_history"], encoding="utf-8")
            risk_parts.append(("Neutral Analyst", risk["neutral_history"]))
        if risk_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in risk_parts)
            sections.append(f"## IV. Risk Management Team Decision\n\n{content}")

        # 5. Portfolio Manager
        if risk.get("judge_decision"):
            portfolio_dir = save_path / "5_portfolio"
            portfolio_dir.mkdir(exist_ok=True)
            (portfolio_dir / "decision.md").write_text(risk["judge_decision"], encoding="utf-8")
            trade_signal = final_state.get("final_trade_signal")
            if not trade_signal and final_state.get("final_trade_decision"):
                trade_signal = normalize_trade_signal(final_state["final_trade_decision"])
            if trade_signal:
                (portfolio_dir / "signal.json").write_text(
                    json.dumps(trade_signal, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            sections.append(f"## V. Portfolio Manager Decision\n\n### Portfolio Manager\n{risk['judge_decision']}")

    # Write consolidated report
    header = f"# Trading Analysis Report: {ticker}\n\nGenerated: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    (save_path / "complete_report.md").write_text(header + "\n\n".join(sections), encoding="utf-8")
    (save_path / "analysis_snapshot.json").write_text(
        json.dumps(
            build_analysis_snapshot(final_state, ticker, generated_at),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return save_path / "complete_report.md"
