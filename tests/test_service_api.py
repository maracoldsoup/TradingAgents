import json
from pathlib import Path

import pytest

from tradingagents.service_api import ServiceApiConfig, create_app, load_ops_status


def _write(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _snapshot(ticker: str, kind: str, name: str):
    composition = {
        "profile_type": kind,
        "ticker": ticker,
        "name": name,
        "source": ".pilot/internal/profile.json",
        "products": [{"name": "제품"}],
    }
    if kind == "etf":
        composition = {
            "profile_type": "etf",
            "ticker": ticker,
            "name": name,
            "source": "issuer_download",
            "issuer": "VanEck",
            "benchmark": "MVIS US Listed Semiconductor 25 Index",
            "expense_ratio_pct": 0.35,
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
            "value_chain": [{"stage": "메모리", "domestic_names": [{"ticker": "000660", "name": "SK하이닉스"}]}],
            "domestic_names": [{"ticker": "000660", "name": "SK하이닉스", "role": "HBM"}],
            "global_names": [{"ticker": "NVDA", "name": "Nvidia", "role": "GPU"}],
            "catalysts": [{"name": "AI 서버 투자", "description": "데이터센터 증설"}],
            "risks": [{"name": "수출 규제", "description": "반도체 장비 규제"}],
        }
    return {
        "artifact": "content_snapshot",
        "ticker": ticker,
        "content_type": kind,
        "market_adapter": "KR" if ticker.startswith("KR") or ticker[0].isdigit() else "US",
        "trade_date": "2026-07-09",
        "cards": [
            {"id": "what_is_it", "status": "ready", "body": f"{name} 설명입니다."},
            {"id": "why_moved", "status": "ready", "body": "주요 배경입니다."},
            {"id": "composition", "status": "ready", "body": "구성 설명입니다."},
            {"id": "risk", "status": "ready", "bullets": ["데이터 부족 경고"]},
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
                "volume_vs_20d_avg": 1.4,
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
        content_summary_paths=(
            tmp_path / "ops" / "content_summary.json",
            tmp_path / "ops" / "profile_summary.json",
        ),
    )


def _seed(tmp_path: Path, config: ServiceApiConfig):
    _write(tmp_path / "assets" / "AAPL" / "content_snapshot.json", _snapshot("AAPL", "stock", "Apple Inc."))
    _write(tmp_path / "assets" / "SMH" / "content_snapshot.json", _snapshot("SMH", "etf", "VanEck Semiconductor ETF"))
    _write(tmp_path / "assets" / "KR-AI-SEMI" / "content_snapshot.json", _snapshot("KR-AI-SEMI", "theme", "AI 반도체 테마"))
    _write(config.candidate_queue_path, {
        "artifact": "candidate_queue",
        "target_candidates": 20,
        "summary": {
            "ready_for_local_pilot": 9,
            "markets": {"KR": 6, "US": 3},
            "content_types": {"stock": 4, "etf": 3, "theme": 2},
        },
        "gate": {"status": "needs_more_candidates"},
    })
    _write(config.candidate_gap_path, {
        "artifact": "candidate_gap",
        "status": "needs_inputs",
        "summary": {"ready_shortfall": 11},
    })
    _write(config.candidate_review_path, {
        "artifact": "candidate_input_review",
        "summary": {
            "status": "pass",
            "rows": 7,
            "errors": 0,
            "warnings": 0,
            "statuses": {"ready_input": 6, "empty": 1},
            "issue_codes": {"candidate_file_empty": 1},
        },
    })
    _write(config.assessment_path, {
        "artifact": "pilot_assessment",
        "llm_policy": "no external LLM API; local files only",
        "verdict": {
            "status": "continue_with_constraints",
            "recommendation": "more real candidates",
            "twelve_month_validation": {"required_now": False, "judgment": "too early"},
        },
        "aggregate": {
            "coverage": {"cost_statuses": {"pass": 2}},
        },
    })
    for path, reports, market_snapshots in (
        (config.content_summary_paths[0], 5, 5),
        (config.content_summary_paths[1], 4, 1),
    ):
        _write(path, {
            "summary": {
                "reports": reports,
                "publish_ready": reports,
                "publish_ready_pct": 100.0,
                "market_snapshots_attached": market_snapshots,
                "price_trend_ready": market_snapshots,
                "volume_change_ready": market_snapshots,
                "warnings": {},
            },
        })


@pytest.mark.unit
def test_service_api_lists_and_filters_public_assets(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    _seed(tmp_path, config)
    client = TestClient(create_app(config))

    response = client.get("/api/assets")
    assert response.status_code == 200
    body = response.json()
    assert body["artifact"] == "service_asset_list"
    assert body["count"] == 3
    assert {asset["kind"] for asset in body["assets"]} == {"stock", "etf", "theme"}
    assert ".pilot" not in json.dumps(body, ensure_ascii=False)

    etfs = client.get("/api/assets?kind=etf").json()
    assert etfs["count"] == 1
    assert etfs["assets"][0]["ticker"] == "SMH"

    search = client.get("/api/assets?q=apple").json()
    assert search["count"] == 1
    assert search["assets"][0]["id"] == "stock-aapl"


@pytest.mark.unit
def test_service_api_serves_public_home_page(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    _seed(tmp_path, config)
    client = TestClient(create_app(config))

    response = client.get("/")

    assert response.status_code == 200
    assert "Research Gateway" in response.text
    assert "오늘 먼저 볼 흐름" in response.text
    assert "왜 움직였고, 무엇으로 구성됐는지 바로 읽습니다" in response.text
    assert "오늘 움직인 흐름" in response.text
    assert "Theme Map" in response.text
    assert "ETF X-ray" in response.text
    assert "발행 후 실제 흐름" in response.text
    assert "종목·ETF·테마 전체" in response.text
    assert "Apple Inc." in response.text
    assert "VanEck Semiconductor ETF" in response.text
    assert "AI 반도체 테마" in response.text
    assert "/stocks/aapl" in response.text
    assert "/etfs/smh" in response.text
    assert "/themes/kr-ai-semi" in response.text
    assert "/search?kind=stock" in response.text
    assert "/search?kind=etf" in response.text
    assert "/search?kind=theme" in response.text
    assert "/search" in response.text
    assert "/review" in response.text
    assert "/learn" in response.text
    assert "처음 보는 ETF·테마" in response.text
    assert ".pilot" not in response.text
    assert "ready_shortfall" not in response.text
    assert "/api/ops/status" not in response.text
    assert 'href="/api/assets"' not in response.text


@pytest.mark.unit
def test_service_api_serves_public_search_page(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    _seed(tmp_path, config)
    client = TestClient(create_app(config))

    response = client.get("/search?q=apple")

    assert response.status_code == 200
    assert "종목·ETF·테마 검색" in response.text
    assert "종목 탐색" in response.text
    assert "ETF 구성" in response.text
    assert "섹터·테마" in response.text
    assert "검색 결과 1개" in response.text
    assert "Apple Inc." in response.text
    assert "/stocks/aapl" in response.text
    assert "VanEck Semiconductor ETF" not in response.text
    assert ".pilot" not in response.text

    etfs = client.get("/search?kind=etf")
    assert "검색 결과 1개" in etfs.text
    assert "VanEck Semiconductor ETF" in etfs.text

    themes = client.get("/search?kind=theme")
    assert "검색 결과 1개" in themes.text
    assert "AI 반도체 테마" in themes.text
    assert "Apple Inc." not in themes.text


@pytest.mark.unit
def test_service_api_serves_learn_page(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    _seed(tmp_path, config)
    client = TestClient(create_app(config))

    response = client.get("/learn")

    assert response.status_code == 200
    assert "ETF와 테마를 처음 보는 사람" in response.text
    assert "ETF란 무엇인가" in response.text
    assert "밸류체인" in response.text
    assert "환노출" in response.text


@pytest.mark.unit
def test_service_api_serves_review_page_and_api(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    _seed(tmp_path, config)
    client = TestClient(create_app(config))

    page = client.get("/review")

    assert page.status_code == 200
    assert "발행 후 사후 점검" in page.text
    assert "검증 로그" in page.text
    assert "+1.20%" in page.text
    assert "-2.30%" in page.text
    assert "1.40x" in page.text
    assert "추정 숫자" in page.text
    assert "/stocks/aapl" in page.text
    assert ".pilot" not in page.text

    api = client.get("/api/reviews").json()
    assert api["artifact"] == "service_review_list"
    assert api["count"] == 3
    first = api["reviews"][0]
    assert first["status"] == "available"
    assert first["metrics"]["return_5d_pct"] == -2.3
    assert ".pilot" not in json.dumps(api, ensure_ascii=False)


@pytest.mark.unit
def test_service_api_serves_public_asset_page(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    _seed(tmp_path, config)
    client = TestClient(create_app(config))

    response = client.get("/etfs/smh")

    assert response.status_code == 200
    assert "VanEck Semiconductor ETF" in response.text
    assert "왜 움직였나" in response.text
    assert "가격·거래량 스냅샷" in response.text
    assert "ETF 해부" in response.text
    assert "집중도" in response.text
    assert "환율/국가 노출" in response.text
    assert "MVIS US Listed Semiconductor 25 Index" in response.text
    assert "상위 보유 종목" in response.text
    assert "Nvidia" in response.text
    assert "주의 관점" in response.text
    assert "데이터 신뢰" in response.text
    assert "원천 데이터" in response.text or "출처" in response.text
    assert "시각화 상태" in response.text
    assert "시각화 보드" in response.text
    assert "issuer_download" in response.text
    assert ".pilot" not in response.text

    compatibility = client.get("/assets/etf-smh")
    assert compatibility.status_code == 200
    assert "VanEck Semiconductor ETF" in compatibility.text


@pytest.mark.unit
def test_service_api_serves_public_theme_detail_page(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    _seed(tmp_path, config)
    client = TestClient(create_app(config))

    response = client.get("/themes/kr-ai-semi")

    assert response.status_code == 200
    assert "AI 반도체 테마" in response.text
    assert "국내·해외 연결 지도" in response.text
    assert "국내 대표 종목" in response.text
    assert "해외 대표 종목" in response.text
    assert "촉매와 리스크" in response.text
    assert "SK하이닉스" in response.text
    assert "Nvidia" in response.text
    assert "AI 서버 투자" in response.text
    assert "수출 규제" in response.text
    assert ".pilot" not in response.text


@pytest.mark.unit
def test_service_api_serves_public_stock_detail_page(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    _seed(tmp_path, config)
    client = TestClient(create_app(config))

    response = client.get("/stocks/aapl")

    assert response.status_code == 200
    assert "Apple Inc." in response.text
    assert "가격·거래량 스냅샷" in response.text
    assert "종목 읽기 순서" in response.text
    assert "제품/사업" in response.text
    assert "비교 대상" in response.text
    assert "+1.20%" in response.text
    assert "1.40x" in response.text
    assert ".pilot" not in response.text


@pytest.mark.unit
def test_service_api_serves_ops_console_separately(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    _seed(tmp_path, config)
    client = TestClient(create_app(config))

    response = client.get("/ops")

    assert response.status_code == 200
    assert "Research Gateway Ops" in response.text
    assert "control plane" in response.text
    assert "Service Health" in response.text
    assert "Source Intake" in response.text
    assert "Collection Workers" in response.text
    assert "Cost Guard" in response.text
    assert "Publish Gate" in response.text
    assert "Candidate Queue" in response.text
    assert "Next Slots" in response.text
    assert "9 / 20" in response.text
    assert "needs_more_candidates" in response.text
    assert "paid model" in response.text
    assert "locked" in response.text
    assert "/api/ops/status" in response.text


@pytest.mark.unit
def test_service_api_serves_asset_detail_and_themes(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    _seed(tmp_path, config)
    client = TestClient(create_app(config))

    detail = client.get("/api/assets/etf-smh")
    assert detail.status_code == 200
    asset = detail.json()["asset"]
    assert asset["composition"]["holdings"][0]["ticker"] == "NVDA"
    assert ".pilot" not in json.dumps(asset, ensure_ascii=False)

    themes = client.get("/api/themes").json()
    assert themes["count"] == 1
    assert themes["themes"][0]["id"] == "theme-kr-ai-semi"

    missing = client.get("/api/assets/not-real")
    assert missing.status_code == 404


@pytest.mark.unit
def test_service_api_ops_status_is_separate_from_public_assets(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    _seed(tmp_path, config)
    client = TestClient(create_app(config))

    status = client.get("/api/ops/status").json()

    assert status == load_ops_status(config)
    assert status["artifact"] == "service_ops_status"
    assert status["ready_candidates"] == 9
    assert status["ready_shortfall"] == 11
    assert status["queue_status"] == "needs_more_candidates"
    assert status["source_health"]["status"] == "pass"
    assert status["source_health"]["ready_inputs"] == 6
    assert status["collection"]["status"] == "pass"
    assert status["collection"]["totals"]["reports"] == 9
    assert status["collection"]["totals"]["market_snapshots_attached"] == 6
    assert status["cost_guard"]["status"] == "pass"
    assert status["cost_guard"]["paid_model_allowed"] is False
    assert status["cost_guard"]["twelve_month_required_now"] is False
    assert status["publish"]["public_assets"] == 3
    assert status["publish"]["publish_ready_assets"] == 3
    assert status["publish"]["by_kind"] == {"stock": 1, "etf": 1, "theme": 1}
    assert "paths" not in status
    assert ".pilot" not in json.dumps(status, ensure_ascii=False)
