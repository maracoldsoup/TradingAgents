import json
from pathlib import Path

import pytest

from tradingagents.candidate_queue import build_candidate_queue, write_candidate_queue


def _write_report_tree(root: Path, name: str = "005930.KS_20260709_090000") -> Path:
    report_dir = root / name
    (report_dir / "5_portfolio").mkdir(parents=True)
    ticker = name.split("_", 1)[0]
    (report_dir / "analysis_snapshot.json").write_text(
        json.dumps({
            "schema_version": 1,
            "artifact": "analysis_snapshot",
            "ticker": ticker,
            "asset_type": "stock",
        }),
        encoding="utf-8",
    )
    (report_dir / "5_portfolio" / "signal.json").write_text(
        json.dumps({"schema_version": 1, "action": "Hold"}),
        encoding="utf-8",
    )
    return report_dir


def _write_profiles(path: Path) -> Path:
    path.write_text(
        json.dumps({
            "profiles": [
                {
                    "profile_type": "stock",
                    "ticker": "AAPL",
                    "name": "Apple Inc.",
                    "exchange": "NASDAQ",
                    "currency": "USD",
                    "products": ["iPhone"],
                },
                {
                    "profile_type": "etf",
                    "ticker": "DEMOETF",
                    "name": "Demo ETF",
                    "holdings": {"AAPL": 20, "NVDA": 15},
                    "sectors": {"Technology": 80},
                    "countries": {"United States": 90},
                },
                {
                    "profile_type": "theme",
                    "ticker": "KR-AI-SEMI",
                    "name": "AI 반도체",
                    "value_chain": [{"stage": "설계", "global_names": ["NVDA"]}],
                    "global_names": ["NVDA"],
                },
            ]
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _write_market_snapshot(path: Path) -> Path:
    path.write_text(
        json.dumps({
            "schema_version": 1,
            "artifact": "toss_market_snapshot",
            "symbols": ["005930", "AAPL"],
            "stocks": [{"symbol": "005930"}, {"symbol": "AAPL"}],
            "prices": [{"symbol": "005930"}, {"symbol": "AAPL"}],
            "candles": {"005930": [{"closePrice": "70000"}], "AAPL": [{"closePrice": "300"}]},
        }),
        encoding="utf-8",
    )
    return path


@pytest.mark.unit
def test_build_candidate_queue_merges_reports_profiles_and_seed_file(tmp_path):
    reports_dir = tmp_path / "reports"
    _write_report_tree(reports_dir)
    profiles = _write_profiles(tmp_path / "profiles.json")
    market_dir = tmp_path / "market"
    market_dir.mkdir()
    _write_market_snapshot(market_dir / "snapshot.json")
    candidates = tmp_path / "candidates.csv"
    candidates.write_text(
        "ticker,name,content_type,market,notes\nNVDA,Nvidia,stock,US,watchlist\n",
        encoding="utf-8",
    )

    payload = build_candidate_queue(
        reports_dir=reports_dir,
        report_limit=20,
        profile_paths=[profiles],
        candidate_files=[candidates],
        market_snapshot_dir=market_dir,
        target_candidates=4,
    )

    assert payload["artifact"] == "candidate_queue"
    assert payload["llm_policy"].startswith("no external LLM")
    assert payload["summary"]["candidates"] == 5
    assert payload["summary"]["ready_for_local_pilot"] == 4
    assert payload["gate"]["status"] == "pass"
    assert payload["summary"]["content_types"] == {"stock": 3, "etf": 1, "theme": 1}
    nvda = next(row for row in payload["rows"] if row["ticker"] == "NVDA")
    assert nvda["status"] == "needs_seed_data"
    assert "saved_report_or_profile" in nvda["missing_inputs"]


@pytest.mark.unit
def test_write_candidate_queue_outputs_json_and_markdown(tmp_path):
    reports_dir = tmp_path / "reports"
    _write_report_tree(reports_dir)
    profiles = _write_profiles(tmp_path / "profiles.json")

    payload = write_candidate_queue(
        output_dir=tmp_path / "out",
        reports_dir=reports_dir,
        report_limit=20,
        profile_paths=[profiles],
        target_candidates=20,
    )

    assert payload["gate"]["status"] == "needs_more_candidates"
    assert "ready_candidates_below_target" in payload["gate"]["reasons"]
    assert (tmp_path / "out" / "candidate_queue.json").exists()
    markdown = (tmp_path / "out" / "candidate_queue.md").read_text(encoding="utf-8")
    assert "# Candidate Queue" in markdown
    assert "remaining_ready_to_target" in markdown
