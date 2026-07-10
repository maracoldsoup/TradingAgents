"""Static no-LLM HTML preview for content snapshots."""

from __future__ import annotations

import contextlib
import html
from pathlib import Path
from typing import Any

from tradingagents.content_pilot import read_json
from tradingagents.dataflows.toss_market_snapshot import normalize_toss_symbol


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ticker_candidates(ticker: str) -> list[str]:
    candidates = [str(ticker or "").strip().upper()]
    with contextlib.suppress(ValueError):
        candidates.append(normalize_toss_symbol(ticker))
    seen = set()
    result = []
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return result


def find_content_snapshot_files(input_dir: Path) -> list[Path]:
    if input_dir.is_file():
        return [input_dir]
    files = sorted(input_dir.glob("*/content_snapshot.json"))
    if not files and (input_dir / "content_snapshot.json").exists():
        files = [input_dir / "content_snapshot.json"]
    return files


def _resolve_path(raw: str | None, *, content_file: Path, cwd: Path) -> Path | None:
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute() and path.exists():
        return path
    candidates = [
        cwd / path,
        content_file.parent / path,
        content_file.parent.parent / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _load_market_snapshot(content: dict[str, Any], content_file: Path, cwd: Path) -> tuple[dict[str, Any], Path | None]:
    market_data = content.get("market_data") or {}
    market_path = _resolve_path(market_data.get("snapshot_file"), content_file=content_file, cwd=cwd)
    if market_path:
        return read_json(market_path), market_path
    return {}, None


def _candles_for(content: dict[str, Any], market_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    candles = market_snapshot.get("candles") or {}
    if not isinstance(candles, dict):
        return []
    for candidate in _ticker_candidates(str(content.get("ticker") or "")):
        rows = candles.get(candidate)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _latest_price(content: dict[str, Any], market_snapshot: dict[str, Any]) -> dict[str, Any]:
    rows = market_snapshot.get("prices") or []
    candidates = set(_ticker_candidates(str(content.get("ticker") or "")))
    for row in rows:
        if isinstance(row, dict) and str(row.get("symbol") or "").upper() in candidates:
            return row
    latest = content.get("market_data", {}).get("latest_prices") or []
    return latest[0] if latest and isinstance(latest[0], dict) else {}


def _stock_info(content: dict[str, Any], market_snapshot: dict[str, Any]) -> dict[str, Any]:
    rows = market_snapshot.get("stocks") or []
    candidates = set(_ticker_candidates(str(content.get("ticker") or "")))
    for row in rows:
        if isinstance(row, dict) and str(row.get("symbol") or "").upper() in candidates:
            return row
    return {}


def _line_chart(candles: list[dict[str, Any]], *, width: int = 420, height: int = 160) -> str:
    rows = list(reversed(candles[-60:]))
    closes = [_num(row.get("closePrice")) for row in rows]
    values = [value for value in closes if value is not None]
    if len(values) < 2:
        return '<div class="empty-chart">가격 데이터 부족</div>'
    min_v, max_v = min(values), max(values)
    span = max(max_v - min_v, 1)
    step = width / max(len(rows) - 1, 1)
    points = []
    for index, row in enumerate(rows):
        value = _num(row.get("closePrice"))
        if value is None:
            continue
        x = round(index * step, 2)
        y = round(height - ((value - min_v) / span * (height - 18)) - 9, 2)
        points.append(f"{x},{y}")
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="가격 추이 차트">'
        f'<polyline points="{" ".join(points)}" fill="none" stroke="#176b87" '
        f'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<text x="0" y="15" class="axis-label">{max_v:,.0f}</text>'
        f'<text x="0" y="{height - 4}" class="axis-label">{min_v:,.0f}</text>'
        '</svg>'
    )


def _volume_chart(candles: list[dict[str, Any]], *, width: int = 420, height: int = 120) -> str:
    rows = list(reversed(candles[-60:]))
    volumes = [_num(row.get("volume")) for row in rows]
    values = [value for value in volumes if value is not None]
    if not values:
        return '<div class="empty-chart">거래량 데이터 부족</div>'
    max_v = max(values) or 1
    bar_w = max(width / max(len(rows), 1) - 1, 1)
    bars = []
    for index, row in enumerate(rows):
        value = _num(row.get("volume")) or 0
        bar_h = max(value / max_v * (height - 18), 1)
        x = round(index * (bar_w + 1), 2)
        y = round(height - bar_h, 2)
        bars.append(f'<rect x="{x}" y="{y}" width="{bar_w:.2f}" height="{bar_h:.2f}" rx="1"/>')
    return (
        f'<svg class="chart volume" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="거래량 변화 차트">{"".join(bars)}</svg>'
    )


def _metric(value: str, label: str) -> str:
    return f'<div class="metric"><span>{_esc(label)}</span><strong>{_esc(value)}</strong></div>'


def _fmt_pct(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.2f}%"


def _fmt_ratio(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):.2f}x"
    except (TypeError, ValueError):
        return "-"


