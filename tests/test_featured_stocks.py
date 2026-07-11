"""특징주 (notable-mover news) collector tests.

All API access is mocked, so these run without live Naver credentials.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from tradingagents.dataflows import featured_stocks
from tradingagents.dataflows.errors import VendorNotConfiguredError


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


@pytest.fixture(autouse=True)
def reset_name_index():
    featured_stocks._NAME_INDEX = None
    yield
    featured_stocks._NAME_INDEX = None


def _mock_page(items: list[dict]):
    return _Response(json.dumps({"items": items}).encode("utf-8"))


@pytest.mark.unit
def test_missing_credentials_returns_empty_snapshot_not_error(monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)

    snapshot = featured_stocks.collect_featured_stocks_snapshot(pages=1)

    assert snapshot["artifact"] == "featured_stocks_snapshot"
    assert snapshot["count"] == 0
    assert snapshot["items"] == []


@pytest.mark.unit
def test_resolves_krx_ticker_and_direction(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "secret")

    payload = [
        {
            "title": "[<b>특징주</b>] 삼성전자, 실적 서프라이즈에 급등",
            "description": "삼성전자가 2분기 실적 발표 후 강세를 보이고 있다.",
            "originallink": "https://example.com/news/1",
            "link": "https://example.com/news/1",
            "pubDate": "Sat, 11 Jul 2026 10:24:00 +0900",
        },
    ]

    with mock.patch.object(featured_stocks, "urlopen", return_value=_mock_page(payload)):
        snapshot = featured_stocks.collect_featured_stocks_snapshot(pages=1)

    assert snapshot["count"] == 1
    item = snapshot["items"][0]
    assert item["headline_ko"] == "삼성전자, 실적 서프라이즈에 급등"
    assert item["ticker"] == "005930"
    assert item["direction"] == "up"
    assert item["source_url"] == "https://example.com/news/1"
    assert item["published_at"] == "2026-07-11T10:24:00"


@pytest.mark.unit
def test_resolves_global_name_from_manual_map(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "secret")

    payload = [
        {
            "title": "[美증시 특징주] 메타 오랜만엔 6% 급등...AI 지출구조 개선",
            "description": "메타가 AI 투자 효율 개선 소식에 강세다.",
            "originallink": "https://example.com/news/2",
            "pubDate": "Sat, 11 Jul 2026 06:20:00 +0900",
        },
    ]

    with mock.patch.object(featured_stocks, "urlopen", return_value=_mock_page(payload)):
        snapshot = featured_stocks.collect_featured_stocks_snapshot(pages=1)

    item = snapshot["items"][0]
    assert item["ticker"] == "META"
    assert item["direction"] == "up"


@pytest.mark.unit
def test_unresolvable_name_keeps_article_with_null_ticker(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "secret")

    payload = [
        {
            "title": "[유럽증시 특징주] 어느 무명 소기업 12% 급등",
            "description": "특정 회사명이 매핑되지 않는 경우.",
            "originallink": "https://example.com/news/3",
            "pubDate": "Sat, 11 Jul 2026 06:44:00 +0900",
        },
    ]

    with mock.patch.object(featured_stocks, "urlopen", return_value=_mock_page(payload)):
        snapshot = featured_stocks.collect_featured_stocks_snapshot(pages=1)

    item = snapshot["items"][0]
    assert item["ticker"] is None
    assert item["headline_ko"] == "어느 무명 소기업 12% 급등"


@pytest.mark.unit
def test_down_direction_detected():
    text = "잘나가던 모더나 10% 폭락...증권사 '비중축소' 의견에"
    assert featured_stocks._detect_direction(text) == "down"


@pytest.mark.unit
def test_dedupes_by_link_across_pages(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "secret")

    item = {
        "title": "[특징주] 삼성전자, 급등",
        "description": "설명",
        "originallink": "https://example.com/dup",
        "pubDate": "Sat, 11 Jul 2026 10:24:00 +0900",
    }

    with mock.patch.object(featured_stocks, "urlopen", return_value=_mock_page([item])):
        snapshot = featured_stocks.collect_featured_stocks_snapshot(pages=2)

    assert snapshot["count"] == 1


@pytest.mark.unit
def test_spacex_is_not_mapped_to_a_ticker():
    # Private company mentioned often in Korean press — must not resolve to
    # a fake ticker that would 404 a /ticker/:id page.
    ticker, _ = featured_stocks._resolve_ticker("스페이스X 상장 한 달, 테슬라 주가는 버티고 있다")
    assert ticker != "SPACEX"
