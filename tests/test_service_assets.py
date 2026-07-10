import json

import pytest

from tradingagents.service_assets import (
    asset_from_snapshot,
    asset_id,
    find_asset,
    load_assets,
    theme_assets,
)


def _snapshot(ticker="AAPL", kind="stock", composition=None):
    return {
        "artifact": "content_snapshot",
        "ticker": ticker,
        "content_type": kind,
        "market_adapter": "US" if kind != "theme" else "KR",
        "trade_date": "2026-07-09",
        "cards": [
            {"id": "what_is_it", "title": "무엇인가", "status": "ready", "body": "AAPL은 소비자 기기와 서비스를 파는 회사입니다."},
            {"id": "why_moved", "title": "왜 움직였나", "status": "ready", "body": "신제품 기대와 서비스 매출이 주요 배경입니다."},
            {"id": "composition", "title": "구성", "status": "ready", "body": "제품과 서비스로 구성됩니다."},
            {
                "id": "bull_bear",
                "title": "매수/매도 내러티브",
                "status": "ready",
                "bull": {"bullets": ["서비스 매출 확대", "신제품 사이클"]},
                "bear": {"bullets": ["중국 수요 둔화", "밸류에이션 부담"]},
            },
            {"id": "risk", "title": "리스크", "status": "ready", "bullets": ["환율과 규제 리스크"]},
            {"id": "watch_next", "title": "다음 관찰", "status": "ready", "bullets": ["다음 실적 발표"]},
        ],
        "visuals": [{"id": "price_trend", "title": "가격 추이", "type": "line", "status": "ready"}],
        "market_data": {
            "source": "toss_securities_openapi",
            "snapshot_file": ".pilot/toss_market/internal.json",
            "metrics": {
                "return_1d_pct": -0.5,
                "return_5d_pct": 3.2,
                "return_20d_pct": 7.4,
                "volume_vs_20d_avg": 1.25,
            },
        },
        "composition_data": composition or {
            "profile_type": "stock",
            "ticker": ticker,
            "name": "Apple Inc.",
            "source": "docs/examples/private_profile.json",
            "products": [{"name": "iPhone"}, {"name": "Services"}],
            "regions": [{"name": "Americas", "weight_pct": 42}],
        },
        "publish_gate": {"status": "ready"},
    }


@pytest.mark.unit
def test_asset_from_stock_snapshot_hides_internal_paths():
    asset = asset_from_snapshot(_snapshot())

    assert asset["id"] == "stock-aapl"
    assert asset["kind"] == "stock"
    assert asset["ticker"] == "AAPL"
    assert asset["name"] == "Apple Inc."
    assert asset["one_liner"]["summary"].startswith("AAPL은")
    assert asset["why_moved"]["summary"].startswith("신제품")
    assert asset["bull_points"] == ["서비스 매출 확대", "신제품 사이클"]
    assert asset["bear_points"] == ["중국 수요 둔화", "밸류에이션 부담"]
    assert asset["risk_points"] == ["환율과 규제 리스크"]
    assert asset["watch_points"] == ["다음 실적 발표"]
    assert asset["composition"]["products"][0]["name"] == "iPhone"
    assert asset["sources"] == [
        {"kind": "market_data", "label": "toss_securities_openapi"},
        {"kind": "composition", "label": "structured_profile"},
    ]
    assert asset["review"]["status"] == "available"
    assert asset["review"]["published_at"] == "2026-07-09"
    assert asset["review"]["metrics"] == {
        "return_1d_pct": -0.5,
        "return_5d_pct": 3.2,
        "return_20d_pct": 7.4,
        "volume_vs_20d_avg": 1.25,
    }
    assert asset["review"]["basis"].startswith("신제품")
    assert ".pilot" not in json.dumps(asset, ensure_ascii=False)
    assert "docs/examples" not in json.dumps(asset, ensure_ascii=False)


@pytest.mark.unit
def test_asset_name_prefers_korean_name_already_present_in_cards():
    snapshot = _snapshot(
        ticker="068270.KS",
        composition={
            "profile_type": "stock",
            "ticker": "068270.KS",
            "source": "local_report",
        },
    )
    snapshot["market_adapter"] = "KR"
    snapshot["cards"][0]["body"] = "068270.KS는 Celltrion, Inc.입니다. 사업 분류는 Healthcare / Biotechnology입니다."
    snapshot["cards"][1]["body"] = "금리와 바이오 업종 흐름을 보는 가운데 셀트리온(068270.KS)이 주목받았습니다."

    asset = asset_from_snapshot(snapshot)

    assert asset["name"] == "셀트리온"
    assert ".pilot" not in json.dumps(asset, ensure_ascii=False)


