"""Build beginner-facing content cards from a completed analysis state.

This module is deliberately deterministic: it does not call an LLM, fetch data,
or invent missing numbers. It turns the existing report tree state into a
compact handoff for card-news, short-form video, and dashboard rendering.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

_BOILERPLATE = (
    "executive summary",
    "final transaction proposal",
    "analysis report",
    "comprehensive report",
    "the instrument to analyze",
    "report generated",
    "본 보고서는",
    "보고서 작성일",
    "종합 기업 분석",
    "투자 제안 보고서",
    "분석 보고서",
    "종합 보고서",
    "요약 테이블",
)


_LABEL_PREFIXES = (
    "rating",
    "recommendation",
    "action",
    "report date",
    "작성일",
    "보고서 작성일",
    "분석 기준일",
    "분석 대상",
    "대상 기업",
    "대상 종목",
    "산업 분류",
    "시장 분류",
    "상장 거래소",
    "거래소",
)


def _clean_markdown(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"```[\s\S]*?```", " ", value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"\*([^*]+)\*", r"\1", value)
    value = re.sub(r"^#{1,6}\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"\|", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _compact(text: str, limit: int = 300) -> str:
    value = _clean_markdown(text)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def _split_sentences(text: str) -> list[str]:
    value = _clean_markdown(text)
    if not value:
        return []
    marked = re.sub(r"(다\.|[.!?。])\s+", r"\1\n", value)
    return [sentence.strip() for sentence in marked.splitlines() if sentence.strip()]


def _is_noise_line(text: str) -> bool:
    value = _clean_markdown(text).strip()
    if not value:
        return True
    if not value.strip("-–—_=*•· "):
        return True
    lowered = value.lower().lstrip("*#- ")
    if any(word in lowered for word in _BOILERPLATE):
        return True
    return any(lowered.startswith(prefix) for prefix in _LABEL_PREFIXES)


def _extract_bullets(text: str, limit: int = 4) -> list[str]:
    bullets: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^(?:[-*•]\s+|\d+[.)]\s+)", "", line).strip()
        if _is_noise_line(line):
            continue
        bullets.append(_compact(line, 160))
        if len(bullets) >= limit:
            break
    if bullets:
        return bullets

    for sentence in _split_sentences(text):
        sentence = sentence.strip()
        if not _is_noise_line(sentence):
            bullets.append(_compact(sentence, 160))
        if len(bullets) >= limit:
            break
    return bullets


def _summary(text: str, limit: int = 320) -> dict[str, Any]:
    bullets = _extract_bullets(text)
    headline = bullets[0] if bullets else _compact(text, 120)
    body = ""
    for bullet in bullets:
        candidate = f"{body} {bullet}".strip()
        if body and len(candidate) > limit:
            break
        body = candidate
    if not body:
        body = _compact(text, limit)
    return {
        "headline": _compact(headline, 120),
        "body": _compact(body, limit),
        "bullets": bullets,
    }


def _market_adapter(ticker: str) -> str:
    normalized = ticker.upper()
    if normalized.startswith("KR-") or normalized.endswith(".KR"):
        return "KR"
    if normalized.endswith((".KS", ".KQ")) or normalized.split(".", 1)[0].isdigit():
        return "KR"
    if normalized.endswith("-USD"):
        return "CRYPTO"
    if normalized.endswith((".T", ".HK", ".L", ".TO", ".AX", ".NS", ".BO")):
        return "GLOBAL"
    return "US"


def _content_type(final_state: dict[str, Any], ticker: str) -> str:
    explicit = str(final_state.get("content_type") or "").strip().lower()
    if explicit in {"stock", "etf", "theme", "crypto"}:
        return explicit
    asset_type = str(final_state.get("asset_type") or "").strip().lower()
    if asset_type in {"stock", "etf", "theme", "crypto"}:
        return asset_type
    text = " ".join(
        str(final_state.get(key, ""))
        for key in ("instrument_context", "fundamentals_report", "news_report")
    ).lower()
    if " etf" in text or "exchange-traded fund" in text or "상장지수펀드" in text:
        return "etf"
    if "theme" in text or "테마" in text:
        return "theme"
    if ticker.upper().endswith("-USD"):
        return "crypto"
    return "stock"


def _identity_field(context: str, label: str) -> str:
    marker = f"{label}:"
    if marker not in context:
        return ""
    value = context.split(marker, 1)[1].split(";", 1)[0].strip()
    if label == "Exchange":
        value = value.split(".", 1)[0].strip()
    return value


def _weighted_names(rows: list[dict[str, Any]], limit: int = 5) -> str:
    labels: list[str] = []
    for row in rows[:limit]:
        name = row.get("name") or row.get("ticker") or row.get("symbol")
        if not name:
            continue
        weight = row.get("weight_pct")
        if weight not in (None, ""):
            labels.append(f"{name} {weight:g}%")
        else:
            labels.append(str(name))
    return ", ".join(labels)


def _plain_names(rows: list[dict[str, Any]], limit: int = 6) -> str:
    names = [
        str(row.get("name") or row.get("ticker") or row.get("symbol"))
        for row in rows[:limit]
        if row.get("name") or row.get("ticker") or row.get("symbol")
    ]
    return ", ".join(names)


def _instrument_summary(final_state: dict[str, Any], ticker: str, content_type: str) -> str:
    if content_type == "etf":
        profile = final_state.get("etf_profile") or {}
        name = profile.get("name") or ticker
        benchmark = profile.get("benchmark")
        issuer = profile.get("issuer")
        parts = [f"{ticker}는 {name}입니다."]
        if issuer:
            parts.append(f"운용사는 {issuer}입니다.")
        if benchmark:
            parts.append(f"기초지수는 {benchmark}입니다.")
        parts.append("상위 보유 종목, 섹터, 국가 비중으로 구성을 설명합니다.")
        return " ".join(parts)

    if content_type == "theme":
        profile = final_state.get("theme_profile") or {}
        name = profile.get("name") or ticker
        label = name if "테마" in str(name) else f"{name} 테마"
        description = profile.get("description")
        if description:
            return f"{label}는 {description}"
        return f"{label}는 밸류체인과 국내/해외 대표 종목으로 설명합니다."

    context = str(final_state.get("instrument_context") or "").strip()
    if not context:
        return f"{ticker} 분석 대상"

    company = _identity_field(context, "Company")
    business = _identity_field(context, "Business classification")
    exchange = _identity_field(context, "Exchange")
    parts = []
    if company:
        parts.append(f"{ticker}는 {company}입니다.")
    if business:
        parts.append(f"사업 분류는 {business}입니다.")
    if exchange:
        parts.append(f"{exchange} 거래소 기준으로 분석합니다.")
    if parts:
        return " ".join(parts)
    return context


def _profile_composition_text(final_state: dict[str, Any], content_type: str) -> str:
    if content_type == "stock":
        profile = final_state.get("stock_profile") or {}
        parts: list[str] = []
        business_lines = profile.get("business_lines") or []
        regions = profile.get("regions") or []
        products = profile.get("products") or []
        peers = profile.get("peers") or []
        if business_lines:
            parts.append("사업 구성: " + _weighted_names(business_lines, 8))
        if regions:
            parts.append("지역 노출: " + _weighted_names(regions, 8))
        if products:
            parts.append("핵심 제품/서비스: " + _plain_names(products, 8))
        if peers:
            parts.append("비교 대상: " + _plain_names(peers, 8))
        if profile.get("as_of"):
            parts.append(f"기준일: {profile['as_of']}")
        return "\n".join(parts)

    if content_type == "etf":
        profile = final_state.get("etf_profile") or {}
        parts: list[str] = []
        holdings = profile.get("holdings") or []
        sectors = profile.get("sectors") or []
        countries = profile.get("countries") or []
        if holdings:
            parts.append("상위 보유 종목: " + _weighted_names(holdings, 10))
        if sectors:
            parts.append("섹터 비중: " + _weighted_names(sectors, 8))
        if countries:
            parts.append("국가 비중: " + _weighted_names(countries, 8))
        if profile.get("expense_ratio_pct") is not None:
            parts.append(f"총보수: {profile['expense_ratio_pct']:g}%")
        if profile.get("aum"):
            parts.append(f"운용자산: {profile['aum']}")
        if profile.get("as_of"):
            parts.append(f"기준일: {profile['as_of']}")
        return "\n".join(parts)

    if content_type == "theme":
        profile = final_state.get("theme_profile") or {}
        parts = []
        value_chain = profile.get("value_chain") or []
        if value_chain:
            stages = []
            for item in value_chain[:8]:
                stage = item.get("stage")
                domestic = _plain_names(item.get("domestic_names") or [], 3)
                global_names = _plain_names(item.get("global_names") or [], 3)
                names = ", ".join(part for part in (domestic, global_names) if part)
                stages.append(f"{stage}: {names}" if names else str(stage))
            parts.append("밸류체인: " + " | ".join(stages))
        domestic_names = profile.get("domestic_names") or []
        global_names = profile.get("global_names") or []
        if domestic_names:
            parts.append("국내 대표 종목: " + _plain_names(domestic_names, 8))
        if global_names:
            parts.append("해외 대표 종목: " + _plain_names(global_names, 8))
        catalysts = profile.get("catalysts") or []
        if catalysts:
            parts.append("촉매: " + _plain_names(catalysts, 5))
        risks = profile.get("risks") or []
        if risks:
            parts.append("리스크: " + _plain_names(risks, 5))
        if profile.get("as_of"):
            parts.append(f"기준일: {profile['as_of']}")
        return "\n".join(parts)

    return ""


def _composition_status(final_state: dict[str, Any], content_type: str, composition_text: str) -> str:
    if content_type == "stock":
        profile = final_state.get("stock_profile") or {}
        if profile.get("business_lines") or profile.get("regions") or profile.get("products"):
            return "ready"
        return "ready" if composition_text else "needs_structured_data"
    if content_type == "etf":
        profile = final_state.get("etf_profile") or {}
        if profile.get("holdings") and profile.get("sectors") and profile.get("countries"):
            return "ready"
        return "needs_structured_data"
    if content_type == "theme":
        profile = final_state.get("theme_profile") or {}
        if profile.get("value_chain") and (profile.get("domestic_names") or profile.get("global_names")):
            return "ready"
        return "needs_structured_data"
    return "ready" if content_type == "stock" and composition_text else "needs_structured_data"


def _levels_complete(signal: dict[str, Any] | None) -> bool:
    levels = (signal or {}).get("levels") or {}
    return all(levels.get(field) not in (None, "") for field in (
        "entry", "stop", "target", "position_size_pct",
    ))


def _visual(id_: str, title: str, type_: str, status: str, data_required: list[str]) -> dict:
    return {
        "id": id_,
        "title": title,
        "type": type_,
        "status": status,
        "data_required": data_required,
    }


def _symbol_candidates(ticker: str) -> set[str]:
    normalized = str(ticker or "").strip().upper()
    candidates = {normalized}
    for suffix in (".KS", ".KQ", ".KR"):
        if normalized.endswith(suffix):
            candidates.add(normalized[: -len(suffix)])
    if normalized.startswith("KR-"):
        candidates.add(normalized[3:])
    return {candidate for candidate in candidates if candidate}


def _market_snapshot(final_state: dict[str, Any]) -> dict[str, Any]:
    snapshot = final_state.get("market_snapshot") or final_state.get("toss_market_snapshot") or {}
    return snapshot if isinstance(snapshot, dict) else {}


def _candles_for_ticker(final_state: dict[str, Any], ticker: str) -> list[dict[str, Any]]:
    candles = (_market_snapshot(final_state).get("candles") or {})
    if not isinstance(candles, dict):
        return []
    for key in _symbol_candidates(ticker):
        rows = candles.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _price_rows_for_ticker(final_state: dict[str, Any], ticker: str) -> list[dict[str, Any]]:
    rows = (_market_snapshot(final_state).get("prices") or [])
    if not isinstance(rows, list):
        return []
    candidates = _symbol_candidates(ticker)
    return [
        row
        for row in rows
        if isinstance(row, dict) and str(row.get("symbol") or "").upper() in candidates
    ]


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round((current / previous - 1) * 100, 2)


def _round_or_none(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _market_metrics(candles: list[dict[str, Any]]) -> dict[str, Any]:
    if not candles:
        return {}
    ordered = sorted(
        candles,
        key=lambda row: str(row.get("timestamp") or row.get("date") or ""),
    )
    closes = [_float_or_none(row.get("closePrice")) for row in ordered]
    volumes = [_float_or_none(row.get("volume")) for row in ordered]
    valid_closes = [value for value in closes if value is not None]
    if not valid_closes:
        return {}
    latest_close = closes[-1]

    def prior_close(days_back: int) -> float | None:
        if len(closes) <= days_back:
            return None
        return closes[-1 - days_back]

    recent_volumes = [value for value in volumes[-21:-1] if value is not None]
    latest_volume = volumes[-1] if volumes else None
    avg_volume_20d = sum(recent_volumes) / len(recent_volumes) if recent_volumes else None
    volume_ratio = (
        round(latest_volume / avg_volume_20d, 2)
        if latest_volume is not None and avg_volume_20d not in (None, 0)
        else None
    )
    return {
        key: value
        for key, value in {
            "latest_close": _round_or_none(latest_close),
            "return_1d_pct": _pct_change(latest_close, prior_close(1)),
            "return_5d_pct": _pct_change(latest_close, prior_close(5)),
            "return_20d_pct": _pct_change(latest_close, prior_close(20)),
            "high_60d": _round_or_none(max(valid_closes)),
            "low_60d": _round_or_none(min(valid_closes)),
            "latest_volume": _round_or_none(latest_volume, 0),
            "avg_volume_20d": _round_or_none(avg_volume_20d, 0),
            "volume_vs_20d_avg": volume_ratio,
        }.items()
        if value is not None
    }


def _market_data_summary(final_state: dict[str, Any], ticker: str) -> dict[str, Any]:
    snapshot = _market_snapshot(final_state)
    if not snapshot:
        return {}
    prices = _price_rows_for_ticker(final_state, ticker)
    candles = _candles_for_ticker(final_state, ticker)
    summary: dict[str, Any] = {
        "source": snapshot.get("source") or "market_snapshot",
        "snapshot_file": final_state.get("market_snapshot_file"),
        "symbols": snapshot.get("symbols") or [],
        "coverage": snapshot.get("coverage") or {},
        "latest_prices": prices,
        "candle_count": len(candles),
        "metrics": _market_metrics(candles),
    }
    return {key: value for key, value in summary.items() if value not in (None, "", [], {})}


def _composition_data(final_state: dict[str, Any], content_type: str) -> dict[str, Any]:
    if content_type == "stock":
        profile = final_state.get("stock_profile") or {}
        fields = (
            "profile_type",
            "ticker",
            "name",
            "exchange",
            "country",
            "currency",
            "sector",
            "industry",
            "description",
            "as_of",
            "source",
            "business_lines",
            "regions",
            "products",
            "peers",
            "catalysts",
            "risks",
        )
        return {key: profile.get(key) for key in fields if profile.get(key) not in (None, "", [])}

    if content_type == "etf":
        profile = final_state.get("etf_profile") or {}
        fields = (
            "profile_type",
            "ticker",
            "name",
            "issuer",
            "benchmark",
            "expense_ratio_pct",
            "aum",
            "currency",
            "as_of",
            "source",
            "holdings",
            "sectors",
            "countries",
        )
        return {key: profile.get(key) for key in fields if profile.get(key) not in (None, "", [])}

    if content_type == "theme":
        profile = final_state.get("theme_profile") or {}
        fields = (
            "profile_type",
            "ticker",
            "name",
            "description",
            "as_of",
            "source",
            "value_chain",
            "domestic_names",
            "global_names",
            "catalysts",
            "risks",
        )
        return {key: profile.get(key) for key in fields if profile.get(key) not in (None, "", [])}

    return {}


def _visuals_for(
    *,
    final_state: dict[str, Any],
    ticker: str,
    content_type: str,
    signal: dict[str, Any] | None,
) -> list[dict]:
    candles = _candles_for_ticker(final_state, ticker)
    has_price_trend = bool(candles)
    has_volume = any(row.get("volume") not in (None, "") for row in candles)
    visuals = [
        _visual("price_trend", "가격 추이", "line", "ready" if has_price_trend else "needs_data", ["ohlcv_1m", "ohlcv_3m", "ohlcv_1y"]),
        _visual("volume_change", "거래량 변화", "bar", "ready" if has_volume else "needs_data", ["ohlcv_volume"]),
        _visual("event_timeline", "이벤트 타임라인", "timeline", "needs_data", ["dated_news_or_filings"]),
    ]

    visuals.append(
        _visual(
            "price_ladder",
            "가격 사다리",
            "ladder",
            "ready" if _levels_complete(signal) else "hidden",
            ["signal.levels.entry", "signal.levels.stop", "signal.levels.target"],
        )
    )

    if content_type == "etf":
        etf_profile = final_state.get("etf_profile") or {}
        has_holdings = bool(etf_profile.get("holdings"))
        has_sectors = bool(etf_profile.get("sectors"))
        has_countries = bool(etf_profile.get("countries"))
        visuals.extend([
            _visual("etf_top_holdings", "상위 보유 종목", "bar", "ready" if has_holdings else "required_missing", ["etf_profile.holdings"]),
            _visual("etf_sector_allocation", "섹터 비중", "allocation", "ready" if has_sectors else "required_missing", ["etf_profile.sectors"]),
            _visual("etf_country_allocation", "국가 비중", "allocation", "ready" if has_countries else "required_missing", ["etf_profile.countries"]),
        ])
    elif content_type == "theme":
        theme_profile = final_state.get("theme_profile") or {}
        has_map = bool(theme_profile.get("value_chain"))
        has_names = bool(theme_profile.get("domestic_names") or theme_profile.get("global_names"))
        visuals.extend([
            _visual("theme_value_chain", "테마 밸류체인 지도", "map", "ready" if has_map else "required_missing", ["theme_profile.value_chain"]),
            _visual("theme_stock_ranking", "대표 종목 수익률 랭킹", "ranking", "ready" if has_names else "required_missing", ["theme_profile.domestic_names", "theme_profile.global_names"]),
        ])
    else:
        stock_profile = final_state.get("stock_profile") or {}
        has_business_mix = bool(
            stock_profile.get("business_lines")
            or stock_profile.get("regions")
            or stock_profile.get("products")
        )
        visuals.append(
            _visual(
                "business_mix",
                "사업/지역 구성",
                "allocation",
                "ready" if has_business_mix else "needs_data",
                ["stock_profile.business_lines", "stock_profile.regions"],
            )
        )

    return visuals


def _publish_gate(content_type: str, signal: dict[str, Any] | None, visuals: list[dict]) -> dict:
    reasons: list[str] = []
    warnings: list[str] = []
    required_missing = [v["id"] for v in visuals if v["status"] == "required_missing"]
    if required_missing:
        reasons.append("required_visual_data_missing:" + ",".join(required_missing))
    if signal and not _levels_complete(signal):
        warnings.append("price_ladder_hidden_incomplete_levels")

    status = "blocked" if required_missing else "ready"

    return {
        "status": status,
        "content_type": content_type,
        "reasons": reasons,
        "warnings": warnings,
        "rule": "ETF/theme composition visuals are required; incomplete price levels hide the ladder only.",
    }


def build_content_snapshot(
    final_state: dict[str, Any],
    ticker: str,
    generated_at: datetime | None = None,
) -> dict:
    """Build a no-LLM content handoff for beginner-facing publishing."""
    generated_at = generated_at or datetime.now()
    signal = final_state.get("final_trade_signal")
    risk = final_state.get("risk_debate_state") or {}
    debate = final_state.get("investment_debate_state") or {}
    final_decision = final_state.get("final_trade_decision") or risk.get("judge_decision", "")
    content_type = _content_type(final_state, ticker)
    visuals = _visuals_for(final_state=final_state, ticker=ticker, content_type=content_type, signal=signal)

    why_text = "\n".join(
        str(final_state.get(key, ""))
        for key in ("news_report", "market_report", "sentiment_report")
        if final_state.get(key)
    )
    profile_composition_text = _profile_composition_text(final_state, content_type)
    composition_text = (
        profile_composition_text
        or final_state.get("fundamentals_report")
        or final_state.get("instrument_context")
        or f"{ticker} 분석 대상"
    )
    instrument_text = _instrument_summary(final_state, ticker, content_type)
    composition_status = _composition_status(final_state, content_type, composition_text)
    bull_text = debate.get("bull_history", "")
    bear_text = debate.get("bear_history", "")

    cards = [
        {
            "id": "what_is_it",
            "title": "무엇인가",
            "status": "ready" if final_state.get("instrument_context") else "needs_review",
            **_summary(instrument_text, 260),
        },
        {
            "id": "why_moved",
            "title": "왜 움직였나",
            "status": "ready" if why_text else "needs_data",
            **_summary(why_text, 320),
        },
        {
            "id": "composition",
            "title": "무엇으로 구성되어 있나",
            "status": composition_status,
            **_summary(composition_text, 320),
        },
        {
            "id": "bull_bear",
            "title": "매수/매도 내러티브",
            "status": "ready" if bull_text or bear_text else "needs_review",
            "bull": _summary(bull_text, 220),
            "bear": _summary(bear_text, 220),
        },
        {
            "id": "risk",
            "title": "리스크",
            "status": "ready" if final_decision or risk.get("history") else "needs_review",
            **_summary((risk.get("history") or "") + "\n" + str(final_decision), 320),
        },
        {
            "id": "watch_next",
            "title": "다음 관찰 포인트",
            "status": "ready" if final_decision else "needs_review",
            **_summary(str(final_decision) or final_state.get("trader_investment_plan", ""), 260),
        },
    ]

    return {
        "schema_version": 1,
        "artifact": "content_snapshot",
        "ticker": ticker,
        "asset_type": final_state.get("asset_type", "stock"),
        "market_adapter": _market_adapter(ticker),
        "content_type": content_type,
        "audience": "beginner",
        "presentation": {
            "tone": "antwiki_like",
            "principles": [
                "easy everyday wording before financial jargon",
                "theme map and narrative cards before dense metrics",
                "wiki-style exploration across sector, theme, and names",
                "clear source badges and disclaimers without visual clutter",
            ],
        },
        "trade_date": final_state.get("trade_date"),
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "signal": signal,
        "cards": cards,
        "visuals": visuals,
        "composition_data": _composition_data(final_state, content_type),
        "market_data": _market_data_summary(final_state, ticker),
        "publish_gate": _publish_gate(content_type, signal, visuals),
        "source_policy": {
            "numbers": "Use only data-tool output, structured fields, or signal.json levels.",
            "llm_role": "Narrative compression only; no invented facts or prices.",
            "disclaimer": "Information only, not investment advice.",
        },
    }
