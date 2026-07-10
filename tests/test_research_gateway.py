import json
from pathlib import Path

import pytest

from tradingagents.research_gateway import ServiceApiConfig, create_app


def _write(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _snapshot(ticker: str, kind: str, name: str):
    composition = {
        "profile_type": kind,
        "ticker": ticker,
        "name": name,
        "source": "structured_profile",
        "products": [{"name": "제품", "weight_pct": 55}],
        "regions": [{"name": "Americas", "weight_pct": 42}],
    }
    if kind == "etf":
        composition = {
            "profile_type": "etf",
            "ticker": ticker,
            "name": name,
            "source": "issuer_download",
            "issuer": "VanEck",
            "benchmark": "MVIS US Listed Semiconductor 25 Index",
            "holdings": [
                {"ticker": "NVDA", "name": "Nvidia", "weight_pct": 20},
                {"ticker": "TSM", "name": "TSMC", "weight_pct": 11},
            ],
            "sectors": [{"name": "Semiconductors", "weight_pct": 70}],
            "countries": [{"name": "United States", "weight_pct": 90}],
        }
    if kind == "theme":
        composition = {
            "profile_type": "theme",
            "ticker": ticker,
            "name": name,
            "source": "manual_theme_map",
            "value_chain": [
                {
                    "stage": "메모리",
                    "description": "HBM과 고성능 DRAM",
                    "domestic_names": [{"ticker": "000660", "name": "SK하이닉스"}],
                    "global_names": [{"ticker": "MU", "name": "Micron"}],
                }
            ],
        }
    return {
        "artifact": "content_snapshot",
        "ticker": ticker,
        "content_type": kind,
        "market_adapter": "KR" if kind == "theme" else "US",
        "trade_date": "2026-07-09",
        "cards": [
            {"id": "what_is_it", "status": "ready", "body": f"{name} 설명입니다."},
            {"id": "why_moved", "status": "ready", "body": "주요 배경입니다."},
            {"id": "bull_bear", "status": "ready", "bull": {"bullets": ["상승 요인"]}, "bear": {"bullets": ["주의 요인"]}},
            {"id": "watch_next", "status": "ready", "bullets": ["다음 이벤트"]},
        ],
        "visuals": [{"id": "price_trend", "title": "가격 추이", "status": "ready"}],
        "market_data": {
            "source": "toss_securities_openapi",
            "snapshot_file": ".pilot/internal/snapshot.json",
            "metrics": {
                "return_1d_pct": 1.2,
                "return_5d_pct": -2.3,
                "return_20d_pct": 4.5,
            },
        },
        "composition_data": composition,
        "publish_gate": {"status": "ready"},
    }


def _config(tmp_path: Path) -> ServiceApiConfig:
    return ServiceApiConfig(
        asset_dirs=(tmp_path / "assets",),
        candidate_queue_path=tmp_path / "ops" / "candidate_queue.json",
        candidate_gap_path=tmp_path / "ops" / "candidate_gap.json",
        candidate_review_path=tmp_path / "ops" / "candidate_input_review.json",
        assessment_path=tmp_path / "ops" / "pilot_assessment.json",
    )


def _seed(tmp_path: Path, config: ServiceApiConfig):
    _write(tmp_path / "assets" / "AAPL" / "content_snapshot.json", _snapshot("AAPL", "stock", "Apple Inc."))
    _write(tmp_path / "assets" / "SMH" / "content_snapshot.json", _snapshot("SMH", "etf", "VanEck Semiconductor ETF"))
    _write(tmp_path / "assets" / "KR-AI-SEMI" / "content_snapshot.json", _snapshot("KR-AI-SEMI", "theme", "AI 반도체 테마"))
    _write(config.candidate_queue_path, {"summary": {"ready_for_local_pilot": 3}, "target_candidates": 20})
    _write(config.candidate_gap_path, {"summary": {"ready_shortfall": 17}})
    _write(config.assessment_path, {
        "verdict": {"status": "continue_with_constraints", "twelve_month_validation": {"required_now": False}},
        "aggregate": {"coverage": {"cost_statuses": {"pass": 1}}},
    })


@pytest.mark.unit
def test_research_gateway_home_is_public_service_not_ops_console(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    _seed(tmp_path, config)
    client = TestClient(create_app(config))

    response = client.get("/")

    assert response.status_code == 200
    assert "시장 이슈를 종목, ETF, 테마로 번역합니다" in response.text
    assert "왜 움직였나" in response.text
    assert "Theme Map" in response.text
    assert "ETF X-ray" in response.text
    assert "위키 라이브러리" in response.text
    assert "market-rails" in response.text
    assert "--navy:#1E3A5F" in response.text
    assert "--blue:#2563EB" in response.text
    assert "lime" not in response.text.lower()
    assert "purple" not in response.text.lower()
    assert "gradient" not in response.text.lower()
    assert "Cost Guard" not in response.text
    assert "/api/ops/status" not in response.text
    assert 'href="/api/assets"' not in response.text
    assert ".pilot" not in response.text


@pytest.mark.unit
def test_research_gateway_routes_assets_and_reviews(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    _seed(tmp_path, config)
    client = TestClient(create_app(config))

    etf = client.get("/etfs/smh")
    assert etf.status_code == 200
    assert "ETF 구성" in etf.text
    assert "상위 보유 종목" in etf.text
    assert "섹터 비중" in etf.text
    assert "국가 비중" in etf.text
    assert ".pilot" not in etf.text

    theme = client.get("/themes/kr-ai-semi")
    assert theme.status_code == 200
    assert "테마 밸류체인" in theme.text
    assert "메모리" in theme.text

    reviews = client.get("/api/reviews").json()
    assert reviews["artifact"] == "service_review_list"
    assert reviews["count"] == 3
    assert reviews["reviews"][0]["metrics"]["return_5d_pct"] == -2.3
    assert ".pilot" not in json.dumps(reviews, ensure_ascii=False)
