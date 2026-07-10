import json

import pytest

from tradingagents.content_profiles import final_state_from_profile
from tradingagents.content_snapshot import build_content_snapshot
from tradingagents.theme_profile_importer import import_theme_profile


@pytest.mark.unit
def test_import_theme_profile_from_local_csv_builds_value_chain(tmp_path):
    theme_map = tmp_path / "theme.csv"
    theme_map.write_text(
        "\n".join([
            "Stage,Description,Scope,Ticker,Name,Role,Market,Country,Catalysts,Risks,Metrics",
            "설계/IP,AI 가속기와 핵심 설계 자산,Global,DEMO-GPU,GPU 설계 데모,설계,NASDAQ,United States,AI 서버 투자 확대;온디바이스 AI 기능 확산,수출 규제,GPU 수요",
            "설계/IP,AI 가속기와 핵심 설계 자산,Domestic,DEMO-KR-IP,국내 IP 데모,IP,KOSDAQ,Korea,,인력 확보 경쟁,IP 라이선스 매출",
            "메모리,HBM과 고성능 DRAM,Domestic,DEMO-HBM,국내 HBM 데모,메모리,KOSPI,Korea,HBM 공급 계약,메모리 가격 하락,HBM ASP",
        ]),
        encoding="utf-8",
    )

    profile = import_theme_profile(
        theme_map_path=theme_map,
        ticker="KR-AI-SEMI-CSV",
        name="CSV AI 반도체 테마",
        description="CSV에서 가져온 AI 반도체 밸류체인입니다.",
        as_of="2026-07-09",
        source="unit_test_csv",
    )

    assert profile["profile_type"] == "theme"
    assert [stage["stage"] for stage in profile["value_chain"]] == ["설계/IP", "메모리"]
    assert profile["value_chain"][0]["global_names"][0]["ticker"] == "DEMO-GPU"
    assert profile["value_chain"][0]["domestic_names"][0]["ticker"] == "DEMO-KR-IP"
    assert profile["domestic_names"][0]["name"] == "국내 IP 데모"
    assert profile["global_names"][0]["name"] == "GPU 설계 데모"
    assert [row["name"] for row in profile["catalysts"]] == ["AI 서버 투자 확대", "온디바이스 AI 기능 확산", "HBM 공급 계약"]
    assert "수출 규제" in [row["name"] for row in profile["risks"]]

    state, ticker, generated_at = final_state_from_profile(profile)
    content = build_content_snapshot(state, ticker, generated_at)

    assert content["publish_gate"]["status"] == "ready"
    assert content["composition_data"]["value_chain"][0]["stage"] == "설계/IP"
    assert next(v for v in content["visuals"] if v["id"] == "theme_value_chain")["status"] == "ready"


@pytest.mark.unit
def test_import_theme_profile_supports_json_rows(tmp_path):
    theme_map = tmp_path / "theme.json"
    theme_map.write_text(
        json.dumps([
            {"stage": "플랫폼", "scope": "global", "ticker": "AAA", "name": "AAA Platform"},
            {"stage": "플랫폼", "scope": "domestic", "ticker": "BBB", "name": "BBB 플랫폼"},
        ]),
        encoding="utf-8",
    )

    profile = import_theme_profile(theme_map_path=theme_map, ticker="THEME")

    assert profile["value_chain"][0]["stage"] == "플랫폼"
    assert profile["value_chain"][0]["global_names"][0]["ticker"] == "AAA"
    assert profile["value_chain"][0]["domestic_names"][0]["ticker"] == "BBB"
