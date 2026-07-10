import json

import pytest

from tradingagents.content_profiles import (
    final_state_from_profile,
    normalize_etf_profile,
    normalize_stock_profile,
    normalize_theme_profile,
)
from tradingagents.content_preview import (
    find_content_snapshot_files,
    load_preview_items,
    render_content_preview,
)
from tradingagents.content_snapshot import build_content_snapshot


@pytest.mark.unit
def test_render_content_preview_uses_market_snapshot_charts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    market_dir = tmp_path / ".pilot" / "toss_market"
    market_dir.mkdir(parents=True)
    market_file = market_dir / "sample.json"
    market_file.write_text(
        json.dumps({
            "artifact": "toss_market_snapshot",
            "source": "toss_securities_openapi",
            "symbols": ["005930"],
            "stocks": [{"symbol": "005930", "name": "삼성전자", "currency": "KRW"}],
            "prices": [{"symbol": "005930", "lastPrice": "288500", "currency": "KRW"}],
            "candles": {
                "005930": [
                    {"timestamp": "2026-07-08", "closePrice": "267000", "volume": "10"},
                    {"timestamp": "2026-07-09", "closePrice": "288500", "volume": "20"},
                ]
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    content_dir = tmp_path / ".pilot" / "content_with_market" / "005930.KS_report"
    content_dir.mkdir(parents=True)
    content_file = content_dir / "content_snapshot.json"
    content_file.write_text(
        json.dumps({
            "artifact": "content_snapshot",
            "ticker": "005930.KS",
            "content_type": "stock",
            "signal": {"rating": "Buy", "levels": {"entry": 280000, "stop": 260000, "target": 310000}},
            "cards": [{"id": "what_is_it", "title": "무엇인가", "status": "ready", "body": "반도체 기업입니다."}],
            "visuals": [{"id": "price_trend", "title": "가격 추이", "status": "ready"}],
            "market_data": {
                "source": "toss_securities_openapi",
                "snapshot_file": str(market_file.relative_to(tmp_path)),
                "metrics": {"return_1d_pct": 8.05, "return_5d_pct": -1.2, "volume_vs_20d_avg": 2.4, "high_60d": 300000},
            },
            "publish_gate": {"status": "ready"},
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    output = render_content_preview(tmp_path / ".pilot" / "content_with_market", tmp_path / "preview.html")

    html = output.read_text(encoding="utf-8")
    assert "005930.KS" in html
    assert "삼성전자" in html
    assert "가격 추이" in html
    assert "거래량 변화" in html
    assert "+8.05%" in html
    assert "2.40x" in html
    assert "60일 고가" in html
    assert "<svg" in html
    assert "외부 LLM 사용 <strong>없음</strong>" in html


@pytest.mark.unit
def test_load_preview_items_skips_non_content_snapshots(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "content_snapshot.json").write_text('{"artifact":"other"}', encoding="utf-8")

    assert find_content_snapshot_files(input_dir) == [input_dir / "content_snapshot.json"]
    assert load_preview_items(input_dir) == []


@pytest.mark.unit
def test_render_content_preview_shows_etf_and_theme_composition(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    input_dir = tmp_path / "profiles"
    stock_dir = input_dir / "AAPL"
    etf_dir = input_dir / "DEMOETF"
    theme_dir = input_dir / "KR_AI_SEMI"
    stock_dir.mkdir(parents=True)
    etf_dir.mkdir(parents=True)
    theme_dir.mkdir(parents=True)

    stock_profile = normalize_stock_profile({
        "profile_type": "stock",
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "exchange": "NASDAQ",
        "country": "United States",
        "currency": "USD",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "business_lines": [{"name": "Products"}, {"name": "Services"}],
        "regions": [{"name": "Americas"}, {"name": "Greater China"}],
        "products": [{"name": "iPhone"}, {"name": "Services"}],
        "peers": [{"ticker": "MSFT", "name": "Microsoft"}],
        "catalysts": [{"name": "신제품 사이클"}],
        "risks": [{"name": "중국 수요 둔화"}],
    })
    etf_profile = normalize_etf_profile({
        "profile_type": "etf",
        "ticker": "DEMOETF",
        "name": "글로벌 AI ETF 데모",
        "issuer": "Demo Asset",
        "benchmark": "Demo AI Index",
        "holdings": [
            {"ticker": "DEMO-GPU", "name": "GPU 설계 데모", "weight_pct": 22.5, "country": "United States"},
            {"ticker": "DEMO-MEM", "name": "메모리 데모", "weight_pct": 14.0, "country": "Korea"},
        ],
        "sectors": [{"name": "Semiconductors", "weight_pct": 62.0}],
        "countries": [{"name": "United States", "weight_pct": 74.0}, {"name": "Korea", "weight_pct": 18.0}],
    })
    theme_profile = normalize_theme_profile({
        "profile_type": "theme",
        "ticker": "KR-AI-SEMI",
        "name": "AI 반도체 테마",
        "description": "AI 인프라 투자와 함께 보는 반도체 밸류체인입니다.",
        "value_chain": [
            {
                "stage": "메모리",
                "description": "HBM과 고성능 DRAM",
                "domestic_names": [{"ticker": "DEMO-HBM", "name": "국내 HBM 데모"}],
                "global_names": [{"ticker": "DEMO-MEM", "name": "글로벌 메모리 데모"}],
            }
        ],
        "domestic_names": [{"ticker": "DEMO-HBM", "name": "국내 HBM 데모"}],
        "global_names": [{"ticker": "DEMO-GPU", "name": "GPU 설계 데모"}],
        "catalysts": [{"name": "AI 서버 투자 확대"}],
        "risks": [{"name": "수출 규제"}],
    })

    for directory, profile in ((stock_dir, stock_profile), (etf_dir, etf_profile), (theme_dir, theme_profile)):
        state, ticker, generated_at = final_state_from_profile(profile)
        content = build_content_snapshot(state, ticker, generated_at)
        (directory / "content_snapshot.json").write_text(
            json.dumps(content, ensure_ascii=False),
            encoding="utf-8",
        )

    output = render_content_preview(input_dir, tmp_path / "preview.html")
    html = output.read_text(encoding="utf-8")

    assert "Apple Inc. 구성" in html
    assert "사업 구성" in html
    assert "지역 노출" in html
    assert "핵심 제품/서비스" in html
    assert "상승 요인" in html
    assert "신제품 사이클" in html
    assert "주의 요인" in html
    assert "중국 수요 둔화" in html
    assert "상위 보유 종목" in html
    assert "섹터 비중" in html
    assert "국가 비중" in html
    assert "테마 밸류체인" in html
    assert "해외 대표 종목" in html
    assert "GPU 설계 데모" in html
    assert "가격 데이터 부족" not in html