def _fmt_number(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_price(value: Any, currency: Any = "") -> str:
    if value in (None, ""):
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if str(currency or "").upper() in {"USD", "EUR", "GBP", "CAD", "AUD", "HKD"}:
        return f"{number:,.2f}"
    return f"{number:,.0f}"


def _row_label(row: dict[str, Any]) -> str:
    return str(row.get("name") or row.get("ticker") or row.get("symbol") or "-")


def _row_meta(row: dict[str, Any]) -> str:
    parts = [
        str(row.get(key))
        for key in ("ticker", "symbol", "sector", "country", "role", "market", "stage")
        if row.get(key) not in (None, "", row.get("name"))
    ]
    return " · ".join(parts)


def _weighted_bars(title: str, rows: list[dict[str, Any]], *, limit: int = 8) -> str:
    clean_rows = [row for row in rows if isinstance(row, dict)]
    if not clean_rows:
        return ""
    weights = [_num(row.get("weight_pct")) for row in clean_rows]
    if not any(weight is not None for weight in weights):
        return _pills(title, clean_rows, limit=limit)
    max_weight = max([weight for weight in weights if weight is not None] or [100])
    items = []
    for row in clean_rows[:limit]:
        weight = _num(row.get("weight_pct"))
        width = max(4.0, min(100.0, (weight or 0) / max_weight * 100)) if weight is not None else 12.0
        meta = _row_meta(row)
        weight_text = f"{weight:g}%" if weight is not None else "-"
        items.append(
            '<div class="bar-row">'
            '<div class="bar-head">'
            f'<span><strong>{_esc(_row_label(row))}</strong>'
            f'{f"<em>{_esc(meta)}</em>" if meta else ""}</span>'
            f'<b>{_esc(weight_text)}</b>'
            '</div>'
            f'<div class="bar-track"><i style="width:{width:.2f}%"></i></div>'
            '</div>'
        )
    return (
        '<section class="composition-panel">'
        f'<h3>{_esc(title)}</h3>'
        f'{"".join(items)}'
        '</section>'
    )


def _pills(title: str, rows: list[dict[str, Any]], *, limit: int = 10) -> str:
    clean_rows = [row for row in rows if isinstance(row, dict)]
    if not clean_rows:
        return ""
    items = []
    for row in clean_rows[:limit]:
        meta = _row_meta(row)
        items.append(
            '<span class="pill">'
            f'<strong>{_esc(_row_label(row))}</strong>'
            f'{f"<em>{_esc(meta)}</em>" if meta else ""}'
            '</span>'
        )
    return (
        '<section class="composition-panel">'
        f'<h3>{_esc(title)}</h3>'
        f'<div class="pill-grid">{"".join(items)}</div>'
        '</section>'
    )


def _theme_value_chain(rows: list[dict[str, Any]]) -> str:
    clean_rows = [row for row in rows if isinstance(row, dict)]
    if not clean_rows:
        return ""
    stages = []
    for row in clean_rows[:8]:
        domestic = row.get("domestic_names") or []
        global_names = row.get("global_names") or []
        domestic_text = ", ".join(_row_label(item) for item in domestic[:3] if isinstance(item, dict))
        global_text = ", ".join(_row_label(item) for item in global_names[:3] if isinstance(item, dict))
        stages.append(
            '<article class="stage">'
            f'<h4>{_esc(row.get("stage") or row.get("name") or "-")}</h4>'
            f'<p>{_esc(row.get("description") or "")}</p>'
            f'{f"<small>국내: {_esc(domestic_text)}</small>" if domestic_text else ""}'
            f'{f"<small>해외: {_esc(global_text)}</small>" if global_text else ""}'
            '</article>'
        )
    return (
        '<section class="composition-panel wide">'
        '<h3>테마 밸류체인</h3>'
        f'<div class="stage-grid">{"".join(stages)}</div>'
        '</section>'
    )


def _composition_visual_html(content: dict[str, Any]) -> str:
    data = content.get("composition_data") or {}
    content_type = str(content.get("content_type") or "")
    if not isinstance(data, dict):
        return ""

    if content_type == "stock":
        panels = [
            _weighted_bars("사업 구성", data.get("business_lines") or []),
            _weighted_bars("지역 노출", data.get("regions") or []),
            _pills("핵심 제품/서비스", data.get("products") or []),
            _pills("비교 대상", data.get("peers") or []),
            _pills("상승 촉매", data.get("catalysts") or [], limit=6),
            _pills("주요 리스크", data.get("risks") or [], limit=6),
        ]
        body = "".join(panel for panel in panels if panel)
        if not body:
            return ""
        meta = " · ".join(
            str(data.get(key))
            for key in ("exchange", "sector", "industry", "as_of")
            if data.get(key) not in (None, "")
        )
        return (
            '<div class="composition-visual">'
            '<div class="composition-head">'
            f'<h3>{_esc(data.get("name") or content.get("ticker") or "종목")} 구성</h3>'
            f'{f"<p>{_esc(meta)}</p>" if meta else ""}'
            '</div>'
            f'<div class="composition-grid">{body}</div>'
            '</div>'
        )

    if content_type == "etf":
        panels = [
            _weighted_bars("상위 보유 종목", data.get("holdings") or []),
            _weighted_bars("섹터 비중", data.get("sectors") or []),
            _weighted_bars("국가 비중", data.get("countries") or []),
        ]
        body = "".join(panel for panel in panels if panel)
        if not body:
            return ""
        headline = data.get("name") or content.get("ticker") or "ETF"
        meta = " · ".join(
            str(data.get(key))
            for key in ("issuer", "benchmark", "as_of")
            if data.get(key) not in (None, "")
        )
        return (
            '<div class="composition-visual">'
            '<div class="composition-head">'
            f'<h3>{_esc(headline)} 구성</h3>'
            f'{f"<p>{_esc(meta)}</p>" if meta else ""}'
            '</div>'
            f'<div class="composition-grid">{body}</div>'
            '</div>'
        )

    if content_type == "theme":
        panels = [
            _theme_value_chain(data.get("value_chain") or []),
            _pills("국내 대표 종목", data.get("domestic_names") or []),
            _pills("해외 대표 종목", data.get("global_names") or []),
            _pills("상승 촉매", data.get("catalysts") or [], limit=6),
            _pills("주요 리스크", data.get("risks") or [], limit=6),
        ]
        body = "".join(panel for panel in panels if panel)
        if not body:
            return ""
        return (
            '<div class="composition-visual">'
            '<div class="composition-head">'
            f'<h3>{_esc(data.get("name") or content.get("ticker") or "테마")} 구성</h3>'
            f'<p>{_esc(data.get("description") or "")}</p>'
            '</div>'
            f'<div class="composition-grid">{body}</div>'
            '</div>'
        )

    return ""


def _card_html(card: dict[str, Any]) -> str:
    if card.get("id") == "bull_bear":
        bull = card.get("bull") or {}
        bear = card.get("bear") or {}

        def stance(label: str, payload: dict[str, Any]) -> str:
            text = payload.get("body") or payload.get("headline") or ""
            bullets = payload.get("bullets") or []
            bullet_html = ""
            if bullets:
                bullet_html = "<ul>" + "".join(f"<li>{_esc(item)}</li>" for item in bullets[:3]) + "</ul>"
            if not text and not bullet_html:
                return ""
            return (
                '<div class="stance">'
                f'<b>{_esc(label)}</b>'
                f'<p>{_esc(text)}</p>'
                f'{bullet_html}'
                '</div>'
            )

        body = stance("상승 요인", bull) + stance("주의 요인", bear)
        if not body:
            body = "<p></p>"
        return (
            '<article class="content-card">'
            f'<div class="card-title">{_esc(card.get("title"))}<span>{_esc(card.get("status"))}</span></div>'
            f'<div class="stance-grid">{body}</div>'
            '</article>'
        )

    bullets = card.get("bullets") or []
    body = card.get("body") or card.get("headline") or ""
    bullet_html = ""
    if bullets:
        bullet_html = "<ul>" + "".join(f"<li>{_esc(item)}</li>" for item in bullets[:3]) + "</ul>"
    return (
        '<article class="content-card">'
        f'<div class="card-title">{_esc(card.get("title"))}<span>{_esc(card.get("status"))}</span></div>'
        f'<p>{_esc(body)}</p>{bullet_html}'
        '</article>'
    )


def _instrument_html(item: dict[str, Any]) -> str:
    content = item["content"]
    candles = item["candles"]
    latest = item["latest_price"]
    stock = item["stock"]
    gate = content.get("publish_gate") or {}
    signal = content.get("signal") or {}
    levels = signal.get("levels") or {}
    cards = content.get("cards") or []
    visuals = content.get("visuals") or []
    content_type = str(content.get("content_type") or "")
    composition_data = content.get("composition_data") or {}
    market_metrics = content.get("market_data", {}).get("metrics") or {}
    currency = latest.get("currency") or stock.get("currency") or composition_data.get("currency") or ""
    visual_chips = "".join(
        f'<span class="chip { _esc(visual.get("status")) }">{_esc(visual.get("title"))}: {_esc(visual.get("status"))}</span>'
        for visual in visuals
    )
    has_market_metrics = bool(latest or market_metrics or candles or (content_type == "stock" and not composition_data))
    if has_market_metrics:
        metrics = [
            _metric(_fmt_price(latest.get("lastPrice") or market_metrics.get("latest_close"), currency), "현재가"),
            _metric(str(currency or "-"), "통화"),
            _metric(str(signal.get("rating") or "-"), "판정"),
            _metric(str(gate.get("status") or "-"), "발행 상태"),
            _metric(_fmt_pct(market_metrics.get("return_1d_pct")), "1일"),
            _metric(_fmt_pct(market_metrics.get("return_5d_pct")), "5일"),
            _metric(_fmt_pct(market_metrics.get("return_20d_pct")), "20일"),
            _metric(_fmt_ratio(market_metrics.get("volume_vs_20d_avg")), "거래량/20일"),
            _metric(_fmt_price(market_metrics.get("high_60d"), currency), "60일 고가"),
            _metric(_fmt_price(market_metrics.get("low_60d"), currency), "60일 저가"),
        ]
    else:
        metrics = [
            _metric(content_type or "-", "유형"),
            _metric(str(content.get("market_adapter") or "-"), "시장"),
            _metric(str(gate.get("status") or "-"), "발행 상태"),
            _metric(str(composition_data.get("as_of") or "-"), "구성 기준일"),
            _metric(str(composition_data.get("currency") or "-"), "통화"),
        ]
        if content_type == "stock":
            metrics.extend([
                _metric(str(composition_data.get("exchange") or "-"), "거래소"),
                _metric(str(composition_data.get("sector") or "-"), "섹터"),
                _metric(str(len(composition_data.get("products") or [])), "제품/서비스"),
            ])
        elif content_type == "etf":
            metrics.extend([
                _metric(str(composition_data.get("expense_ratio_pct") or "-"), "총보수 %"),
                _metric(str(len(composition_data.get("holdings") or [])), "보유 종목"),
                _metric(str(len(composition_data.get("countries") or [])), "국가 수"),
            ])
        elif content_type == "theme":
            domestic = len(composition_data.get("domestic_names") or [])
            global_names = len(composition_data.get("global_names") or [])
            metrics.extend([
                _metric(str(len(composition_data.get("value_chain") or [])), "밸류체인 단계"),
                _metric(str(domestic), "국내 종목"),
                _metric(str(global_names), "해외 종목"),
            ])
    if levels:
        metrics.extend([
            _metric(str(levels.get("entry") or "-"), "진입"),
            _metric(str(levels.get("stop") or "-"), "손절"),
            _metric(str(levels.get("target") or "-"), "목표"),
        ])
    selected_cards = "".join(_card_html(card) for card in cards[:4])
    composition_visual = _composition_visual_html(content)
    chart_block = ""
    if candles or (content_type == "stock" and not composition_data):
        chart_block = (
            '<div class="chart-grid">'
            f'<div><h3>가격 추이</h3>{_line_chart(candles)}</div>'
            f'<div><h3>거래량 변화</h3>{_volume_chart(candles)}</div>'
            '</div>'
        )
    return (
        '<section class="instrument">'
        '<div class="instrument-head">'
        '<div>'
        f'<h2>{_esc(content.get("ticker"))}</h2>'
        f'<p>{_esc(stock.get("name") or stock.get("englishName") or composition_data.get("name") or content.get("content_type"))}</p>'
        '</div>'
        f'<span class="source">{_esc(content.get("market_data", {}).get("source") or "local")}</span>'
        '</div>'
        f'<div class="metrics">{"".join(metrics)}</div>'
        f'<div class="visual-chips">{visual_chips}</div>'
        f'{composition_visual}'
        f'{chart_block}'
        f'<div class="cards">{selected_cards}</div>'
        '</section>'
    )


def load_preview_items(input_dir: Path, cwd: Path | None = None) -> list[dict[str, Any]]:
    cwd = cwd or Path.cwd()
    items = []
    for content_file in find_content_snapshot_files(input_dir):
        content = read_json(content_file)
        if content.get("artifact") != "content_snapshot":
            continue
        market_snapshot, market_file = _load_market_snapshot(content, content_file, cwd)
        items.append({
            "content_file": content_file,
            "market_file": market_file,
            "content": content,
            "market_snapshot": market_snapshot,
            "candles": _candles_for(content, market_snapshot),
            "latest_price": _latest_price(content, market_snapshot),
            "stock": _stock_info(content, market_snapshot),
        })
    return items


def render_content_preview(input_dir: Path, output: Path, *, title: str = "TradingAgents Local Content Preview") -> Path:
    items = load_preview_items(input_dir)
    ready = sum(1 for item in items if item["content"].get("publish_gate", {}).get("status") == "ready")
    price_ready = sum(1 for item in items if item["candles"])
    body = "\n".join(_instrument_html(item) for item in items)
    html_text = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <style>
    :root {{
      --ink: #1b1f23;
      --muted: #64707d;
      --line: #d8dee4;
      --paper: #fbfbf8;
      --panel: #ffffff;
      --accent: #176b87;
      --green: #20845a;
      --amber: #9a6700;
      --red: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 24px clamp(16px, 4vw, 48px) 16px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }}
    h1, h2, h3, p {{ margin-top: 0; }}
    h1 {{ font-size: 28px; margin-bottom: 8px; letter-spacing: 0; }}
    h2 {{ font-size: 22px; margin-bottom: 2px; letter-spacing: 0; }}
    h3 {{ font-size: 14px; margin-bottom: 8px; letter-spacing: 0; }}
    main {{ padding: 18px clamp(16px, 4vw, 48px) 48px; }}
    .summary {{ display: flex; flex-wrap: wrap; gap: 10px; color: var(--muted); }}
    .summary strong {{ color: var(--ink); }}
    .instrument {{
      border-top: 1px solid var(--line);
      padding: 22px 0 28px;
    }}
    .instrument-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 14px;
    }}
    .instrument-head p {{ color: var(--muted); margin-bottom: 0; }}
    .source {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 9px;
      color: var(--muted);
      white-space: nowrap;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
      gap: 8px;
      margin-bottom: 12px;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: var(--panel);
      min-height: 62px;
    }}
    .metric span {{ display: block; color: var(--muted); font-size: 12px; }}
    .metric strong {{ display: block; font-size: 17px; overflow-wrap: anywhere; }}
    .visual-chips {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }}
    .chip {{
      border-radius: 999px;
      padding: 4px 8px;
      background: #eef6f8;
      color: var(--accent);
      font-size: 12px;
    }}
    .chip.hidden, .chip.needs_data {{ background: #fff7e6; color: var(--amber); }}
    .chip.required_missing {{ background: #fff1f0; color: var(--red); }}
    .chart-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 18px;
      margin-bottom: 18px;
    }}
    .chart-grid > div {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      background: var(--panel);
      min-width: 0;
    }}
    .chart {{ width: 100%; height: auto; display: block; }}
    .volume rect {{ fill: #8fb9aa; }}
    .axis-label {{ fill: var(--muted); font-size: 11px; }}
    .empty-chart {{
      min-height: 120px;
      display: grid;
      place-items: center;
      color: var(--muted);
      border: 1px dashed var(--line);
      border-radius: 6px;
    }}
    .composition-visual {{
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      padding: 14px;
      margin-bottom: 18px;
    }}
    .composition-head {{
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: flex-start;
      border-bottom: 1px solid var(--line);
      padding-bottom: 10px;
      margin-bottom: 12px;
    }}
    .composition-head h3 {{ margin-bottom: 0; font-size: 16px; }}
    .composition-head p {{
      max-width: 520px;
      margin-bottom: 0;
      color: var(--muted);
      text-align: right;
    }}
    .composition-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
    }}
    .composition-panel {{
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      background: #fff;
    }}
    .composition-panel.wide {{ grid-column: 1 / -1; }}
    .bar-row + .bar-row {{ margin-top: 10px; }}
    .bar-head {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: flex-start;
      margin-bottom: 4px;
    }}
    .bar-head span {{ min-width: 0; }}
    .bar-head strong {{
      display: block;
      overflow-wrap: anywhere;
    }}
    .bar-head em, .pill em {{
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-style: normal;
    }}
    .bar-head b {{ white-space: nowrap; }}
    .bar-track {{
      height: 8px;
      border-radius: 999px;
      background: #edf1f3;
      overflow: hidden;
    }}
    .bar-track i {{
      display: block;
      height: 100%;
      border-radius: inherit;
      background: var(--accent);
    }}
    .pill-grid {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .pill {{
      display: inline-flex;
      flex-direction: column;
      max-width: 100%;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 9px;
      background: #fbfbf8;
    }}
    .pill strong {{ overflow-wrap: anywhere; }}
    .stage-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
    }}
    .stage {{
      border-left: 3px solid var(--accent);
      padding: 8px 10px;
      background: #fbfbf8;
      min-width: 0;
    }}
    .stage h4 {{ margin: 0 0 4px; font-size: 13px; }}
    .stage p {{ margin-bottom: 6px; color: #30363d; }}
    .stage small {{ display: block; color: var(--muted); overflow-wrap: anywhere; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 10px;
    }}
    .content-card {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      background: var(--panel);
      min-width: 0;
    }}
    .card-title {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-weight: 700;
      margin-bottom: 8px;
    }}
    .card-title span {{ color: var(--green); font-size: 12px; font-weight: 500; }}
    .content-card p, .content-card li {{ color: #30363d; }}
    .content-card ul {{ padding-left: 18px; margin-bottom: 0; }}
    .stance-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 8px;
    }}
    .stance {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      background: #fbfbf8;
      min-width: 0;
    }}
    .stance b {{ display: block; margin-bottom: 4px; }}
    .stance p {{ margin-bottom: 6px; }}
    @media (max-width: 760px) {{
      .chart-grid {{ grid-template-columns: 1fr; }}
      .instrument-head {{ display: block; }}
      .source {{ display: inline-block; margin-top: 8px; }}
      .composition-head {{ display: block; }}
      .composition-head p {{ text-align: left; margin-top: 4px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{_esc(title)}</h1>
    <div class="summary">
      <span>콘텐츠 <strong>{len(items)}</strong>개</span>
      <span>발행 가능 <strong>{ready}</strong>개</span>
      <span>가격 차트 준비 <strong>{price_ready}</strong>개</span>
      <span>외부 LLM 사용 <strong>없음</strong></span>
    </div>
  </header>
  <main>
    {body}
  </main>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8")
    return output
