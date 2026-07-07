"""OpenDART vendor tests.

All network access is mocked so these run without a real OpenDART key.
"""

from __future__ import annotations

import copy
import json
import zipfile
from io import BytesIO
from unittest import mock

import pytest

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import dart, interface
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


def _corp_zip() -> bytes:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<result>
  <list>
    <corp_code>00126380</corp_code>
    <corp_name>삼성전자</corp_name>
    <stock_code>005930</stock_code>
  </list>
</result>
""".encode()
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("CORPCODE.xml", xml)
    return buffer.getvalue()


def _reset_config():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


@pytest.fixture(autouse=True)
def reset_config():
    _reset_config()
    yield
    _reset_config()


def test_missing_dart_key_raises_not_configured(monkeypatch):
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    monkeypatch.delenv("DART_API_KEY", raising=False)
    with pytest.raises(VendorNotConfiguredError):
        dart.get_api_key()


def test_get_news_dart_formats_disclosures(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENDART_API_KEY", "dart-test-key")
    config_module.set_config({"data_cache_dir": str(tmp_path), "news_article_limit": 5})
    disclosure_payload = {
        "status": "000",
        "message": "정상",
        "list": [
            {
                "corp_name": "삼성전자",
                "report_nm": "분기보고서",
                "rcept_no": "20260707000123",
                "rcept_dt": "20260707",
            }
        ],
    }

    with mock.patch.object(
        dart,
        "urlopen",
        side_effect=[
            _Response(_corp_zip()),
            _Response(json.dumps(disclosure_payload).encode()),
        ],
    ):
        out = dart.get_news_dart("005930.KS", "2026-07-01", "2026-07-07")

    assert "005930.KS OpenDART Disclosures" in out
    assert "분기보고서" in out
    assert "삼성전자" in out
    assert "20260707000123" in out


def test_get_news_dart_no_disclosures_raises_no_data(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENDART_API_KEY", "dart-test-key")
    config_module.set_config({"data_cache_dir": str(tmp_path)})

    with mock.patch.object(
        dart,
        "urlopen",
        side_effect=[
            _Response(_corp_zip()),
            _Response(json.dumps({"status": "013", "message": "조회된 데이타가 없습니다."}).encode()),
        ],
    ):
        with pytest.raises(NoMarketDataError):
            dart.get_news_dart("005930.KS", "2026-07-01", "2026-07-07")


def test_default_news_chain_includes_dart_then_yfinance():
    assert default_config.DEFAULT_CONFIG["data_vendors"]["news_data"] == "krnews,dart,yfinance"
    assert "krnews" in interface.VENDOR_METHODS["get_news"]
    assert "dart" in interface.VENDOR_METHODS["get_news"]


def test_korean_news_route_combines_naver_and_dart(monkeypatch):
    config_module.set_config({"data_vendors": {"news_data": "krnews,dart,yfinance"}})
    monkeypatch.setitem(
        interface.VENDOR_METHODS["get_news"],
        "krnews",
        lambda ticker, start_date, end_date: "NAVER NEWS",
    )
    monkeypatch.setitem(
        interface.VENDOR_METHODS["get_news"],
        "dart",
        lambda ticker, start_date, end_date: "DART DISCLOSURES",
    )
    monkeypatch.setitem(
        interface.VENDOR_METHODS["get_news"],
        "yfinance",
        lambda ticker, start_date, end_date: "YFINANCE FALLBACK",
    )

    out = interface.route_to_vendor("get_news", "005930.KS", "2026-07-01", "2026-07-07")

    assert "NAVER NEWS" in out
    assert "DART DISCLOSURES" in out
    assert "YFINANCE FALLBACK" not in out
