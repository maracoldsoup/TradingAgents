"""Korean market sentiment proxies from official Naver DataLab Search."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .config import get_config

logger = logging.getLogger(__name__)

_DATALAB_URL = "https://openapi.naver.com/v1/datalab/search"


def _credentials() -> tuple[str, str] | None:
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    return client_id, client_secret


def _ticker_key(ticker: str) -> str:
    return ticker.split(".", 1)[0].upper()


def is_korean_equity(ticker: str) -> bool:
    normalized = ticker.upper()
    return normalized.endswith((".KS", ".KQ")) or normalized.split(".", 1)[0].isdigit()


def _company_query(ticker: str) -> tuple[str, list[str]]:
    names = get_config().get("korean_ticker_names", {})
    normalized = ticker.upper()
    key = _ticker_key(normalized)
    company = names.get(normalized) or names.get(key) or ticker
    keywords = [company]
    if key != company:
        keywords.append(key)
    return company, keywords


def _window(end_date: str, lookback_days: int) -> tuple[str, str]:
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    start = end - timedelta(days=lookback_days)
    return start.isoformat(), end.isoformat()


def fetch_naver_datalab_sentiment(
    ticker: str,
    end_date: str,
    lookback_days: int = 30,
    timeout: float = 10.0,
) -> str:
    """Return a formatted Naver search-interest block for Korean equities.

    DataLab returns relative search ratios, not bullish/bearish opinions. Treat
    this as attention/interest sentiment: a rising ratio means the stock is more
    discussed, not necessarily liked. The caller receives a placeholder string
    on any missing-key, network, or API error so the sentiment pipeline keeps
    running.
    """
    if not is_korean_equity(ticker):
        return f"<Naver DataLab skipped: {ticker} is not a Korean equity ticker>"

    creds = _credentials()
    if creds is None:
        return "<Naver DataLab unavailable: NAVER_CLIENT_ID/NAVER_CLIENT_SECRET not set>"

    company, keywords = _company_query(ticker)
    start_date, end = _window(end_date, lookback_days)
    payload = {
        "startDate": start_date,
        "endDate": end,
        "timeUnit": "date",
        "keywordGroups": [{"groupName": company, "keywords": keywords}],
    }
    request = Request(
        _DATALAB_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Naver-Client-Id": creds[0],
            "X-Naver-Client-Secret": creds[1],
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        logger.warning("Naver DataLab fetch failed for %s: HTTP %s", ticker, exc.code)
        return f"<Naver DataLab unavailable: HTTP {exc.code}>"
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Naver DataLab fetch failed for %s: %s", ticker, exc)
        return f"<Naver DataLab unavailable: {type(exc).__name__}>"

    series = ((data.get("results") or [{}])[0].get("data") or []) if isinstance(data, dict) else []
    points = [
        (row.get("period"), float(row.get("ratio")))
        for row in series
        if row.get("period") is not None and row.get("ratio") is not None
    ]
    if not points:
        return f"<Naver DataLab unavailable: no search trend data for {company}>"

    latest_period, latest_ratio = points[-1]
    first_period, first_ratio = points[0]
    avg_ratio = sum(ratio for _, ratio in points) / len(points)
    change = latest_ratio - first_ratio
    direction = "rising" if change > 5 else "falling" if change < -5 else "stable"
    recent_rows = "\n".join(f"| {period} | {ratio:.2f} |" for period, ratio in points[-7:])

    return "\n".join([
        f"## Naver DataLab Search Interest: {company} ({ticker})",
        f"Window: {start_date} to {end}",
        f"Keywords: {', '.join(keywords)}",
        (
            f"Latest ratio: {latest_ratio:.2f} ({latest_period}); "
            f"window average: {avg_ratio:.2f}; change from {first_period}: {change:+.2f} "
            f"({direction} attention)."
        ),
        "Interpretation: this is search-attention momentum, not bullish/bearish opinion.",
        "",
        "| Date | Search ratio |",
        "|---|---:|",
        recent_rows,
    ])
