"""Tests for the live dashboard (dashboard/events.py, dashboard/server.py)."""

from __future__ import annotations

import json

import pytest

from tradingagents.dashboard.events import DashboardEventTranslator, summarize_content


def _types(events):
    return [e["type"] for e in events]


def test_translator_emits_reports_once():
    tr = DashboardEventTranslator()
    chunk = {"market_report": "기술적 분석 결과", "news_report": ""}
    events = tr.translate(chunk)
    assert _types(events) == ["report"]
    assert events[0]["agent"] == "market"
    assert events[0]["summary"] == "기술적 분석 결과"
    assert "bullets" in events[0]
    # 같은 내용 재수신 시 재발행 금지 (values 스트림은 상태를 반복 노출)
    assert tr.translate(chunk) == []


def test_translator_debate_deltas_are_incremental():
    tr = DashboardEventTranslator()
    first = {"investment_debate_state": {"bull_history": "Bull: 저평가 구간입니다."}}
    events = tr.translate(first)
    assert _types(events) == ["debate"]
    assert events[0]["speaker"] == "bull"

    grown = {
        "investment_debate_state": {
            "bull_history": "Bull: 저평가 구간입니다.\nBull: 수급도 개선 중입니다.",
            "bear_history": "Bear: 재료 소멸 위험이 있습니다.",
        }
    }
    events = tr.translate(grown)
    speakers = [(e["speaker"], e["content"]) for e in events]
    assert ("bull", "Bull: 수급도 개선 중입니다.") in speakers
    assert any(s == "bear" for s, _ in speakers)


def test_translator_final_event_carries_standard_rating():
    tr = DashboardEventTranslator()
    chunk = {"final_trade_decision": "**Rating**: Overweight\n\n비중 확대 권고"}
    events = tr.translate(chunk)
    final = [e for e in events if e["type"] == "final"]
    assert len(final) == 1
    assert final[0]["rating"] == "Overweight"
    assert final[0]["action"] == "Buy"
    assert final[0]["bias"] == "bullish"
    assert final[0]["headline"]
    # 재발행 금지
    assert tr.translate(chunk) == []


def test_translator_telemetry_and_risk_and_trader():
    tr = DashboardEventTranslator()
    chunk = {
        "analyst_telemetry": {"market": {"seconds": 12.0, "tool_calls": 5}},
        "trader_investment_plan": "**Action**: Buy",
        "risk_debate_state": {"aggressive_history": "Aggressive: 비중 상단 제안"},
    }
    events = tr.translate(chunk)
    kinds = _types(events)
    assert "telemetry" in kinds and "trader" in kinds and "risk" in kinds


def test_sse_stream_end_to_end_with_fake_graph(tmp_path):
    fastapi = pytest.importorskip("fastapi")  # noqa: F841
    from fastapi.testclient import TestClient

    from tradingagents.dashboard.server import create_app

    class FakeGraph:
        """propagate(on_chunk=...) 계약만 흉내내는 그래프 대역."""

        def __init__(self):
            self.saved = False

        def propagate(self, ticker, trade_date, asset_type="stock", on_chunk=None):
            chunks = [
                {"market_report": "차트 요약"},
                {
                    "market_report": "차트 요약",
                    "investment_debate_state": {"bull_history": "Bull: 매수"},
                },
                {
                    "market_report": "차트 요약",
                    "final_trade_decision": "**Rating**: Hold\n관망",
                },
            ]
            for c in chunks:
                on_chunk(c)
            return {}, "HOLD"

        def save_reports(self, final_state, ticker, save_path=None):
            # Model the real contract: write_report_tree returns a DIRECTORY.
            self.saved = True
            report_dir = tmp_path / "reports" / "005930.KS_20260707"
            (report_dir / "1_analysts").mkdir(parents=True)
            (report_dir / "1_analysts" / "market.md").write_text("# 차트", encoding="utf-8")
            (report_dir / "decision.md").write_text("# 최종", encoding="utf-8")
            return report_dir

    app = create_app(graph_factory=FakeGraph)
    client = TestClient(app)

    with client.stream("GET", "/api/stream?ticker=005930.KS") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        payloads = []
        for line in resp.iter_lines():
            if line.startswith("data: "):
                payloads.append(json.loads(line[len("data: "):]))

    kinds = [p["type"] for p in payloads]
    assert kinds[0] == "stage" and payloads[0]["stage"] == "start"
    assert "report" in kinds and "debate" in kinds and "final" in kinds
    assert "artifact" in kinds
    artifact = [p for p in payloads if p["type"] == "artifact"][0]
    assert artifact["kind"] == "complete_report"
    assert artifact["path"].endswith("dossier.md")
    assert artifact["download_url"].startswith("/api/artifacts/")
    report = client.get(artifact["download_url"])
    assert report.status_code == 200
    assert "# 차트" in report.text and "# 최종" in report.text
    report_text = client.get(artifact["text_url"])
    assert "# 차트" in report_text.text and "# 최종" in report_text.text
    assert kinds[-1] == "stage" and payloads[-1]["stage"] == "done"
    assert payloads[-1]["decision"] == "HOLD"


