import json
from pathlib import Path

import pytest

from tradingagents.pilot_api import PilotApiConfig, create_app, load_pilot_status


def _write(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _config(tmp_path: Path) -> PilotApiConfig:
    output_root = tmp_path / ".pilot"
    return PilotApiConfig(
        reports_dir=tmp_path / "reports",
        output_root=output_root,
        market_snapshot_dir=output_root / "toss_market",
        local_pilot_reports=(output_root / "local" / "local_pilot_report.json",),
        profile_paths=(tmp_path / "profiles.json",),
        candidate_files=(tmp_path / "candidates.csv",),
        target_candidates=20,
    )


def _seed_artifacts(config: PilotApiConfig):
    _write(config.candidate_input_review_file, {
        "artifact": "candidate_input_review",
        "summary": {"status": "pass", "rows": 1, "issue_codes": {}},
    })
    _write(config.candidate_queue_file, {
        "artifact": "candidate_queue",
        "target_candidates": 20,
        "summary": {"ready_for_local_pilot": 9},
        "gate": {"status": "needs_more_candidates"},
        "rows": [{"ticker": "AAPL", "content_type": "stock", "market": "US", "status": "ready_for_local_pilot"}],
    })
    _write(config.candidate_gap_file, {
        "artifact": "candidate_gap",
        "status": "needs_inputs",
        "summary": {"ready_shortfall": 11},
    })
    _write(config.assessment_file, {
        "artifact": "pilot_assessment",
        "verdict": {"status": "continue_with_constraints", "recommendation": "Continue local-only"},
    })
    _write(config.local_pilot_reports[0], {
        "artifact": "local_pilot_report",
        "gate": {"status": "pass"},
        "cost_guard": {"status": "pass", "score": 100},
        "content_pilot": {"summary": {}},
        "content_quality": {"summary": {}},
        "profile_pilot": {"summary": {}},
        "profile_content_quality": {"summary": {}},
    })
    config.dashboard_file.parent.mkdir(parents=True, exist_ok=True)
    config.dashboard_file.write_text("<!doctype html><h1>Dashboard</h1>", encoding="utf-8")
    _write(config.output_root / "profile_content" / "AAPL_stock" / "content_snapshot.json", {
        "artifact": "content_snapshot",
        "ticker": "AAPL",
        "content_type": "stock",
        "market_adapter": "US",
        "generated_at": "2026-07-09T10:00:00",
        "publish_gate": {"status": "ready"},
        "cards": [
            {"id": "what_is_it", "title": "무엇인가", "body": "Apple Inc.는 소비자 기기와 서비스를 파는 회사입니다."},
            {"id": "why_moved", "title": "왜 움직였나", "body": "신제품 기대와 서비스 매출이 주요 배경입니다."},
            {"id": "composition", "title": "구성", "body": "iPhone, Services, Mac으로 구성됩니다."},
            {
                "id": "bull_bear",
                "title": "내러티브",
                "bull": {"headline": "서비스 매출 확대"},
                "bear": {"headline": "중국 수요 둔화"},
            },
        ],
        "visuals": [{"id": "business_mix", "title": "사업 구성", "status": "ready"}],
        "composition_data": {
            "profile_type": "stock",
            "name": "Apple Inc.",
            "products": [{"name": "iPhone"}, {"name": "Services"}],
            "catalysts": [{"name": "신제품 사이클"}],
        },
    })


@pytest.mark.unit
def test_load_pilot_status_reads_local_artifacts(tmp_path):
    config = _config(tmp_path)
    _seed_artifacts(config)

    status = load_pilot_status(config)

    assert status["artifact"] == "pilot_api_status"
    assert status["llm_policy"].startswith("no external LLM")
    assert status["status"] == "continue_with_constraints"
    assert status["ready_candidates"] == 9
    assert status["ready_shortfall"] == 11
    assert status["input_review_status"] == "pass"


@pytest.mark.unit
def test_pilot_api_serves_status_artifacts_and_candidates(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    _seed_artifacts(config)
    client = TestClient(create_app(config))

    index = client.get("/")
    assert index.status_code == 200
    assert "Research Gateway" in index.text
    assert "Apple Inc." in index.text
    assert "Cloudflare" in index.text

    console = client.get("/console")
    assert console.status_code == 200
    assert "TradingAgents Pilot Console" in console.text
    assert "candidateForm" in console.text

    ops = client.get("/ops")
    assert ops.status_code == 200
    assert "Dashboard" in ops.text

    status = client.get("/api/pilot/status").json()
    assert status["ready_candidates"] == 9
    assert status["candidate_queue_status"] == "needs_more_candidates"

    service = client.get("/api/pilot/service").json()
    assert service["items"][0]["ticker"] == "AAPL"
    assert service["items"][0]["content_type"] == "stock"

    artifacts = client.get("/api/pilot/artifacts").json()
    assert any(item["name"] == "candidate_queue" for item in artifacts["artifacts"])

    queue = client.get("/api/pilot/artifacts/candidate_queue").json()
    assert queue["artifact"] == "candidate_queue"

    candidates = client.get("/api/pilot/candidates").json()
    assert candidates["rows"][0]["ticker"] == "AAPL"

    missing = client.get("/api/pilot/artifacts/not-real")
    assert missing.status_code == 404


@pytest.mark.unit
def test_pilot_api_rebuilds_local_only_artifacts(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    reports = config.reports_dir / "005930.KS_20260709_090000"
    (reports / "5_portfolio").mkdir(parents=True)
    _write(reports / "analysis_snapshot.json", {
        "artifact": "analysis_snapshot",
        "ticker": "005930.KS",
        "asset_type": "stock",
    })
    _write(reports / "5_portfolio" / "signal.json", {"action": "Hold"})
    _write(config.market_snapshot_dir / "snapshot.json", {
        "artifact": "toss_market_snapshot",
        "symbols": ["005930"],
        "stocks": [{"symbol": "005930"}],
        "prices": [{"symbol": "005930"}],
        "candles": {"005930": [{"closePrice": "70000"}]},
    })
    _write(tmp_path / "profiles.json", {
        "profiles": [
            {
                "profile_type": "stock",
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "currency": "USD",
                "exchange": "NASDAQ",
                "products": ["iPhone"],
            },
            {
                "profile_type": "etf",
                "ticker": "DEMOETF",
                "holdings": {"AAPL": 20},
                "sectors": {"Technology": 80},
                "countries": {"United States": 90},
            },
            {
                "profile_type": "theme",
                "ticker": "KR-AI-SEMI",
                "value_chain": [{"stage": "설계", "global_names": ["NVDA"]}],
                "global_names": ["NVDA"],
            },
        ]
    })
    (tmp_path / "candidates.csv").write_text("ticker,name,content_type,market,notes\n", encoding="utf-8")
    _write(config.local_pilot_reports[0], {
        "artifact": "local_pilot_report",
        "gate": {"status": "pass"},
        "cost_guard": {"status": "pass", "score": 100},
        "content_pilot": {"summary": {"reports": 1, "publish_ready_pct": 100}},
        "content_quality": {"summary": {"pass_pct": 100, "avg_score": 100}},
        "profile_pilot": {"summary": {"reports": 3, "publish_ready_pct": 100}},
        "profile_content_quality": {"summary": {"pass_pct": 100, "avg_score": 100}},
    })

    client = TestClient(create_app(config))
    response = client.post("/api/pilot/rebuild")

    assert response.status_code == 200
    body = response.json()
    assert body["artifact"] == "pilot_api_status"
    assert config.candidate_queue_file.exists()
    assert config.candidate_gap_file.exists()
    assert config.assessment_file.exists()
    assert config.dashboard_file.exists()


@pytest.mark.unit
def test_pilot_api_adds_candidate_seed_and_profile(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    config = _config(tmp_path)
    _seed_artifacts(config)
    client = TestClient(create_app(config))

    seed = client.post("/api/pilot/candidate-seeds", json={
        "ticker": "NVDA",
        "name": "Nvidia",
        "content_type": "stock",
        "market": "US",
        "notes": "manual test",
    })
    assert seed.status_code == 200
    assert "NVDA" in (tmp_path / "candidates.csv").read_text(encoding="utf-8")

    profile = client.post("/api/pilot/profiles", json={
        "profile_type": "etf",
        "ticker": "DEMOETF2",
        "name": "Demo ETF 2",
        "holdings": [{"ticker": "AAPL", "name": "Apple", "weight_pct": 25}],
        "sectors": [{"name": "Technology", "weight_pct": 80}],
        "countries": [{"name": "United States", "weight_pct": 90}],
    })
    assert profile.status_code == 200
    assert config.manual_profile_file.exists()

    candidates = client.get("/api/pilot/candidates").json()["rows"]
    demo = next(row for row in candidates if row["ticker"] == "DEMOETF2")
    assert demo["status"] == "ready_for_local_pilot"

    invalid_seed = client.post("/api/pilot/candidate-seeds", json={"content_type": "stock"})
    assert invalid_seed.status_code == 400

    invalid_profile = client.post("/api/pilot/profiles", json={"ticker": "BAD"})
    assert invalid_profile.status_code == 400
