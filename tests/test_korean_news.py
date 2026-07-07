"""Naver Korean news vendor tests.

All API access is mocked, so these run without live Naver credentials.
"""

from __future__ import annotations

import copy
import json
from unittest import mock

import pytest

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import korean_news
from tradingagents.dataflows.errors import NoMarketDataError, VendorNotConfiguredError


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def _reset_config():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


@pytest.fixture(autouse=True)
def reset_config():
    _reset_config()
    yield
    _reset_config()


def test_missing_naver_credentials_raise_not_configured(monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    with pytest.raises(VendorNotConfiguredError):
        korean_news.get_api_credentials()


def test_get_news_krnews_formats_articles(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "naver-client")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "naver-secret")
    config_module.set_config({"news_article_limit": 5})
    payload = {
        "items": [
            {
                "title": "<b>삼성전자</b> 실적 개선",
                "description": "반도체 업황 회복 기대",
                "originallink": "https://example.com/news",
                "pubDate": "Tue, 07 Jul 2026 09:00:00 +0900",
            },
            {
                "title": "기간 밖 기사",
                "description": "제외되어야 함",
                "originallink": "https://example.com/old",
                "pubDate": "Mon, 01 Jun 2026 09:00:00 +0900",
            },
        ]
    }

    with mock.patch.object(
        korean_news,
        "urlopen",
        return_value=_Response(json.dumps(payload).encode("utf-8")),
    ):
        out = korean_news.get_news_krnews("005930.KS", "2026-07-01", "2026-07-07")

    assert "005930.KS Korean News via Naver" in out
    assert "삼성전자 실적 개선" in out
    assert "반도체 업황 회복 기대" in out
    assert "기간 밖 기사" not in out


def test_get_news_krnews_no_articles_raises_no_data(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "naver-client")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "naver-secret")
    payload = {"items": []}

    with mock.patch.object(
        korean_news,
        "urlopen",
        return_value=_Response(json.dumps(payload).encode("utf-8")),
    ):
        with pytest.raises(NoMarketDataError):
            korean_news.get_news_krnews("005930.KS", "2026-07-01", "2026-07-07")
