import json

import pytest

from tradingagents.content_profiles import (
    final_state_from_profile,
    load_profiles,
    normalize_etf_profile,
    normalize_stock_profile,
    normalize_theme_profile,
)
from tradingagents.content_snapshot import build_content_snapshot


def _etf_profile():
    return normalize_etf_profile({
        "profile_type": "etf",
        "ticker": "DEMO2BAT.KS",
        "name": "국내 2차전지 ETF",
        "issuer": "Demo Asset",
        "benchmark": "Demo Battery Index",
        "expense_ratio_pct": "0.45",
        "holdings": {
            "셀 제조사": 18.5,
            "양극재": 14.2,
        },
        "sectors": {
            "Battery Cells": 38,
            "Materials": 34,
        },
        "countries": {
            "Korea": 82,
            "United States": 10,
        },
    })


def _theme_profile():
    return normalize_theme_profile({
        "profile_type": "theme",
        "ticker": "KR-AI-SEMI",
        "name": "AI 반도체",
        "description": "AI 수요와 함께 움직이는 반도체 밸류체인입니다.",
        "value_chain": [
            {
                "stage": "메모리",
                "domestic_names": [{"ticker": "DEMO-HBM", "name": "국내 HBM"}],
                "global_names": [{"ticker": "DEMO-MEM", "name": "글로벌 메모리"}],
            }
        ],
        "domestic_names": [{"ticker": "DEMO-HBM", "name": "국내 HBM"}],
        "global_names": [{"ticker": "DEMO-GPU", "name": "GPU 설계"}],
        "catalysts": [{"name": "AI 서버 투자 확대"}],
    })


def _stock_profile():
    return normalize_stock_profile({
        "profile_type": "stock",
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "exchange": "NASDAQ",
        "country": "United States",
        "currency": "USD",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "description": "iPhone, Mac, iPad, wearables, services를 함께 보는 글로벌 소비자 기술 기업입니다.",
        "business_lines": [
            {"name": "Products"},
            {"name": "Services"},
        ],
        "regions": [
            {"name": "Americas"},
            {"name": "Europe"},
            {"name": "Greater China"},
        ],
        "products": [
            {"name": "iPhone"},
            {"name": "Mac"},
            {"name": "Services"},
        ],
        "peers": [
            {"ticker": "MSFT", "name": "Microsoft"},
            {"ticker": "GOOGL", "name": "Alphabet"},
        ],
        "catalysts": [{"name": "신제품 사이클"}],
        "risks": [{"name": "중국 수요 둔화"}],
    })


@pytest.mark.unit
def test_stock_profile_builds_overseas_content_snapshot():
    profile = _stock_profile()
    state, ticker, generated_at = final_state_from_profile(profile)

    content = build_content_snapshot(state, ticker, generated_at)

    assert ticker == "AAPL"
    assert content["market_adapter"] == "US"
    assert content["content_type"] == "stock"
    assert content["publish_gate"]["status"] == "ready"
    assert content["composition_data"]["name"] == "Apple Inc."
    assert content["composition_data"]["products"][0]["name"] == "iPhone"
    assert next(v for v in content["visuals"] if v["id"] == "business_mix")["status"] == "ready"
    composition = next(card for card in content["cards"] if card["id"] == "composition")
    assert composition["status"] == "ready"
    assert "핵심 제품/서비스" in composition["body"]


@pytest.mark.unit
def test_etf_profile_builds_ready_content_snapshot():
    profile = _etf_profile()
    state, ticker, generated_at = final_state_from_profile(profile)

    content = build_content_snapshot(state, ticker, generated_at)

    assert content["market_adapter"] == "KR"
    assert content["content_type"] == "etf"
    assert content["publish_gate"]["status"] == "ready"
    assert content["composition_data"]["holdings"][0]["name"] == "셀 제조사"
    assert content["composition_data"]["sectors"][0]["name"] == "Battery Cells"
    assert all(v["status"] != "required_missing" for v in content["visuals"])
    composition = next(card for card in content["cards"] if card["id"] == "composition")
    assert composition["status"] == "ready"
    assert "셀 제조사 18.5%" in composition["body"]
    assert "Korea 82%" in composition["body"]


@pytest.mark.unit
def test_theme_profile_builds_ready_content_snapshot():
    profile = _theme_profile()
    state, ticker, generated_at = final_state_from_profile(profile)

    content = build_content_snapshot(state, ticker, generated_at)

    assert content["market_adapter"] == "KR"
    assert content["content_type"] == "theme"
    assert content["publish_gate"]["status"] == "ready"
    assert content["composition_data"]["value_chain"][0]["stage"] == "메모리"
    assert content["composition_data"]["global_names"][0]["name"] == "GPU 설계"
    composition = next(card for card in content["cards"] if card["id"] == "composition")
    assert composition["status"] == "ready"
    assert "밸류체인" in composition["body"]
    assert "국내 HBM" in composition["body"]


@pytest.mark.unit
def test_incomplete_etf_profile_stays_blocked():
    profile = normalize_etf_profile({
        "profile_type": "etf",
        "ticker": "DEMOETF.KS",
        "name": "구성 부족 ETF",
        "holdings": [{"name": "A", "weight_pct": 50}],
    })
    state, ticker, generated_at = final_state_from_profile(profile)

    content = build_content_snapshot(state, ticker, generated_at)

    assert content["publish_gate"]["status"] == "blocked"
    assert any("etf_sector_allocation" in reason for reason in content["publish_gate"]["reasons"])
    composition = next(card for card in content["cards"] if card["id"] == "composition")
    assert composition["status"] == "needs_structured_data"


@pytest.mark.unit
def test_load_profiles_supports_profile_list_payload(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps({"profiles": [_etf_profile(), _theme_profile()]}, ensure_ascii=False),
        encoding="utf-8",
    )

    profiles = load_profiles(path)

    assert [profile["profile_type"] for profile in profiles] == ["etf", "theme"]
    assert profiles[0]["holdings"][0]["weight_pct"] == 18.5


@pytest.mark.unit
def test_load_profiles_supports_directory_batches(tmp_path):
    (tmp_path / "a_stock.json").write_text(
        json.dumps({"profiles": [_stock_profile()]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "b_etf.json").write_text(
        json.dumps(_etf_profile(), ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "summary.json").write_text(
        json.dumps({"summary": {"not": "a profile"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    profiles = load_profiles(tmp_path)

    assert [profile["profile_type"] for profile in profiles] == ["stock", "etf"]
    assert profiles[0]["ticker"] == "AAPL"
    assert profiles[1]["ticker"] == "DEMO2BAT.KS"
