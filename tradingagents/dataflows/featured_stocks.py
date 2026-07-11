"""특징주 (notable-mover) articles via Naver News Search.

Korean financial media publishes a distinct genre of article literally
titled "[특징주] {company}, {reason} {상승/하락}" — a real journalist's
explanation of why a stock moved, in native Korean. This is a better
"why" source than Toss's bare ranking numbers (breaking_feed.py), and
unlike collect-news's international wire content it needs no
translation: the text is already Korean.

Mirrors breaking_feed.py's discipline: no LLM call, no invented
numbers or reasons. Ticker resolution is a deterministic substring
match against the KRX name map (tradingagents/dataflows/data/
krx_ticker_names.json) plus a small manual map for globally-known
non-KRX names that recur constantly in Korean financial press (메타,
테슬라, 엔비디아, ...). If no name matches, the article still carries
a real Korean headline/summary — ticker is None rather than guessed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import get_config
from .errors import VendorNotConfiguredError, VendorRateLimitError
from .korean_news import get_api_credentials  # NAVER_CLIENT_ID / _SECRET

_NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"
_TAG_RE = re.compile(r"<[^>]+>")
_PREFIX_RE = re.compile(r"^\[[^\]]*특징주[^\]]*\]\s*")

# Well-known non-KRX names that Korean financial press writes in
# Korean but that don't exist in the KRX name map (they're foreign
# listings). Extend as new recurring names show up in practice.
_GLOBAL_NAME_TICKERS: dict[str, str] = {
    "엔비디아": "NVDA", "테슬라": "TSLA", "애플": "AAPL", "아마존": "AMZN",
    "마이크로소프트": "MSFT", "메타": "META", "알파벳": "GOOGL", "구글": "GOOGL",
    "인텔": "INTC", "마이크론": "MU", "퀄컴": "QCOM", "넷플릭스": "NFLX",
    "팔란티어": "PLTR", "슈퍼마이크로": "SMCI", "스타벅스": "SBUX",
    "코인베이스": "COIN", "모더나": "MRNA", "화이자": "PFE", "보잉": "BA",
    "AMD": "AMD", "브로드컴": "AVGO", "오라클": "ORCL", "세일즈포스": "CRM",
    "써클": "CRCL", "리비안": "RIVN", "로빈후드": "HOOD",
    "팔로알토": "PANW", "스노우플레이크": "SNOW", "쇼피파이": "SHOP",
    # 스페이스X는 비상장이라 실제 거래 가능한 티커가 없음 — 매핑하지 않음
    # (매핑하면 /ticker/SPACEX 같은 존재하지 않는 페이지로 연결됨).
}

_UP_KEYWORDS = ("급등", "폭등", "상한가", "강세", "상승", "치솟")
_DOWN_KEYWORDS = ("급락", "폭락", "하한가", "약세", "하락", "곤두박질")

_MIN_NAME_LEN = 2


def _strip_markup(value: str) -> str:
    return _TAG_RE.sub("", unescape(value or "")).strip()


def _clean_headline(title: str) -> str:
    return _PREFIX_RE.sub("", _strip_markup(title)).strip()


def _parse_pub_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).replace(tzinfo=None)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _load_name_ticker_index() -> list[tuple[str, str]]:
    """(name, ticker) pairs, longest name first so multi-word names win
    over a shorter substring another company's name happens to contain."""
    krx_path = Path(__file__).parent / "data" / "krx_ticker_names.json"
    pairs: list[tuple[str, str]] = []
    if krx_path.exists():
        krx = json.loads(krx_path.read_text(encoding="utf-8"))
        for ticker, name in krx.items():
            if len(ticker) == 6 and len(name) >= _MIN_NAME_LEN:  # skip the ".KS" dup keys
                pairs.append((name, ticker))
    for name, ticker in _GLOBAL_NAME_TICKERS.items():
        pairs.append((name, ticker))
    pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
    return pairs


_NAME_INDEX: list[tuple[str, str]] | None = None


def _resolve_ticker(text: str) -> tuple[str | None, str | None]:
    """Best-effort (ticker, matched_name) from the longest name found in text."""
    global _NAME_INDEX
    if _NAME_INDEX is None:
        _NAME_INDEX = _load_name_ticker_index()
    for name, ticker in _NAME_INDEX:
        if name in text:
            return ticker, name
    return None, None


def _detect_direction(text: str) -> str | None:
    up_idx = min((text.index(kw) for kw in _UP_KEYWORDS if kw in text), default=None)
    down_idx = min((text.index(kw) for kw in _DOWN_KEYWORDS if kw in text), default=None)
    if up_idx is None and down_idx is None:
        return None
    if down_idx is None or (up_idx is not None and up_idx < down_idx):
        return "up"
    return "down"


def _request_page(query: str, display: int, start: int) -> dict:
    client_id, client_secret = get_api_credentials()
    params = urlencode({"query": query, "display": display, "start": start, "sort": "date"})
    request = Request(
        f"{_NAVER_NEWS_URL}?{params}",
        headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 429:
            raise VendorRateLimitError("Naver News API rate-limited the request.") from exc
        raise


def collect_featured_stocks_snapshot(
    *,
    pages: int = 2,
    generated_at: datetime | None = None,
) -> dict:
    """Fetch recent 특징주 articles and resolve tickers where possible.

    `pages` * 100 is the number of most-recent articles considered
    (Naver caps `display` at 100 per call); default 2 pages covers a
    same-day window at the observed ~10-20min publish cadence.
    """
    generated_at = generated_at or datetime.now()
    try:
        get_api_credentials()
    except VendorNotConfiguredError:
        return {
            "schema_version": 1,
            "artifact": "featured_stocks_snapshot",
            "generated_at": generated_at.isoformat(timespec="seconds"),
            "count": 0,
            "items": [],
        }

    seen_links: set[str] = set()
    items: list[dict] = []
    for page in range(pages):
        payload = _request_page("특징주", 100, page * 100 + 1)
        for raw in payload.get("items") or []:
            link = raw.get("originallink") or raw.get("link") or ""
            if not link or link in seen_links:
                continue
            seen_links.add(link)

            headline = _clean_headline(raw.get("title", ""))
            summary = _strip_markup(raw.get("description", ""))
            if not headline:
                continue
            pub_date = _parse_pub_date(raw.get("pubDate", ""))

            search_text = f"{headline} {summary}"
            ticker, matched_name = _resolve_ticker(search_text)
            direction = _detect_direction(search_text)

            items.append({
                "headline_ko": headline,
                "summary_ko": summary or None,
                "source_url": link,
                "published_at": pub_date.isoformat(timespec="seconds") if pub_date else None,
                "ticker": ticker,
                "matched_name": matched_name,
                "direction": direction,
            })

    items.sort(key=lambda item: item["published_at"] or "", reverse=True)
    return {
        "schema_version": 1,
        "artifact": "featured_stocks_snapshot",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "count": len(items),
        "items": items,
    }
