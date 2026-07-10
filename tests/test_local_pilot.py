import json
from pathlib import Path

import pytest

from tradingagents.local_pilot import run_local_pilot


def _write_report_tree(tmp_path: Path, name: str = "005930.KS_20260709_090000") -> Path:
    report_dir = tmp_path / name
    (report_dir / "1_analysts").mkdir(parents=True)
    (report_dir / "2_research").mkdir()
    (report_dir / "3_trading").mkdir()
    (report_dir / "4_risk").mkdir()
    (report_dir / "5_portfolio").mkdir()
    ticker = name.split("_", 1)[0]
    snapshot = {
        "schema_version": 1,
        "artifact": "analysis_snapshot",
        "ticker": ticker,
        "asset_type": "stock",
        "trade_date": "2026-07-09",
        "generated_at": "2026-07-09T09:00:00",
        "instrument_context": "Company: Samsung Electronics; Exchange: KSC.",
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
    (report_dir / "complete_report.md").write_text("Complete report", encoding="utf-8")
    for rel, text in {
        "1_analysts/market.md": "Price rose on higher volume.",
        "1_analysts/news.md": "Product news supported the move.",
        "1_analysts/sentiment.md": "Attention improved.",
        "1_analysts/fundamentals.md": "Revenue comes from semiconductors.",
        "2_research/bull.md": "Demand is improving.",
        "2_research/bear.md": "Valuation is high.",
        "2_research/manager.md": "Prefer starter position.",
        "3_trading/trader.md": "Wait for confirmation.",
        "4_risk/aggressive.md": "Momentum can continue.",
        "4_risk/conservative.md": "Keep size modest.",
        "4_risk/neutral.md": "Balance upside and risk.",
        "5_portfolio/decision.md": "Buy, but control risk.",
    }.items():
        (report_dir / rel).write_text(text, encoding="utf-8")
    return report_dir


def _write_local_env(path: Path) -> None:
    path.write_text(
        "\n".join([
            "TRADINGAGENTS_LOCAL_ONLY=true",
            "TRADINGAGENTS_LLM_PROVIDER=ollama",
            "OLLAMA_BASE_URL=http://localhost:11434/v1",
            "TRADINGAGENTS_QUICK_THINK_LLM=qwen3:latest",
            "TRADINGAGENTS_DEEP_THINK_LLM=qwen3:latest",
            "TRADINGAGENTS_MAX_DEBATE_ROUNDS=0",
            "TRADINGAGENTS_MAX_RISK_ROUNDS=0",
            "TRADINGAGENTS_PARALLEL_ANALYSTS=false",
            "TRADINGAGENTS_CHECKPOINT_ENABLED=true",
        ]),
        encoding="utf-8",
    )


@pytest.mark.unit
def test_run_local_pilot_writes_combined_no_llm_report(tmp_path):
    _write_report_tree(tmp_path / "reports")
    env_file = tmp_path / ".env.lowcost"
    _write_local_env(env_file)
    market_dir = tmp_path / "market"
    market_dir.mkdir()
    (market_dir / "005930.json").write_text(
        json.dumps({
            "schema_version": 1,
            "artifact": "toss_market_snapshot",
            "source": "toss_securities_openapi",
            "symbols": ["005930"],
            "prices": [{"symbol": "005930", "lastPrice": "290500", "currency": "KRW"}],
            "candles": {"005930": [{"closePrice": "291000", "volume": "9674466"}]},
            "coverage": {"prices": True, "candles": {"005930": True}},
        }),
        encoding="utf-8",
    )
    (market_dir / "AAPL.json").write_text(
        json.dumps({
            "schema_version": 1,
            "artifact": "toss_market_snapshot",
            "source": "toss_securities_openapi",
            "symbols": ["AAPL"],
            "stocks": [{"symbol": "AAPL", "name": "Apple Inc.", "market": "NASDAQ", "currency": "USD"}],
            "prices": [{"symbol": "AAPL", "lastPrice": "313.32", "currency": "USD"}],
            "candles": {
                "AAPL": [
                    {"timestamp": "2026-07-08", "closePrice": "310.00", "volume": "90000000"},
                    {"timestamp": "2026-07-09", "closePrice": "313.32", "volume": "95000000"},
                ]
            },
            "coverage": {"prices": True, "candles": {"AAPL": True}},
        }),
        encoding="utf-8",
    )
    profiles = tmp_path / "profiles.json"
    profiles.write_text(
        json.dumps({
            "profiles": [
                {
                    "profile_type": "stock",
                    "ticker": "AAPL",
                    "name": "Apple Inc.",
                    "exchange": "NASDAQ",
                    "country": "United States",
                    "currency": "USD",
                    "sector": "Technology",
                    "products": ["iPhone", "Services"],
                },
                {
                    "profile_type": "theme",
                    "ticker": "KR-AI-SEMI",
                    "name": "AI 반도체",
                    "value_chain": [{"stage": "설계", "global_names": ["NVDA"]}],
                    "global_names": ["NVDA"],
                }
            ]
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    payload = run_local_pilot(
        reports_dir=tmp_path / "reports",
        output_dir=tmp_path / "out",
        env_file=env_file,
        market_snapshot_dir=market_dir,
        profiles_path=profiles,
        env={},
    )

    assert payload["artifact"] == "local_pilot_report"
    assert payload["llm_policy"].startswith("no external LLM")
    assert payload["cost_guard"]["status"] == "pass"
    assert payload["gate"]["status"] == "pass"
    assert payload["report_audit"]["summary"]["reports"] == 1
    assert payload["content_pilot"]["summary"]["market_snapshots_attached"] == 1
    assert payload["content_quality"]["summary"]["pass_pct"] == 100.0
    assert payload["profile_pilot"]["summary"]["publish_ready_pct"] == 100.0
    assert payload["profile_pilot"]["summary"]["market_snapshots_attached"] == 1
    assert payload["profile_pilot"]["summary"]["price_trend_ready"] == 1
    assert payload["profile_pilot"]["summary"]["volume_change_ready"] == 1
    assert payload["profile_content_quality"]["summary"]["pass_pct"] == 100.0
    assert payload["profile_content_quality"]["summary"]["issue_codes"] == {}
    assert (tmp_path / "out" / "local_pilot_report.json").exists()
    assert (tmp_path / "out" / "local_pilot_report.md").exists()


@pytest.mark.unit
def test_run_local_pilot_fails_when_local_cost_guard_fails(tmp_path):
    _write_report_tree(tmp_path / "reports")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join([
            "TRADINGAGENTS_LLM_PROVIDER=google",
            "TRADINGAGENTS_QUICK_THINK_LLM=gemini-3.1-flash-lite",
            "TRADINGAGENTS_DEEP_THINK_LLM=gemini-3.1-flash-lite",
            "TRADINGAGENTS_MAX_DEBATE_ROUNDS=0",
            "TRADINGAGENTS_MAX_RISK_ROUNDS=0",
            "TRADINGAGENTS_PARALLEL_ANALYSTS=false",
            "TRADINGAGENTS_CHECKPOINT_ENABLED=true",
        ]),
        encoding="utf-8",
    )

    payload = run_local_pilot(
        reports_dir=tmp_path / "reports",
        output_dir=tmp_path / "out",
        env_file=env_file,
        profiles_path=None,
        env={},
    )

    assert payload["cost_guard"]["status"] == "fail"
    assert payload["gate"]["status"] == "fail"
    assert "cost_guard_failed" in payload["gate"]["reasons"]
