"""OpenDART disclosure feed for Korean listed companies."""

from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen
from xml.etree import ElementTree

from .config import get_config
from .errors import NoMarketDataError, VendorNotConfiguredError, VendorRateLimitError

_DART_BASE = "https://opendart.fss.or.kr/api"
_CACHE_FILE = "dart_corp_codes.json"


def get_api_key() -> str:
    api_key = os.getenv("OPENDART_API_KEY") or os.getenv("DART_API_KEY")
    if not api_key:
        raise VendorNotConfiguredError(
            "OPENDART_API_KEY or DART_API_KEY environment variable is not set."
        )
    return api_key


def _ticker_key(ticker: str) -> str:
    return ticker.split(".", 1)[0].upper()


def _cache_path() -> Path:
    cache_dir = Path(get_config().get("data_cache_dir", "~/.tradingagents/cache")).expanduser()
    return cache_dir / "dart" / _CACHE_FILE


def _fetch_corp_code_map(api_key: str) -> dict[str, dict[str, str]]:
    url = f"{_DART_BASE}/corpCode.xml?{urlencode({'crtfc_key': api_key})}"
    try:
        with urlopen(url, timeout=20) as response:
            payload = response.read()
    except HTTPError as exc:
        if exc.code == 429:
            raise VendorRateLimitError("OpenDART rate-limited the corp-code request.") from exc
        raise

    mapping: dict[str, dict[str, str]] = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        xml_name = archive.namelist()[0]
        root = ElementTree.fromstring(archive.read(xml_name))

    for item in root.findall("list"):
        stock_code = (item.findtext("stock_code") or "").strip()
        corp_code = (item.findtext("corp_code") or "").strip()
        corp_name = (item.findtext("corp_name") or "").strip()
        if stock_code and corp_code:
            mapping[stock_code] = {"corp_code": corp_code, "corp_name": corp_name}
    return mapping


def _corp_code_map(api_key: str) -> dict[str, dict[str, str]]:
    path = _cache_path()
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    mapping = _fetch_corp_code_map(api_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(mapping, fh, ensure_ascii=False, sort_keys=True)
    return mapping


def _dart_date(value: str) -> str:
    return datetime.strptime(value, "%Y-%m-%d").strftime("%Y%m%d")


def _request_disclosures(
    api_key: str,
    corp_code: str,
    start_date: str,
    end_date: str,
    limit: int,
) -> dict:
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": _dart_date(start_date),
        "end_de": _dart_date(end_date),
        "page_count": str(min(max(limit, 10), 100)),
    }
    url = f"{_DART_BASE}/list.json?{urlencode(params)}"
    try:
        with urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 429:
            raise VendorRateLimitError("OpenDART rate-limited the disclosure request.") from exc
        raise


def get_news_dart(ticker: str, start_date: str, end_date: str) -> str:
    """Return OpenDART disclosures as a factual news source."""
    api_key = get_api_key()
    stock_code = _ticker_key(ticker)
    company = _corp_code_map(api_key).get(stock_code)
    if not company:
        raise NoMarketDataError(ticker, stock_code, "no OpenDART corp_code mapping for ticker")

    limit = int(get_config().get("news_article_limit", 20))
    payload = _request_disclosures(api_key, company["corp_code"], start_date, end_date, limit)
    status = str(payload.get("status", ""))
    message = payload.get("message", "")

    if status == "013":
        raise NoMarketDataError(ticker, stock_code, "OpenDART returned no disclosures")
    if status == "020":
        raise VendorRateLimitError(f"OpenDART rate limit: {message}")
    if status != "000":
        raise ValueError(f"OpenDART error {status}: {message}")

    disclosures = payload.get("list") or []
    if not disclosures:
        raise NoMarketDataError(ticker, stock_code, "OpenDART returned an empty disclosure list")

    lines: list[str] = []
    for item in disclosures[:limit]:
        report_name = item.get("report_nm", "Untitled disclosure")
        corp_name = item.get("corp_name") or company.get("corp_name") or stock_code
        receipt_no = item.get("rcept_no", "")
        receipt_date = item.get("rcept_dt", "")
        link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_no}" if receipt_no else ""
        lines.append(f"### {report_name} (source: OpenDART)")
        lines.append(f"Company: {corp_name}")
        if receipt_date:
            lines.append(f"Filed: {receipt_date}")
        if link:
            lines.append(f"Link: {link}")
        lines.append("")

    return f"## {ticker} OpenDART Disclosures, from {start_date} to {end_date}:\n\n" + "\n".join(lines)