def test_dashboard_index_and_search_api():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from tradingagents.dashboard.server import create_app

    app = create_app(
        graph_factory=lambda: None,
        name_map_provider=lambda: {"005930": "삼성전자", "247540": "에코프로비엠"},
        suffix_prober=lambda t: t == "247540.KQ",
    )
    client = TestClient(app)

    html = client.get("/")
    assert html.status_code == 200
    assert "EventSource" in html.text and "/api/search" in html.text

    rows = client.get("/api/search?q=삼성").json()["results"]
    assert rows and rows[0]["code"] == "005930" and rows[0]["market"] == "KR"

    rows = client.get("/api/search?q=NVDA").json()["results"]
    assert rows and rows[0]["code"] == "NVDA"

    # 코스닥 종목: .KS 하드코딩이 아니라 프로브 결과(.KQ)를 따라야 한다
    resolved = client.get("/api/resolve?code=247540").json()
    assert resolved == {"ticker": "247540.KQ", "resolved": True}

    passthrough = client.get("/api/resolve?code=NVDA").json()
    assert passthrough["ticker"] == "NVDA" and passthrough["resolved"] is False



def test_summarize_content_strips_markdown_and_extracts_bullets():
    result = summarize_content(
        "## FINAL TRANSACTION PROPOSAL\n"
        "**Rating**: Hold\n\n"
        "- 50일선 회복 전까지 관망\n"
        "- 공시와 매크로 변동성 확인 필요"
    )

    assert "**" not in result["summary"]
    assert result["headline"]
    assert result["bullets"][0] == "50일선 회복 전까지 관망"


def test_summarize_content_skips_report_titles_for_dashboard_copy():
    result = summarize_content(
        "FINAL TRANSACTION PROPOSAL: **BUY**\n\n"
        "### 1. 개요 및 요약\n"
        "## 삼성전자(Samsung Electronics Co., Ltd. / 005930.KS) 기업 기본적 분석"
        "(Fundamental Analysis) 종합 보고서\n\n"
        "### 2. 시장 분석을 위한 8개 핵심 기술적 지표 선정 및 선정 이유\n"
        "Reasoning: 2분기 실적은 견조하지만 밸류에이션 부담이 남아 있습니다.\n"
        "- 50일선 회복 전까지 관망이 필요합니다."
    )

    assert "종합 보고서" not in result["headline"]
    assert "FINAL TRANSACTION" not in result["headline"]
    assert "개요 및 요약" not in result["bullets"]
    assert not any("시장 분석을 위한" in bullet for bullet in result["bullets"])
    assert result["headline"] == "2분기 실적은 견조하지만 밸류에이션 부담이 남아 있습니다."


def test_sse_stream_surfaces_graph_error():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from tradingagents.dashboard.server import create_app

    class BoomGraph:
        def propagate(self, *a, **k):
            raise ValueError("vendor exploded")

    app = create_app(graph_factory=BoomGraph)
    client = TestClient(app)
    with client.stream("GET", "/api/stream?ticker=NVDA") as resp:
        payloads = [
            json.loads(line[len("data: "):])
            for line in resp.iter_lines()
            if line.startswith("data: ")
        ]
    errors = [p for p in payloads if p["type"] == "error"]
    assert errors and "vendor exploded" in errors[0]["message"]


def test_search_ranks_large_caps_above_alphabetical_order():
    from tradingagents.dashboard.server import search_names

    crowd = {
        "005930": "삼성전자", "009150": "삼성전기", "028260": "삼성물산",
        "032830": "삼성생명", "018260": "삼성에스디에스", "006400": "삼성SDI",
        "000810": "삼성화재", "207940": "삼성바이오로직스", "001360": "삼성제약",
        "010140": "삼성중공업", "016360": "삼성증권", "029780": "삼성카드",
        "068290": "삼성출판사", "006660": "삼성공조", "145990": "삼양사",
    }
    rows = search_names(crowd, "삼성", limit=12)
    codes = [r["code"] for r in rows]
    # 시총 상위(전자)가 가나다 컷에 밀려 사라지면 안 된다
    assert "005930" in codes[:3]
