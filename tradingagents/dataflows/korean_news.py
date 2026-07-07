"""Korean ticker news via Naver News Search."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import get_config
from .errors import NoMarketDataError, VendorNotConfiguredError, VendorRateLimitError

_NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"
_HTML_TAG = re.compile(r"<[^>]+>")


def get_api_credentials() -> tuple[str, str]:
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise VendorNotConfiguredError(
            "NAVER_CLIENT_ID and NAVER_CLIENT_SECRET environment variables are not set."
        )
    return client_id, client_secret


def _ticker_key(ticker: str) -> str:
    return ticker.split(".", 1)[0].upper()


def _company_query(ticker: str) -> str:
    names = get_config().get("korean_ticker_names", {})
    normalized = ticker.upper()
    return names.get(normalized) or names.get(_ticker_key(normalized)) or ticker


def _strip_markup(value: str) -> str:
    return _HTML_TAG.sub("", unescape(value or "")).strip()


def _parse_pub_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).replace(tzinfo=None)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _request_news(query: str, display: int) -> dict:
    client_id, client_secret = get_api_credentials()
    params = urlencode({"query": query, "display": display, "sort": "date"})
    request = Request(
        f"{_NAVER_NEWS_URL}?{params}",
        headers={
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 429:
            raise VendorRateLimitError("Naver News API rate-limited the request.") from exc
        raise


def get_news_krnews(ticker: str, start_date: str, end_date: str) -> str:
    """Return Korean-language news for a ticker using Naver News Search."""
    config = get_config()
    limit = int(config.get("news_article_limit", 20))
    query = _company_query(ticker)
    payload = _request_news(query, min(max(limit * 3, 10), 100))
    items = payload.get("items") or []

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    lines: list[str] = []
    kept = 0

    for item in items:
        pub_date = _parse_pub_date(item.get("pubDate", ""))
        if pub_date is None or not (start_dt <= pub_date < end_dt + timedelta(days=1)):
            continue

        title = _strip_markup(item.get("title", ""))
        summary = _strip_markup(item.get("description", ""))
        link = item.get("originallink") or item.get("link") or ""
        if not title:
            continue

        lines.append(f"### {title} (source: Naver News)")
        lines.append(f"Published: {pub_date.strftime('%Y-%m-%d %H:%M')}")
        if summary:
            lines.append(summary)
        if link:
            lines.append(f"Link: {link}")
        lines.append("")
        kept += 1
        if kept >= limit:
            break

    if kept == 0:
        raise NoMarketDataError(
            ticker,
            ticker,
            f"no Korean news found for query {query!r} between {start_date} and {end_date}",
        )

    return f"## {ticker} Korean News via Naver, from {start_date} to {end_date}:\n\n" + "\n".join(lines)
