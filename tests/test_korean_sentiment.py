"""Naver DataLab Korean sentiment proxy tests."""

from __future__ import annotations

import copy
import json
from unittest import mock

import pytest

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import korean_sentiment


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


def test_missing_naver_credentials_returns_placeholder(monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    out = korean_sentiment.fetch_naver_datalab_sentiment("005930.KS", "2026-07-07")
    assert out.startswith("<Naver DataLab unavailable:")


def test_non_korean_ticker_is_skipped(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "client")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "secret")
    out = korean_sentiment.fetch_naver_datalab_sentiment("NVDA", "2026-07-07")
    assert "skipped" in out


def test_datalab_response_formats_attention_proxy(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "client")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "secret")
    payload = {
        "results": [
            {
                "title": "삼성전자",
                "keywords": ["삼성전자", "005930"],
                "data": [
                    {"period": "2026-07-01", "ratio": 20.0},
                    {"period": "2026-07-02", "ratio": 55.5},
                    {"period": "2026-07-07", "ratio": 80.0},
                ],
            }
        ]
    }

    with mock.patch.object(
        korean_sentiment,
        "urlopen",
        return_value=_Response(json.dumps(payload).encode("utf-8")),
    ):
        out = korean_sentiment.fetch_naver_datalab_sentiment(
            "005930.KS", "2026-07-07", lookback_days=7
        )

    assert "Naver DataLab Search Interest: 삼성전자" in out
    assert "rising attention" in out
    assert "| 2026-07-07 | 80.00 |" in out
