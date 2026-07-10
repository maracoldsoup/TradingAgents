import json

import pytest

from tradingagents.candidate_input_review import (
    review_candidate_inputs,
    write_candidate_input_review,
)


def _market_snapshot(path):
    path.write_text(
        json.dumps({
            "artifact": "toss_market_snapshot",
            "symbols": ["AAPL"],
            "stocks": [{"symbol": "AAPL"}],
            "prices": [{"symbol": "AAPL"}],
            "candles": {"AAPL": [{"closePrice": "300"}]},
        }),
        encoding="utf-8",
    )


@pytest.mark.unit
def test_review_candidate_inputs_accepts_ready_profiles_and_seed_rows(tmp_path):
    market_dir = tmp_path / "market"
    market_dir.mkdir()
    _market_snapshot(market_dir / "aapl.json")
    profiles = tmp_path / "profiles.json"
    profiles.write_text(
        json.dumps({
            "profiles": [
                {
                    "profile_type": "stock",
                    "ticker": "AAPL",
                    "name": "Apple Inc.",
                    "currency": "USD",
                    "exchange": "NASDAQ",
                    "products": ["iPhone", "Services"],
                },
                {
                    "profile_type": "etf",
                    "ticker": "DEMOETF",
                    "name": "Demo ETF",
                    "holdings": {"AAPL": 20},
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
    candidates = tmp_path / "candidates.csv"
    candidates.write_text(
        "ticker,name,content_type,market,notes\nNVDA,Nvidia,stock,US,watchlist\n",
        encoding="utf-8",
    )

    payload = review_candidate_inputs(
        profile_paths=[profiles],
        candidate_files=[candidates],
        market_snapshot_dir=market_dir,
    )

    assert payload["artifact"] == "candidate_input_review"
    assert payload["llm_policy"].startswith("no external LLM")
    assert payload["summary"]["status"] == "pass"
    assert payload["summary"]["rows"] == 4
    assert payload["summary"]["errors"] == 0
    assert payload["summary"]["statuses"]["ready_input"] == 3
    assert payload["summary"]["statuses"]["seed_valid"] == 1
    seed = next(row for row in payload["rows"] if row["kind"] == "candidate_seed")
    assert seed["ticker"] == "NVDA"
    assert seed["issues"][0]["code"] == "seed_only"


@pytest.mark.unit
def test_review_candidate_inputs_flags_invalid_etf_profile(tmp_path):
    profiles = tmp_path / "profiles.json"
    profiles.write_text(
        json.dumps({
            "profile_type": "etf",
            "ticker": "BROKENETF",
            "holdings": {"AAPL": 20},
        }),
        encoding="utf-8",
    )

    payload = review_candidate_inputs(profile_paths=[profiles])

    assert payload["summary"]["status"] == "fail"
    assert payload["summary"]["errors"] == 2
    codes = payload["summary"]["issue_codes"]
    assert codes["etf_sectors_missing"] == 1
    assert codes["etf_countries_missing"] == 1


@pytest.mark.unit
def test_write_candidate_input_review_outputs_files(tmp_path):
    candidates = tmp_path / "candidates.csv"
    candidates.write_text("ticker,name,content_type,market,notes\n", encoding="utf-8")

    payload = write_candidate_input_review(
        output_dir=tmp_path / "out",
        candidate_files=[candidates],
    )

    assert payload["summary"]["status"] == "pass"
    assert payload["summary"]["statuses"]["empty"] == 1
    assert (tmp_path / "out" / "candidate_input_review.json").exists()
    markdown = (tmp_path / "out" / "candidate_input_review.md").read_text(encoding="utf-8")
    assert "# Candidate Input Review" in markdown
    assert "candidate_file_empty" in markdown