@pytest.mark.unit
def test_asset_name_uses_english_card_name_when_no_better_name_exists():
    snapshot = _snapshot(
        ticker="AAPL",
        composition={
            "profile_type": "stock",
            "ticker": "AAPL",
            "source": "local_report",
        },
    )
    snapshot["cards"][0]["body"] = "AAPL는 Apple Inc.입니다. 사업 분류는 Technology / Consumer Electronics입니다."

    asset = asset_from_snapshot(snapshot)

    assert asset["name"] == "Apple Inc."


@pytest.mark.unit
def test_asset_from_etf_snapshot_exposes_holdings_allocations():
    asset = asset_from_snapshot(_snapshot(
        ticker="DEMOETF",
        kind="etf",
        composition={
            "profile_type": "etf",
            "ticker": "DEMOETF",
            "name": "글로벌 AI ETF",
            "source": "issuer_download",
            "issuer": "Demo Asset",
            "benchmark": "Demo AI Index",
            "expense_ratio_pct": 0.25,
            "holdings": [
                {"ticker": "NVDA", "name": "Nvidia", "sector": "Semiconductors", "country": "United States", "weight_pct": 22.5}
            ],
            "sectors": [{"name": "Semiconductors", "weight_pct": 70}],
            "countries": [{"name": "United States", "weight_pct": 88}],
            "as_of": "2026-07-09",
        },
    ))

    assert asset["id"] == "etf-demoetf"
    assert asset["kind"] == "etf"
    assert asset["composition"]["holdings"][0]["ticker"] == "NVDA"
    assert asset["composition"]["sectors"][0]["weight_pct"] == 70
    assert asset["composition"]["countries"][0]["name"] == "United States"
    assert asset["composition"]["expense_ratio_pct"] == 0.25
    assert asset["as_of"] == "2026-07-09"
    assert asset["review"]["status"] == "available"


@pytest.mark.unit
def test_asset_review_is_pending_without_market_metrics():
    snapshot = _snapshot()
    snapshot["market_data"] = {}

    asset = asset_from_snapshot(snapshot)

    assert asset["review"]["status"] == "pending"
    assert asset["review"]["metrics"] == {}
    assert asset["review"]["note"] == "market metrics pending"


@pytest.mark.unit
def test_asset_from_theme_snapshot_exposes_value_chain():
    asset = asset_from_snapshot(_snapshot(
        ticker="KR-AI-SEMI",
        kind="theme",
        composition={
            "profile_type": "theme",
            "ticker": "KR-AI-SEMI",
            "name": "AI 반도체 테마",
            "description": "AI 인프라 투자와 함께 보는 밸류체인입니다.",
            "value_chain": [
                {
                    "stage": "메모리",
                    "description": "HBM과 고성능 DRAM",
                    "domestic_names": [{"ticker": "000660", "name": "SK하이닉스", "role": "메모리"}],
                    "global_names": [{"ticker": "MU", "name": "Micron", "role": "메모리"}],
                }
            ],
            "domestic_names": [{"ticker": "000660", "name": "SK하이닉스", "role": "메모리"}],
            "global_names": [{"ticker": "NVDA", "name": "Nvidia", "role": "GPU"}],
            "catalysts": [{"name": "AI 서버 투자"}],
            "risks": [{"name": "수출 규제"}],
        },
    ))

    assert asset["id"] == "theme-kr-ai-semi"
    assert asset["kind"] == "theme"
    assert asset["composition"]["value_chain"][0]["stage"] == "메모리"
    assert asset["composition"]["value_chain"][0]["domestic_names"][0]["name"] == "SK하이닉스"
    assert asset["composition"]["global_names"][0]["ticker"] == "NVDA"
    assert theme_assets([asset]) == [asset]


@pytest.mark.unit
def test_load_assets_from_snapshot_directories_and_find_asset(tmp_path):
    first = tmp_path / "profiles" / "AAPL"
    second = tmp_path / "profiles" / "DEMOETF"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "content_snapshot.json").write_text(
        json.dumps(_snapshot(), ensure_ascii=False),
        encoding="utf-8",
    )
    (second / "content_snapshot.json").write_text(
        json.dumps(_snapshot(ticker="DEMOETF", kind="etf"), ensure_ascii=False),
        encoding="utf-8",
    )

    assets = load_assets([tmp_path / "profiles"])

    assert [asset["id"] for asset in assets] == ["stock-aapl", "etf-demoetf"]
    assert find_asset(assets, "stock-aapl")["ticker"] == "AAPL"
    assert find_asset(assets, "missing") is None
    assert asset_id("stock", "068270.KS") == "stock-068270-ks"
