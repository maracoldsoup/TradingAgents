import json

import pytest

from tradingagents.content_profiles import final_state_from_profile
from tradingagents.content_snapshot import build_content_snapshot
from tradingagents.etf_profile_importer import import_etf_profile


@pytest.mark.unit
def test_import_etf_profile_from_local_csv_aggregates_allocations(tmp_path):
    holdings = tmp_path / "holdings.csv"
    holdings.write_text(
        "\n".join([
            "Ticker,Name,Weight (%),Sector,Country",
            "DEMO-GPU,GPU 설계 데모,21.0,Semiconductors,United States",
            "DEMO-CLOUD,클라우드 인프라 데모,15.5,Cloud Infrastructure,United States",
            "DEMO-HBM,HBM 메모리 데모,10.8,Memory,Korea",
            "DEMO-POWER,데이터센터 전력 데모,7.2,Power Equipment,United States",
        ]),
        encoding="utf-8",
    )

    profile = import_etf_profile(
        holdings_path=holdings,
        ticker="DEMOUSAI",
        name="글로벌 AI 인프라 ETF 데모",
        issuer="Demo Asset",
        currency="USD",
        as_of="2026-07-09",
        source="unit_test_csv",
    )

    assert profile["profile_type"] == "etf"
    assert profile["holdings"][0]["ticker"] == "DEMO-GPU"
    assert profile["holdings"][0]["weight_pct"] == 21.0
    assert profile["sectors"][0] == {"name": "Semiconductors", "weight_pct": 21.0}
    assert profile["countries"][0] == {"name": "United States", "weight_pct": 43.7}

    state, ticker, generated_at = final_state_from_profile(profile)
    content = build_content_snapshot(state, ticker, generated_at)

    assert content["publish_gate"]["status"] == "ready"
    assert content["composition_data"]["sectors"][0]["name"] == "Semiconductors"
    assert next(v for v in content["visuals"] if v["id"] == "etf_top_holdings")["status"] == "ready"


@pytest.mark.unit
def test_import_etf_profile_supports_fraction_weights_from_json(tmp_path):
    holdings = tmp_path / "holdings.json"
    holdings.write_text(
        json.dumps([
            {"symbol": "AAA", "name": "AAA Corp", "weight": 0.4, "sector": "Tech", "country": "US"},
            {"symbol": "BBB", "name": "BBB Corp", "weight": 0.35, "sector": "Tech", "country": "US"},
            {"symbol": "CCC", "name": "CCC Corp", "weight": 0.25, "sector": "Health", "country": "KR"},
        ]),
        encoding="utf-8",
    )

    profile = import_etf_profile(
        holdings_path=holdings,
        ticker="DEMOETF",
        weight_scale="auto",
    )

    assert [row["weight_pct"] for row in profile["holdings"]] == [40.0, 35.0, 25.0]
    assert profile["sectors"] == [
        {"name": "Tech", "weight_pct": 75.0},
        {"name": "Health", "weight_pct": 25.0},
    ]
