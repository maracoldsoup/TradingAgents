"""Public service API for stock, ETF, and theme content assets."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tradingagents.service_assets import find_asset, load_assets, theme_assets

if TYPE_CHECKING:
    from fastapi.responses import HTMLResponse

DEFAULT_ASSET_DIRS = (
    Path(".pilot/content_with_market"),
    Path(".pilot/profile_content"),
    Path(".pilot/profiles"),
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


@dataclass(frozen=True)
class ServiceApiConfig:
    """Paths used by the public service API."""

    asset_dirs: tuple[Path, ...] = DEFAULT_ASSET_DIRS
    candidate_queue_path: Path = Path(".pilot/candidates/candidate_queue.json")
    candidate_gap_path: Path = Path(".pilot/candidates/candidate_gap.json")
    candidate_review_path: Path = Path(".pilot/candidates/candidate_input_review.json")
    assessment_path: Path = Path(".pilot/assessment/pilot_assessment.json")
    content_summary_paths: tuple[Path, ...] = (
        Path(".pilot/content_with_market/content_pilot_summary.json"),
        Path(".pilot/profile_content/profile_content_pilot_summary.json"),
    )
    rankings_snapshot_dir: Path = Path(".pilot/toss_rankings")
    api_key: str = ""
    """Bearer token required on /api/* routes. Empty string disables auth
    (local/dev default). Set RESEARCH_GATEWAY_API_KEY before exposing this
    service publicly — see docs/aimyticker_integration_architecture.md."""
    enable_background_jobs: bool = False
    """Run the Toss rankings collector in-process on a timer (see
    tradingagents/scheduler.py) instead of via a separate cron/platform job.
    Off by default so import/tests never trigger network calls."""
    rankings_poll_interval_seconds: float = 300


def _latest_rankings_snapshot(rankings_snapshot_dir: Path) -> dict[str, Any] | None:
    """Return the most recently written toss_rankings_snapshot, if any.

    Filenames from `collect_toss_rankings.py` embed a `%Y%m%d_%H%M%S`
    timestamp, so lexicographic sort order is also chronological order.
    """
    if not rankings_snapshot_dir.exists():
        return None
    files = [rankings_snapshot_dir] if rankings_snapshot_dir.is_file() else sorted(rankings_snapshot_dir.glob("*.json"))
    for file_path in reversed(files):
        payload = _read_json(file_path)
        if payload.get("artifact") == "toss_rankings_snapshot":
            return payload
    return None


def load_breaking_list(config: ServiceApiConfig) -> dict[str, Any]:
    """Load the current breaking-item list from the latest rankings snapshot."""
    from tradingagents.breaking_feed import build_breaking_list_payload

    snapshot = _latest_rankings_snapshot(config.rankings_snapshot_dir)
    if snapshot is None:
        return {
            "schema_version": 1,
            "artifact": "service_breaking_list",
            "generated_at": None,
            "count": 0,
            "items": [],
        }
    return build_breaking_list_payload(snapshot)


def _asset_summary(asset: dict[str, Any]) -> dict[str, Any]:
    one_liner = asset.get("one_liner") or {}
    why_moved = asset.get("why_moved") or {}
    visuals = asset.get("visuals") or []
    return {
        "id": asset.get("id"),
        "kind": asset.get("kind"),
        "ticker": asset.get("ticker"),
        "name": asset.get("name"),
        "market": asset.get("market"),
        "one_liner": one_liner.get("summary"),
        "why_moved": why_moved.get("summary"),
        "publish_status": asset.get("publish_status"),
        "as_of": asset.get("as_of"),
        "sources": asset.get("sources") or [],
        "visuals_ready": sum(1 for visual in visuals if visual.get("status") == "ready"),
        "visuals_total": len(visuals),
        "review_status": (asset.get("review") or {}).get("status"),
    }


def _review_summary(asset: dict[str, Any]) -> dict[str, Any]:
    review = asset.get("review") or {}
    metrics = review.get("metrics") or {}
    return {
        "asset_id": asset.get("id"),
        "kind": asset.get("kind"),
        "ticker": asset.get("ticker"),
        "name": asset.get("name"),
        "market": asset.get("market"),
        "status": review.get("status"),
        "published_at": review.get("published_at"),
        "basis": review.get("basis"),
        "metrics": metrics,
        "note": review.get("note"),
    }


def _esc(value: Any) -> str:
    return "" if value is None else html.escape(str(value), quote=True)


def _kind_label(kind: Any) -> str:
    return {"stock": "종목", "etf": "ETF", "theme": "테마"}.get(str(kind or ""), str(kind or "-"))


def _route_slug(value: Any) -> str:
    raw = str(value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9가-힣]+", "-", raw)
    return slug.strip("-") or "asset"


def _asset_href(asset: dict[str, Any]) -> str:
    slug = _route_slug(asset.get("ticker") or asset.get("id"))
    if asset.get("kind") == "stock":
        return f"/stocks/{_esc(slug)}"
    if asset.get("kind") == "etf":
        return f"/etfs/{_esc(slug)}"
    if asset.get("kind") == "theme":
        return f"/themes/{_esc(slug)}"
    return f"/assets/{_esc(asset.get('id'))}"


def _find_public_asset(assets: list[dict[str, Any]], *, kind: str, slug: str) -> dict[str, Any] | None:
    normalized = _route_slug(slug)
    for asset in assets:
        if asset.get("kind") != kind:
            continue
        if _route_slug(asset.get("ticker") or asset.get("id")) == normalized:
            return asset
    return None


def _asset_page_or_404(asset: dict[str, Any] | None) -> HTMLResponse:
    if not asset:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="asset not found")
    from fastapi.responses import HTMLResponse

    return HTMLResponse(_asset_html(asset))


def _source_badges(asset: dict[str, Any]) -> str:
    return "".join(
        f'<span class="source">{_esc(source.get("kind"))}: {_esc(source.get("label"))}</span>'
        for source in asset.get("sources") or []
    )


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


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_weight(value: Any) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:g}%"


def _sum_weights(rows: list[dict[str, Any]], *, limit: int) -> float | None:
    values = [_number(row.get("weight_pct")) for row in rows[:limit]]
    clean = [value for value in values if value is not None]
    return sum(clean) if clean else None


def _largest_weight_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    weighted = [(row, _number(row.get("weight_pct"))) for row in rows]
    weighted = [(row, value) for row, value in weighted if value is not None]
    if not weighted:
        return rows[0] if rows else {}
    return max(weighted, key=lambda item: item[1])[0]


def _bar_rows(rows: list[dict[str, Any]], *, label_key: str = "name", limit: int = 8) -> str:
    bars = []
    for row in rows[:limit]:
        label = row.get(label_key) or row.get("ticker") or row.get("stage") or "-"
        weight = row.get("weight_pct")
        try:
            width = max(4, min(100, float(weight)))
            value = f"{float(weight):g}%"
        except (TypeError, ValueError):
            width = 12
            value = row.get("ticker") or ""
        bars.append(
            '<div class="bar-row">'
            f'<span>{_esc(label)}</span><b>{_esc(value)}</b>'
            f'<i style="width:{width:.2f}%"></i>'
            '</div>'
        )
    return "".join(bars)


def _asset_card(asset: dict[str, Any]) -> str:
    one_liner = asset.get("one_liner") or {}
    why_moved = asset.get("why_moved") or {}
    composition = asset.get("composition") or {}
    visual = ""
    if asset.get("kind") == "etf":
        visual = _bar_rows(composition.get("holdings") or [], limit=5)
    elif asset.get("kind") == "theme":
        stages = composition.get("value_chain") or []
        visual = "".join(
            '<div class="stage-chip">'
            f'<b>{_esc(stage.get("stage") or stage.get("name"))}</b>'
            f'<span>{_esc(stage.get("description") or "대표 종목 연결")}</span>'
            '</div>'
            for stage in stages[:4]
        )
    else:
        visual = _bar_rows(composition.get("regions") or composition.get("business_lines") or [], limit=4)
    return (
        f'<article class="asset-card { _esc(asset.get("kind")) }">'
        '<div class="asset-top">'
        f'<span>{_kind_label(asset.get("kind"))} · {_esc(asset.get("market"))}</span>'
        f'<b>{_esc(asset.get("publish_status"))}</b>'
        '</div>'
        f'<h3><a href="{_asset_href(asset)}">{_esc(asset.get("name"))}</a></h3>'
        f'<p class="ticker">{_esc(asset.get("ticker"))}</p>'
        f'<p>{_esc(one_liner.get("summary"))}</p>'
        '<section class="why">'
        '<strong>왜 움직였나</strong>'
        f'<p>{_esc(why_moved.get("summary") or "원인 데이터 대기")}</p>'
        '</section>'
        f'<div class="mini-visual">{visual or "<span>구성 데이터 대기</span>"}</div>'
        f'<div class="sources">{_source_badges(asset)}</div>'
        '</article>'
    )


def _theme_map(themes: list[dict[str, Any]]) -> str:
    if not themes:
        return '<p class="muted">테마 데이터 대기</p>'
    return "".join(
        '<a class="theme-node" href="' + _asset_href(theme) + '">'
        f'<b>{_esc(theme.get("name"))}</b>'
        f'<span>{_esc((theme.get("why_moved") or {}).get("summary"))}</span>'
        '</a>'
        for theme in themes[:6]
    )


def _kind_search_href(kind: str | None = None) -> str:
    return "/search" if not kind else f"/search?kind={_esc(kind)}"


def _kind_tabs(*, current: str | None = None, counts: dict[str, int] | None = None) -> str:
    counts = counts or {}
    items = [
        (None, "전체", sum(counts.values())),
        ("stock", "종목 탐색", counts.get("stock", 0)),
        ("etf", "ETF 구성", counts.get("etf", 0)),
        ("theme", "섹터·테마", counts.get("theme", 0)),
    ]
    return "".join(
        '<a class="kind-tab'
        + (" active" if (current or None) == kind else "")
        + f'" href="{_kind_search_href(kind)}">'
        f'<span>{_esc(label)}</span><b>{_esc(count)}</b>'
        '</a>'
        for kind, label, count in items
    )


def _quick_search_panel(counts: dict[str, int]) -> str:
    return (
        '<section class="quick-panel">'
        '<span class="eyebrow">Ctrl+K 대신 바로 검색</span>'
        '<h2>빠른 탐색</h2>'
        '<form class="search-form compact" method="get" action="/search">'
        '<input name="q" placeholder="예: 삼성전자, Apple, AI, ETF">'
        '<button>검색</button>'
        '</form>'
        '<div class="kind-tabs compact-tabs">'
        f'{_kind_tabs(counts=counts)}'
        '</div>'
        '<a class="text-link" href="/review">발행 후 실제 흐름 보기</a>'
        '</section>'
    )


def _explore_lanes(stocks: list[dict[str, Any]], etfs: list[dict[str, Any]], themes: list[dict[str, Any]], reviewed: int) -> str:
    lanes = [
        ("종목 탐색", f"{len(stocks)}개", "기업 개요, 움직인 이유, 비교 대상을 먼저 봅니다.", _kind_search_href("stock")),
        ("ETF 구성", f"{len(etfs)}개", "상위 보유 종목과 섹터·국가 비중을 한 화면에서 봅니다.", _kind_search_href("etf")),
        ("섹터·테마", f"{len(themes)}개", "밸류체인 단계와 국내·해외 연결 종목을 따라갑니다.", _kind_search_href("theme")),
        ("검증 로그", f"{reviewed}개", "발행 뒤 1일·5일·20일 변화와 근거를 남깁니다.", "/review"),
    ]
    return "".join(
        '<a class="lane-card" href="' + href + '">'
        f'<span>{_esc(value)}</span>'
        f'<b>{_esc(title)}</b>'
        f'<p>{_esc(body)}</p>'
        '</a>'
        for title, value, body, href in lanes
    )


def _narrative_rail(assets: list[dict[str, Any]]) -> str:
    rows = []
    for asset in assets[:6]:
        rows.append(
            '<a class="narrative-row" href="' + _asset_href(asset) + '">'
            f'<span>{_kind_label(asset.get("kind"))}</span>'
            f'<b>{_esc(asset.get("name"))}</b>'
            f'<p>{_esc((asset.get("why_moved") or {}).get("summary") or "원인 데이터 대기")}</p>'
            '</a>'
        )
    return "".join(rows) or '<p class="muted">내러티브 데이터 대기</p>'


def _etf_shelf(etfs: list[dict[str, Any]]) -> str:
    if not etfs:
        return '<p class="muted">ETF 구성 데이터 대기</p>'
    return "".join(
        '<article class="shelf-card">'
        f'<h3><a href="{_asset_href(etf)}">{_esc(etf.get("name"))}</a></h3>'
        f'<p class="ticker">{_esc(etf.get("ticker"))}</p>'
        f'{_mini_holdings(etf)}'
        '</article>'
        for etf in etfs[:4]
    )


def _mini_holdings(asset: dict[str, Any]) -> str:
    rows = _bar_rows((asset.get("composition") or {}).get("holdings") or [], limit=4)
    return rows or '<p class="muted">보유 종목 대기</p>'


def _review_shelf(assets: list[dict[str, Any]]) -> str:
    reviewed = [asset for asset in assets if (asset.get("review") or {}).get("status") == "available"]
    if not reviewed:
        return '<p class="muted">사후 점검 데이터 대기</p>'
    rows = []
    for asset in reviewed[:4]:
        metrics = ((asset.get("review") or {}).get("metrics") or {})
        rows.append(
            '<a class="review-row" href="' + _asset_href(asset) + '">'
            f'<b>{_esc(asset.get("name"))}</b>'
            f'<span>{_fmt_pct(metrics.get("return_1d_pct"))} · {_fmt_pct(metrics.get("return_5d_pct"))}</span>'
            '</a>'
        )
    return "".join(rows)


def _trend_row(asset: dict[str, Any], rank: int) -> str:
    review = asset.get("review") or {}
    metrics = review.get("metrics") or {}
    day = _fmt_pct(metrics.get("return_1d_pct"))
    week = _fmt_pct(metrics.get("return_5d_pct"))
    return (
        '<a class="trend-row" href="' + _asset_href(asset) + '">'
        f'<span class="trend-rank">{rank:02d}</span>'
        '<div class="trend-name">'
        f'<b>{_esc(asset.get("name"))}</b>'
        f'<small>{_esc(asset.get("ticker"))} · {_kind_label(asset.get("kind"))} · {_esc(asset.get("market"))}</small>'
        '</div>'
        f'<p>{_esc((asset.get("why_moved") or {}).get("summary") or "원인 데이터 대기")}</p>'
        f'<em>{day} / {week}</em>'
        '</a>'
    )


def _trend_table(assets: list[dict[str, Any]], limit: int = 7) -> str:
    if not assets:
        return '<p class="muted">오늘 볼 콘텐츠가 아직 없습니다.</p>'
    return "".join(_trend_row(asset, index + 1) for index, asset in enumerate(assets[:limit]))


def _home_theme_feature(themes: list[dict[str, Any]]) -> str:
    if not themes:
        return '<section class="wiki-panel"><h2>테마 지도</h2><p class="muted">테마 데이터 대기</p></section>'
    theme = themes[0]
    composition = theme.get("composition") or {}
    stages = "".join(
        '<span class="path-chip">'
        f'<b>{_esc(stage.get("stage") or stage.get("name"))}</b>'
        f'<i>{len(stage.get("domestic_names") or [])} KR · {len(stage.get("global_names") or [])} US</i>'
        '</span>'
        for stage in (composition.get("value_chain") or [])[:5]
    )
    stages_fallback = '<span class="path-chip"><b>밸류체인 대기</b><i>data pending</i></span>'
    return (
        '<section class="wiki-panel theme-feature">'
        '<div class="panel-kicker">Theme Map</div>'
        f'<h2><a href="{_asset_href(theme)}">{_esc(theme.get("name"))}</a></h2>'
        f'<p>{_esc((theme.get("why_moved") or {}).get("summary") or composition.get("description") or "테마 설명 대기")}</p>'
        f'<div class="pathway">{stages or stages_fallback}</div>'
        '</section>'
    )


def _home_etf_feature(etfs: list[dict[str, Any]]) -> str:
    if not etfs:
        return '<section class="wiki-panel"><h2>ETF X-ray</h2><p class="muted">ETF 데이터 대기</p></section>'
    etf = etfs[0]
    composition = etf.get("composition") or {}
    holdings = _bar_rows(composition.get("holdings") or [], limit=5) or '<p class="muted">보유 종목 데이터 대기</p>'
    top5 = _sum_weights(composition.get("holdings") or [], limit=5)
    return (
        '<section class="wiki-panel etf-feature">'
        '<div class="panel-kicker">ETF X-ray</div>'
        f'<h2><a href="{_asset_href(etf)}">{_esc(etf.get("name"))}</a></h2>'
        f'<p>{_esc(etf.get("ticker"))} · 상위 5개 비중 {_fmt_weight(top5)}</p>'
        f'<div class="mini-visual">{holdings}</div>'
        '</section>'
    )


def _home_review_feature(assets: list[dict[str, Any]]) -> str:
    reviewed = [asset for asset in assets if (asset.get("review") or {}).get("status") == "available"]
    return (
        '<section class="wiki-panel review-feature">'
        '<div class="panel-kicker">Review</div>'
        '<h2><a href="/review">발행 후 실제 흐름</a></h2>'
        f'<p>{len(reviewed)}개 콘텐츠에 1일·5일·20일 변화가 연결되어 있습니다.</p>'
        f'<div class="review-list compact-review">{_review_shelf(assets)}</div>'
        '</section>'
    )


def _filter_assets(assets: list[dict[str, Any]], *, kind: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
    rows = assets
    if kind:
        rows = [asset for asset in rows if asset.get("kind") == kind]
    if q:
        needle = q.lower()
        rows = [
            asset for asset in rows
            if needle in str(asset.get("ticker") or "").lower()
            or needle in str(asset.get("name") or "").lower()
            or needle in str((asset.get("why_moved") or {}).get("summary") or "").lower()
        ]
    return rows


def _home_html(assets: list[dict[str, Any]]) -> str:
    stocks = [asset for asset in assets if asset.get("kind") == "stock"]
    etfs = [asset for asset in assets if asset.get("kind") == "etf"]
    themes = [asset for asset in assets if asset.get("kind") == "theme"]
    lead = assets[0] if assets else None
    lead_href = _asset_href(lead) if lead else "/search"
    lead_name = _esc(lead.get("name") if lead else "리서치 위키")
    lead_why = _esc((lead.get("why_moved") or {}).get("summary") if lead else "종목, ETF, 테마를 검색하면 움직인 이유와 구성을 같이 봅니다.")
    return _page_shell(
        title="Research Gateway",
        body=f"""
        <main class="wiki-home">
          <section class="wiki-hero">
            <div class="hero-main">
              <span class="eyebrow">Research Wiki</span>
              <h1>왜 움직였고, 무엇으로 구성됐는지 바로 읽습니다</h1>
              <p>국내·해외 종목, ETF, 테마를 추천이 아니라 설명 가능한 콘텐츠로 정리합니다.</p>
              <form class="wiki-search" method="get" action="/search">
                <input name="q" placeholder="종목명, 티커, ETF, 테마 검색">
                <button>검색</button>
              </form>
              <div class="topic-chips">
                <a href="/search?kind=stock">종목 {len(stocks)}</a>
                <a href="/search?kind=etf">ETF {len(etfs)}</a>
                <a href="/search?kind=theme">테마 {len(themes)}</a>
                <a href="/review">사후 점검</a>
              </div>
            </div>
            <a class="hero-lead" href="{lead_href}">
              <span>오늘 먼저 볼 흐름</span>
              <b>{lead_name}</b>
              <p>{lead_why}</p>
            </a>
          </section>
          <section class="wiki-section">
            <div class="wiki-section-head">
              <h2>오늘 움직인 흐름</h2>
              <p>가격 숫자보다 먼저, 움직인 이유와 연결된 자산을 봅니다.</p>
            </div>
            <div class="trend-table">{_trend_table(assets)}</div>
          </section>
          <section class="wiki-feature-grid">
            {_home_theme_feature(themes)}
            {_home_etf_feature(etfs)}
            {_home_review_feature(assets)}
          </section>
          <section class="wiki-section">
            <div class="wiki-section-head">
              <h2>종목·ETF·테마 전체</h2>
              <p>위키처럼 훑고, 필요한 항목만 상세로 들어갑니다.</p>
            </div>
            <div class="asset-grid">{''.join(_asset_card(asset) for asset in assets[:12]) or '<section class="empty"><h2>아직 발행 가능한 콘텐츠가 없습니다</h2><p>로컬 파일럿에서 content_snapshot을 생성하면 여기에 표시됩니다.</p></section>'}</div>
          </section>
        </main>
        """,
    )


def _search_html(assets: list[dict[str, Any]], *, q: str | None = None, kind: str | None = None) -> str:
    rows = _filter_assets(assets, kind=kind, q=q)
    cards = "".join(_asset_card(asset) for asset in rows)
    if not cards:
        cards = '<section class="empty"><h2>검색 결과가 없습니다</h2><p>다른 종목명, 티커, ETF, 테마 키워드로 다시 찾아보세요.</p></section>'
    query_value = _esc(q or "")
    counts = {
        "stock": len([asset for asset in assets if asset.get("kind") == "stock"]),
        "etf": len([asset for asset in assets if asset.get("kind") == "etf"]),
        "theme": len([asset for asset in assets if asset.get("kind") == "theme"]),
    }
    kind_options = [
        ("", "전체"),
        ("stock", "종목"),
        ("etf", "ETF"),
        ("theme", "테마"),
    ]
    options = "".join(
        f'<option value="{_esc(value)}"{" selected" if value == (kind or "") else ""}>{_esc(label)}</option>'
        for value, label in kind_options
    )
    return _page_shell(
        title="검색 - Research Gateway",
        body=f"""
        <main>
          <section class="asset-hero">
            <span class="eyebrow">Search</span>
            <h1>종목·ETF·테마 검색</h1>
            <p>티커, 이름, 움직인 이유를 기준으로 로컬 콘텐츠를 찾습니다.</p>
            <form class="search-form" method="get" action="/search">
              <input name="q" value="{query_value}" placeholder="예: Apple, AI, 068270, ETF">
              <select name="kind">{options}</select>
              <button>검색</button>
            </form>
            <div class="kind-tabs">{_kind_tabs(current=kind, counts=counts)}</div>
          </section>
          <section>
            <div class="section-head">
              <h2>검색 결과 {len(rows)}개</h2>
              <p>공개 가능한 콘텐츠 스냅샷만 표시합니다.</p>
            </div>
            <div class="asset-grid">{cards}</div>
          </section>
        </main>
        """,
    )


def _learn_html() -> str:
    concepts = [
        ("ETF란 무엇인가", "여러 종목을 한 바구니에 담아 거래하는 상품입니다. 개별 기업보다 구성과 비중을 먼저 봐야 합니다."),
        ("보유 종목 비중", "상위 보유 종목 비중이 높을수록 특정 기업 움직임에 크게 흔들릴 수 있습니다."),
        ("섹터와 테마", "섹터는 산업 분류에 가깝고, 테마는 사건·정책·기술 변화로 묶인 이야기입니다."),
        ("환노출", "해외 ETF나 해외 종목은 주가뿐 아니라 환율 변화도 체감 수익률에 영향을 줍니다."),
        ("밸류체인", "테마를 소재, 부품, 장비, 플랫폼, 완제품 같은 단계로 나눠 보는 지도입니다."),
        ("왜 움직였나", "가격 변화 자체보다 뉴스, 실적, 금리, 환율, 수급 중 어떤 배경이 큰지 구분해야 합니다."),
    ]
    cards = "".join(
        '<article class="concept-card">'
        f'<h2>{_esc(title)}</h2>'
        f'<p>{_esc(body)}</p>'
        '</article>'
        for title, body in concepts
    )
    return _page_shell(
        title="처음 보는 투자 용어 - Research Gateway",
        body=f"""
        <main>
          <section class="lead">
            <span class="eyebrow">Learn</span>
            <h1>ETF와 테마를 처음 보는 사람을 위한 카드</h1>
            <p>종목 추천이 아니라, 콘텐츠를 읽기 전에 알아야 할 기본 개념을 짧게 정리합니다.</p>
          </section>
          <section class="learn-grid">{cards}</section>
        </main>
        """,
    )


def _review_card(asset: dict[str, Any]) -> str:
    review = asset.get("review") or {}
    metrics = review.get("metrics") or {}
    status = review.get("status") or "pending"
    metric_html = (
        '<div class="review-metrics">'
        f'<span><b>{_fmt_pct(metrics.get("return_1d_pct"))}</b><small>1일</small></span>'
        f'<span><b>{_fmt_pct(metrics.get("return_5d_pct"))}</b><small>5일</small></span>'
        f'<span><b>{_fmt_pct(metrics.get("return_20d_pct"))}</b><small>20일</small></span>'
        f'<span><b>{_fmt_ratio(metrics.get("volume_vs_20d_avg"))}</b><small>거래량/20일</small></span>'
        '</div>'
    )
    return (
        '<article class="review-card">'
        '<div class="asset-top">'
        f'<span>{_kind_label(asset.get("kind"))} · {_esc(asset.get("market"))}</span>'
        f'<b>{_esc(status)}</b>'
        '</div>'
        f'<h3><a href="{_asset_href(asset)}">{_esc(asset.get("name"))}</a></h3>'
        f'<p class="ticker">{_esc(asset.get("ticker"))} · {_esc(review.get("published_at"))}</p>'
        f'<p>{_esc(review.get("basis") or "발행 근거 대기")}</p>'
        f'{metric_html}'
        f'<p class="muted">{_esc(review.get("note"))}</p>'
        '</article>'
    )


def _review_html(assets: list[dict[str, Any]]) -> str:
    cards = "".join(_review_card(asset) for asset in assets)
    available = sum(1 for asset in assets if (asset.get("review") or {}).get("status") == "available")
    return _page_shell(
        title="사후 점검 - Research Gateway",
        body=f"""
        <main>
          <section class="lead">
            <span class="eyebrow">Review</span>
            <h1>발행 후 사후 점검</h1>
            <p>콘텐츠를 발행한 뒤 실제 1일/5일/20일 변화와 당시 근거를 함께 남깁니다. 데이터가 없으면 대기 상태로 표시합니다.</p>
          </section>
          <section class="stat-strip">
            <div><b>{len(assets)}</b><span>전체 콘텐츠</span></div>
            <div><b>{available}</b><span>시장 지표 있음</span></div>
            <div><b>{len(assets) - available}</b><span>지표 대기</span></div>
            <div><b>0</b><span>추정 숫자</span></div>
          </section>
          <section>
            <div class="section-head">
              <h2>검증 로그</h2>
              <p>나박AI식 신뢰 레이어: 맞고 틀린 흐름을 이후 데이터로 남깁니다.</p>
            </div>
            <div class="review-grid">{cards}</div>
          </section>
        </main>
        """,
    )


def _composition_html(asset: dict[str, Any]) -> str:
    composition = asset.get("composition") or {}
    if asset.get("kind") == "etf":
        holdings = _bar_rows(composition.get("holdings") or [], limit=10) or '<p class="muted">보유 종목 데이터 대기</p>'
        sectors = _bar_rows(composition.get("sectors") or [], limit=8) or '<p class="muted">섹터 비중 데이터 대기</p>'
        countries = _bar_rows(composition.get("countries") or [], limit=8) or '<p class="muted">국가 비중 데이터 대기</p>'
        return (
            '<div class="detail-grid">'
            f'<section><h2>상위 보유 종목</h2>{holdings}</section>'
            f'<section><h2>섹터 비중</h2>{sectors}</section>'
            f'<section><h2>국가 비중</h2>{countries}</section>'
            '</div>'
        )
    if asset.get("kind") == "theme":
        stages = "".join(
            '<article class="stage-card">'
            f'<h3>{_esc(stage.get("stage") or stage.get("name"))}</h3>'
            f'<p>{_esc(stage.get("description"))}</p>'
            f'<small>국내 {len(stage.get("domestic_names") or [])} · 해외 {len(stage.get("global_names") or [])}</small>'
            '</article>'
            for stage in composition.get("value_chain") or []
        )
        names = _bar_rows(composition.get("domestic_names") or composition.get("global_names") or [], limit=12)
        if not stages:
            stages = '<p class="muted">테마 밸류체인 데이터 대기</p>'
        if not names:
            names = '<p class="muted">대표 종목 데이터 대기</p>'
        return (
            '<div class="detail-grid">'
            f'<section class="wide"><h2>테마 밸류체인</h2><div class="stage-grid">{stages}</div></section>'
            f'<section><h2>대표 종목</h2>{names}</section>'
            '</div>'
        )
    products = _bar_rows(composition.get("business_lines") or composition.get("products") or [], limit=10)
    regions = _bar_rows(composition.get("regions") or [], limit=10)
    peers = _bar_rows(composition.get("peers") or [], limit=10)
    summary = _esc(composition.get("summary") or "구조화 데이터 대기")
    product_rows = products or f'<p class="muted">{summary}</p>'
    region_rows = regions or '<p class="muted">지역 노출 데이터 대기</p>'
    peer_rows = peers or '<p class="muted">비교 대상 데이터 대기</p>'
    return (
        '<div class="detail-grid">'
        f'<section><h2>사업/제품</h2>{product_rows}</section>'
        f'<section><h2>지역 노출</h2>{region_rows}</section>'
        f'<section><h2>비교 대상</h2>{peer_rows}</section>'
        '</div>'
    )


def _metric_tile(label: str, value: str, body: str) -> str:
    return (
        '<article class="metric-tile">'
        f'<span>{_esc(label)}</span>'
        f'<b>{_esc(value)}</b>'
        f'<p>{_esc(body)}</p>'
        '</article>'
    )


def _market_pulse_html(asset: dict[str, Any]) -> str:
    review = asset.get("review") or {}
    metrics = review.get("metrics") or {}
    if not metrics:
        metric_html = '<p class="muted">가격·거래량 지표 대기</p>'
    else:
        metric_html = (
            '<div class="metric-grid">'
            + _metric_tile("1일", _fmt_pct(metrics.get("return_1d_pct")), "발행 후 단기 반응")
            + _metric_tile("5일", _fmt_pct(metrics.get("return_5d_pct")), "내러티브의 초기 지속성")
            + _metric_tile("20일", _fmt_pct(metrics.get("return_20d_pct")), "한 달 안쪽 추적")
            + _metric_tile("거래량", _fmt_ratio(metrics.get("volume_vs_20d_avg")), "20일 평균 대비")
            + '</div>'
        )
    return (
        '<section class="insight-panel">'
        '<div class="section-head tight">'
        '<h2>가격·거래량 스냅샷</h2>'
        f'<p>기준일: {_esc(asset.get("as_of") or "데이터 대기")}</p>'
        '</div>'
        f'{metric_html}'
        '</section>'
    )


def _stock_context_html(asset: dict[str, Any]) -> str:
    composition = asset.get("composition") or {}
    sector = composition.get("sector") or "데이터 대기"
    industry = composition.get("industry") or "데이터 대기"
    products = composition.get("products") or composition.get("business_lines") or []
    regions = composition.get("regions") or []
    peers = composition.get("peers") or []
    return (
        '<section class="insight-panel">'
        '<div class="section-head tight"><h2>종목 읽기 순서</h2><p>기업을 먼저 이해한 뒤 가격 반응을 봅니다.</p></div>'
        '<div class="metric-grid">'
        + _metric_tile("업종", sector, industry)
        + _metric_tile("제품/사업", f"{len(products)}개", "사업·제품 구성 데이터")
        + _metric_tile("지역 노출", f"{len(regions)}개", "매출 지역 또는 시장 노출")
        + _metric_tile("비교 대상", f"{len(peers)}개", "동종 기업 비교 후보")
        + '</div>'
        '</section>'
    )


def _etf_detail_html(asset: dict[str, Any]) -> str:
    composition = asset.get("composition") or {}
    holdings = composition.get("holdings") or []
    sectors = composition.get("sectors") or []
    countries = composition.get("countries") or []
    top_holding = holdings[0] if holdings else {}
    top5 = _sum_weights(holdings, limit=5)
    largest_sector = _largest_weight_row(sectors)
    largest_country = _largest_weight_row(countries)
    concentration = "상위 5개 데이터 대기" if top5 is None else f"상위 5개 {_fmt_weight(top5)}"
    top_name = top_holding.get("name") or top_holding.get("ticker") or "데이터 대기"
    country_name = largest_country.get("name") or "데이터 대기"
    country_weight = _fmt_weight(largest_country.get("weight_pct")) if largest_country else "-"
    sector_name = largest_sector.get("name") or "데이터 대기"
    sector_weight = _fmt_weight(largest_sector.get("weight_pct")) if largest_sector else "-"
    expense = _fmt_weight(composition.get("expense_ratio_pct"))
    return (
        '<section class="insight-panel">'
        '<div class="section-head tight"><h2>ETF 해부</h2><p>처음 보는 ETF는 보유 종목, 집중도, 국가 노출을 먼저 확인합니다.</p></div>'
        '<div class="metric-grid">'
        + _metric_tile("상위 보유", top_name, f"1위 비중 {_fmt_weight(top_holding.get('weight_pct'))}")
        + _metric_tile("집중도", concentration, "상위 종목 쏠림이 클수록 특정 기업 영향이 큽니다.")
        + _metric_tile("주요 섹터", sector_name, f"비중 {sector_weight}")
        + _metric_tile("환율/국가 노출", country_name, f"국가 비중 {country_weight}")
        + _metric_tile("운용사", composition.get("issuer") or "데이터 대기", f"보수 {expense}")
        + _metric_tile("기초지수", composition.get("benchmark") or "데이터 대기", "추종하는 지수 또는 기준")
        + '</div>'
        '</section>'
    )


def _entity_list(rows: list[dict[str, Any]], *, empty: str) -> str:
    if not rows:
        return f'<p class="muted">{_esc(empty)}</p>'
    return "".join(
        '<li>'
        f'<b>{_esc(row.get("name") or row.get("ticker"))}</b>'
        f'<span>{_esc(row.get("ticker") or "-")} · {_esc(row.get("role") or row.get("market") or "역할 대기")}</span>'
        '</li>'
        for row in rows[:8]
    )


def _event_list(rows: list[dict[str, Any]], *, empty: str) -> str:
    if not rows:
        return f'<li><b>대기</b><span>{_esc(empty)}</span></li>'
    return "".join(
        '<li>'
        f'<b>{_esc(row.get("name") or "이벤트")}</b>'
        f'<span>{_esc(row.get("description") or "설명 대기")}</span>'
        '</li>'
        for row in rows[:8]
    )


def _theme_detail_html(asset: dict[str, Any]) -> str:
    composition = asset.get("composition") or {}
    domestic = composition.get("domestic_names") or []
    global_names = composition.get("global_names") or []
    catalysts = composition.get("catalysts") or []
    risks = composition.get("risks") or []
    return (
        '<section class="insight-panel">'
        '<div class="section-head tight"><h2>국내·해외 연결 지도</h2><p>테마는 국내 종목만 보지 말고 해외 선도 기업과 같이 봅니다.</p></div>'
        '<div class="compare-grid">'
        '<article><h3>국내 대표 종목</h3><ul class="entity-list">'
        f'{_entity_list(domestic, empty="국내 대표 종목 대기")}'
        '</ul></article>'
        '<article><h3>해외 대표 종목</h3><ul class="entity-list">'
        f'{_entity_list(global_names, empty="해외 대표 종목 대기")}'
        '</ul></article>'
        '<article><h3>촉매와 리스크</h3><ul class="entity-list">'
        f'{_event_list(catalysts, empty="촉매 데이터 대기")}'
        f'{_event_list(risks, empty="리스크 데이터 대기")}'
        '</ul></article>'
        '</div>'
        '</section>'
    )


def _kind_detail_html(asset: dict[str, Any]) -> str:
    if asset.get("kind") == "etf":
        return _etf_detail_html(asset)
    if asset.get("kind") == "theme":
        return _theme_detail_html(asset)
    return _stock_context_html(asset)


def _visual_board_html(asset: dict[str, Any]) -> str:
    visuals = asset.get("visuals") or []
    if not visuals:
        rows = '<p class="muted">시각화 데이터 대기</p>'
    else:
        rows = "".join(
            '<article class="visual-tile">'
            f'<span>{_esc(visual.get("status") or "missing")}</span>'
            f'<b>{_esc(visual.get("title") or visual.get("id"))}</b>'
            f'<p>{_esc(", ".join(visual.get("data_required") or []) or visual.get("type") or "데이터 요구사항 대기")}</p>'
            '</article>'
            for visual in visuals[:8]
        )
    return (
        '<section class="insight-panel">'
        '<div class="section-head tight"><h2>시각화 보드</h2><p>차트가 준비됐는지, 어떤 데이터가 더 필요한지 분리해서 표시합니다.</p></div>'
        f'<div class="visual-grid">{rows}</div>'
        '</section>'
    )


def _points_html(title: str, rows: list[str]) -> str:
    if not rows:
        return f'<section><h2>{_esc(title)}</h2><p class="muted">데이터 대기</p></section>'
    return (
        f'<section><h2>{_esc(title)}</h2>'
        '<ul class="point-list">'
        + "".join(f'<li>{_esc(row)}</li>' for row in rows)
        + '</ul></section>'
    )


def _trust_panel(asset: dict[str, Any]) -> str:
    visuals = asset.get("visuals") or []
    ready = sum(1 for visual in visuals if visual.get("status") == "ready")
    source_rows = "".join(
        '<li>'
        f'<b>{_esc(source.get("kind"))}</b>'
        f'<span>{_esc(source.get("label"))}</span>'
        '</li>'
        for source in asset.get("sources") or []
    )
    visual_rows = "".join(
        '<li>'
        f'<b>{_esc(visual.get("title") or visual.get("id"))}</b>'
        f'<span>{_esc(visual.get("status"))}</span>'
        '</li>'
        for visual in visuals[:8]
    )
    return (
        '<section class="trust-panel">'
        '<div>'
        '<h2>데이터 신뢰</h2>'
        '<p>원천 데이터, 구조화 프로필, 시각화 준비 상태를 분리해서 표시합니다.</p>'
        '</div>'
        '<div class="trust-grid">'
        '<article><h3>출처</h3><ul class="trust-list">'
        f'{source_rows or "<li><b>content</b><span>local_content_snapshot</span></li>"}'
        '</ul></article>'
        '<article><h3>시각화 상태</h3>'
        f'<p class="trust-score">{ready} / {len(visuals)}</p>'
        f'<ul class="trust-list">{visual_rows}</ul>'
        '</article>'
        '<article><h3>발행 상태</h3>'
        f'<p class="trust-score">{_esc(asset.get("publish_status"))}</p>'
        f'<p class="muted">기준일: {_esc(asset.get("as_of") or "데이터 대기")}</p>'
        '</article>'
        '</div>'
        '</section>'
    )


def _asset_html(asset: dict[str, Any]) -> str:
    return _page_shell(
        title=f"{asset.get('name')} - Research Gateway",
        body=f"""
        <main>
          <section class="asset-hero">
            <a class="back" href="/">← 홈</a>
            <span class="eyebrow">{_kind_label(asset.get("kind"))} · {_esc(asset.get("market"))}</span>
            <h1>{_esc(asset.get("name"))}</h1>
            <p class="ticker">{_esc(asset.get("ticker"))}</p>
            <p>{_esc((asset.get("one_liner") or {}).get("summary"))}</p>
            <div class="sources">{_source_badges(asset)}</div>
          </section>
          <section class="why-detail">
            <h2>왜 움직였나</h2>
            <p>{_esc((asset.get("why_moved") or {}).get("summary"))}</p>
          </section>
          {_market_pulse_html(asset)}
          {_kind_detail_html(asset)}
          {_trust_panel(asset)}
          {_composition_html(asset)}
          {_visual_board_html(asset)}
          <div class="detail-grid">
            {_points_html("상승 관점", asset.get("bull_points") or [])}
            {_points_html("주의 관점", asset.get("bear_points") or [])}
            {_points_html("리스크", asset.get("risk_points") or [])}
            {_points_html("다음 관찰", asset.get("watch_points") or [])}
          </div>
        </main>
        """,
    )


def _page_shell(*, title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <style>
    :root {{
      --paper:#f6f3eb; --ink:#18212b; --muted:#667085; --line:#d7d1c3; --panel:#fffdfa;
      --green:#1f7a5a; --blue:#245f8f; --orange:#d97925; --red:#b42318;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    a {{ color:inherit; text-decoration:none; }}
    header {{ position:sticky; top:0; z-index:5; background:rgba(255,253,250,.96); border-bottom:1px solid var(--line); padding:13px clamp(16px,4vw,44px); display:flex; gap:18px; align-items:center; }}
    .brand {{ font-weight:800; letter-spacing:0; }}
    nav {{ margin-left:auto; display:flex; gap:12px; color:var(--muted); font-size:14px; }}
    main {{ padding:18px clamp(16px,4vw,44px) 44px; }}
    .home-hero {{ display:grid; grid-template-columns:minmax(0,1.35fr) minmax(300px,.65fr); gap:12px; align-items:stretch; }}
    .lead,.asset-hero,.why-detail,.insight-panel,section.detail-grid > section,.detail-grid > section,.empty {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:18px; }}
    .lead {{ min-height:230px; display:grid; align-content:center; border-left:5px solid var(--orange); }}
    .quick-panel {{ background:var(--ink); color:#fff; border-radius:8px; padding:18px; display:grid; align-content:center; }}
    .quick-panel h2 {{ color:#fff; font-size:22px; }}
    .quick-panel p,.quick-panel .eyebrow {{ color:#c8d0d9; }}
    .quick-panel .text-link {{ color:#fff; border-bottom:1px solid rgba(255,255,255,.45); width:max-content; font-weight:700; }}
    h1,h2,h3,p {{ margin-top:0; }}
    h1 {{ font-size:clamp(28px,4vw,44px); line-height:1.1; margin-bottom:10px; letter-spacing:0; }}
    h2 {{ font-size:18px; letter-spacing:0; margin-bottom:8px; }}
    h3 {{ font-size:15px; letter-spacing:0; margin-bottom:6px; }}
    p {{ color:#2d3a47; }}
    .eyebrow,.asset-top span {{ color:var(--blue); font-size:12px; font-weight:800; text-transform:uppercase; letter-spacing:0; }}
    .primary {{ width:max-content; background:var(--ink); color:#fff; border-radius:6px; padding:9px 12px; font-weight:700; }}
    .stat-strip {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:12px 0 24px; }}
    .stat-strip div {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:13px; }}
    .stat-strip b {{ display:block; font-size:25px; }}
    .stat-strip span,.muted,.ticker {{ color:var(--muted); }}
    .section-head {{ display:flex; align-items:end; justify-content:space-between; gap:16px; margin:18px 0 10px; }}
    .section-head p {{ margin:0; color:var(--muted); }}
    .section-head.tight {{ margin:0 0 12px; }}
    .lane-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }}
    .lane-card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; min-height:142px; display:grid; align-content:start; transition:transform .16s ease,border-color .16s ease; }}
    .lane-card:hover,.theme-node:hover,.asset-card:hover,.shelf-card:hover,.narrative-row:hover,.review-row:hover {{ transform:translateY(-1px); border-color:#b9ad98; }}
    .lane-card span {{ color:var(--orange); font-size:12px; font-weight:800; }}
    .lane-card b {{ display:block; margin:5px 0 6px; font-size:17px; }}
    .lane-card p {{ margin:0; color:var(--muted); font-size:13px; }}
    .kind-tabs {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }}
    .kind-tab {{ border:1px solid var(--line); background:#fff; border-radius:999px; padding:7px 10px; display:inline-flex; align-items:center; gap:7px; color:var(--muted); font-weight:700; }}
    .kind-tab b {{ color:var(--ink); font-size:12px; }}
    .kind-tab.active {{ border-color:var(--ink); background:var(--ink); color:#fff; }}
    .kind-tab.active b {{ color:#fff; }}
    .quick-panel .kind-tab {{ background:rgba(255,255,255,.08); color:#fff; border-color:rgba(255,255,255,.24); }}
    .quick-panel .kind-tab b {{ color:#fff; }}
    .compact-tabs {{ margin:10px 0 12px; }}
    .theme-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:10px; }}
    .theme-node {{ display:block; background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:13px; }}
    .theme-node b {{ display:block; margin-bottom:5px; }}
    .theme-node span {{ color:var(--muted); font-size:13px; }}
    .asset-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(290px,1fr)); gap:12px; }}
    .asset-card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; min-width:0; }}
    .asset-card h3 {{ font-size:18px; margin:4px 0 0; }}
    .asset-card p {{ overflow-wrap:anywhere; }}
    .asset-top {{ display:flex; justify-content:space-between; gap:10px; }}
    .asset-top b {{ color:var(--green); font-size:12px; }}
    .why {{ border-top:1px solid var(--line); padding-top:10px; margin-top:10px; }}
    .why strong {{ display:block; margin-bottom:4px; }}
    .mini-visual {{ border-top:1px solid var(--line); margin-top:10px; padding-top:10px; }}
    .bar-row {{ display:grid; grid-template-columns:1fr auto; gap:10px; align-items:center; position:relative; padding-bottom:9px; margin:8px 0; }}
    .bar-row span {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .bar-row b {{ color:var(--muted); font-size:12px; }}
    .bar-row i {{ position:absolute; left:0; bottom:0; height:4px; border-radius:999px; background:linear-gradient(90deg,var(--orange),var(--blue)); }}
    .stage-chip,.stage-card {{ border:1px solid var(--line); border-radius:7px; padding:9px; background:#fbf7ef; }}
    .stage-chip b,.stage-card h3 {{ display:block; }}
    .stage-chip span,.stage-card small {{ color:var(--muted); font-size:12px; }}
    .sources {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }}
    .source {{ border:1px solid var(--line); background:#f9fafb; border-radius:999px; padding:4px 8px; color:var(--muted); font-size:12px; }}
    .asset-hero {{ border-left:5px solid var(--blue); }}
    .back {{ display:inline-block; color:var(--muted); margin-bottom:12px; }}
    .why-detail {{ margin:12px 0; }}
    .insight-panel {{ margin:12px 0; }}
    .metric-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; }}
    .metric-tile {{ border:1px solid var(--line); border-radius:8px; padding:12px; background:#fbf7ef; min-width:0; }}
    .metric-tile span {{ display:block; color:var(--muted); font-size:12px; font-weight:800; }}
    .metric-tile b {{ display:block; font-size:18px; margin:3px 0 5px; overflow-wrap:anywhere; }}
    .metric-tile p {{ margin:0; color:var(--muted); font-size:13px; }}
    .detail-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px; margin-top:12px; }}
    .wide {{ grid-column:1/-1; }}
    .stage-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; }}
    .compare-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; }}
    .compare-grid article {{ border-top:1px solid var(--line); padding-top:10px; }}
    .entity-list {{ list-style:none; padding:0; margin:0; display:grid; gap:8px; }}
    .entity-list li {{ border-bottom:1px solid var(--line); padding-bottom:8px; display:grid; gap:2px; }}
    .entity-list span {{ color:var(--muted); font-size:13px; }}
    .visual-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:10px; }}
    .visual-tile {{ border:1px solid var(--line); border-radius:8px; padding:11px; background:#fff; }}
    .visual-tile span {{ color:var(--green); font-weight:800; font-size:12px; }}
    .visual-tile b {{ display:block; margin:4px 0; }}
    .visual-tile p {{ margin:0; color:var(--muted); font-size:13px; }}
    .point-list {{ margin:0; padding-left:18px; color:#2d3a47; }}
    .point-list li {{ margin:5px 0; }}
    .search-form {{ display:grid; grid-template-columns:minmax(0,1fr) 150px auto; gap:8px; margin-top:14px; }}
    .search-form.compact {{ grid-template-columns:minmax(0,1fr) auto; }}
    .search-form input,.search-form select {{ width:100%; border:1px solid var(--line); border-radius:6px; background:#fff; padding:10px; font:inherit; }}
    .search-form button {{ border:0; border-radius:6px; background:var(--ink); color:#fff; padding:10px 13px; font:inherit; font-weight:700; }}
    .quick-panel .search-form button {{ background:var(--orange); color:#111; }}
    .shelf-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px; }}
    .shelf-card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }}
    .narrative-list {{ display:grid; gap:8px; }}
    .narrative-row,.review-row {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; display:grid; grid-template-columns:90px minmax(150px,.6fr) minmax(240px,1fr); gap:12px; align-items:start; }}
    .narrative-row span {{ color:var(--blue); font-weight:800; font-size:12px; }}
    .narrative-row p {{ margin:0; color:var(--muted); }}
    .review-list {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:8px; }}
    .review-row {{ grid-template-columns:1fr auto; align-items:center; }}
    .review-row span {{ color:var(--muted); font-weight:800; }}
    .learn-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; margin-top:12px; }}
    .concept-card,.trust-panel,.review-card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:18px; }}
    .review-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:12px; }}
    .review-metrics {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin:12px 0; }}
    .review-metrics span {{ border:1px solid var(--line); border-radius:7px; padding:8px; background:#fbf7ef; }}
    .review-metrics b {{ display:block; font-size:17px; }}
    .review-metrics small {{ color:var(--muted); }}
    .trust-panel {{ margin:12px 0; }}
    .trust-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }}
    .trust-grid article {{ border-top:1px solid var(--line); padding-top:10px; }}
    .trust-list {{ list-style:none; margin:0; padding:0; display:grid; gap:7px; }}
    .trust-list li {{ display:flex; justify-content:space-between; gap:10px; border-bottom:1px solid var(--line); padding-bottom:7px; }}
    .trust-list span {{ color:var(--muted); text-align:right; }}
    .trust-score {{ font-size:24px; font-weight:800; color:var(--blue); margin-bottom:8px; }}
    @media (max-width:760px) {{
      header {{ align-items:flex-start; flex-direction:column; }}
      nav {{ margin-left:0; flex-wrap:wrap; }}
      .home-hero,.lane-grid {{ grid-template-columns:1fr; }}
      .stat-strip {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
      .section-head {{ display:block; }}
      .search-form {{ grid-template-columns:1fr; }}
      .search-form.compact {{ grid-template-columns:1fr; }}
      .narrative-row {{ grid-template-columns:1fr; }}
      .review-metrics {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
    }}
  </style>
</head>
<body>
  <header>
    <a class="brand" href="/">Research Gateway</a>
    <nav>
      <a href="/">오늘의 흐름</a>
      <a href="/search?kind=theme">섹터·테마</a>
      <a href="/search?kind=stock">종목 탐색</a>
      <a href="/search?kind=etf">ETF 구성</a>
      <a href="/review">사후 점검</a>
      <a href="/learn">처음 보는 ETF·테마</a>
    </nav>
  </header>
  {body}
</body>
</html>"""


def load_public_assets(config: ServiceApiConfig) -> list[dict[str, Any]]:
    """Load all public service assets."""
    return load_assets(config.asset_dirs)


def _status_counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _source_health(review: dict[str, Any]) -> dict[str, Any]:
    summary = review.get("summary") or {}
    statuses = summary.get("statuses") or {}
    return {
        "status": summary.get("status") or "missing",
        "rows": summary.get("rows", 0),
        "ready_inputs": statuses.get("ready_input", 0),
        "errors": summary.get("errors", 0),
        "warnings": summary.get("warnings", 0),
        "issue_codes": summary.get("issue_codes") or {},
    }


def _collection_status(paths: tuple[Path, ...]) -> dict[str, Any]:
    pipelines = []
    totals = {
        "reports": 0,
        "publish_ready": 0,
        "market_snapshots_attached": 0,
        "price_trend_ready": 0,
        "volume_change_ready": 0,
    }
    warnings: dict[str, int] = {}
    for path in paths:
        payload = _read_json(path)
        summary = payload.get("summary") or {}
        name = path.parent.name.replace("_", " ")
        pipeline = {
            "name": name,
            "reports": summary.get("reports", 0),
            "publish_ready": summary.get("publish_ready", 0),
            "publish_ready_pct": summary.get("publish_ready_pct", 0),
            "market_snapshots_attached": summary.get("market_snapshots_attached", 0),
            "price_trend_ready": summary.get("price_trend_ready", 0),
            "volume_change_ready": summary.get("volume_change_ready", 0),
            "warnings": summary.get("warnings") or {},
        }
        pipelines.append(pipeline)
        for key in totals:
            totals[key] += int(summary.get(key, 0) or 0)
        for code, count in (summary.get("warnings") or {}).items():
            warnings[str(code)] = warnings.get(str(code), 0) + int(count or 0)
    status = "pass" if totals["reports"] and totals["reports"] == totals["publish_ready"] else "watch"
    if not pipelines:
        status = "missing"
    return {
        "status": status,
        "totals": totals,
        "warnings": warnings,
        "pipelines": pipelines,
    }


def _cost_guard_status(queue: dict[str, Any], gap: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    aggregate = assessment.get("aggregate") or {}
    coverage = aggregate.get("coverage") or {}
    verdict = assessment.get("verdict") or {}
    cost_statuses = coverage.get("cost_statuses") or {}
    if cost_statuses:
        status = "pass" if set(cost_statuses.keys()) == {"pass"} else "watch"
    else:
        status = "unknown"
    ready_shortfall = (gap.get("summary") or {}).get("ready_shortfall", 0)
    target = queue.get("target_candidates")
    ready = (queue.get("summary") or {}).get("ready_for_local_pilot", 0)
    twelve_month = verdict.get("twelve_month_validation") or {}
    return {
        "status": status,
        "llm_policy": assessment.get("llm_policy") or queue.get("llm_policy") or "local-only policy missing",
        "cost_statuses": cost_statuses,
        "paid_model_allowed": bool(target and ready >= target and status == "pass"),
        "ready_shortfall": ready_shortfall,
        "twelve_month_required_now": bool(twelve_month.get("required_now")),
        "twelve_month_judgment": twelve_month.get("judgment"),
    }


def _publish_status(assets: list[dict[str, Any]]) -> dict[str, Any]:
    ready = [asset for asset in assets if asset.get("publish_status") == "ready"]
    reviews = [asset for asset in assets if (asset.get("review") or {}).get("status") == "available"]
    return {
        "status": "ready" if ready else "empty",
        "public_assets": len(assets),
        "publish_ready_assets": len(ready),
        "review_available_assets": len(reviews),
        "by_kind": _status_counts(assets, "kind"),
        "by_market": _status_counts(assets, "market"),
    }


def load_ops_status(config: ServiceApiConfig) -> dict[str, Any]:
    """Load ops status for the Cloudflare-like console surface."""
    queue = _read_json(config.candidate_queue_path)
    gap = _read_json(config.candidate_gap_path)
    review = _read_json(config.candidate_review_path)
    assessment = _read_json(config.assessment_path)
    assets = load_public_assets(config)
    queue_summary = queue.get("summary") or {}
    gap_summary = gap.get("summary") or {}
    verdict = assessment.get("verdict") or {}
    return {
        "schema_version": 1,
        "artifact": "service_ops_status",
        "status": verdict.get("status") or "unknown",
        "recommendation": verdict.get("recommendation"),
        "ready_candidates": queue_summary.get("ready_for_local_pilot", 0),
        "target_candidates": queue.get("target_candidates"),
        "ready_shortfall": gap_summary.get("ready_shortfall", 0),
        "queue_status": (queue.get("gate") or {}).get("status") or "missing",
        "gap_status": gap.get("status") or "missing",
        "markets": queue_summary.get("markets") or {},
        "content_types": queue_summary.get("content_types") or {},
        "source_health": _source_health(review),
        "collection": _collection_status(config.content_summary_paths),
        "cost_guard": _cost_guard_status(queue, gap, assessment),
        "publish": _publish_status(assets),
    }


def _ops_metric(label: str, value: Any, status: str | None = None) -> str:
    tone = f" {status}" if status else ""
    return (
        f'<article class="ops-metric{tone}">'
        f'<span>{_esc(label)}</span>'
        f'<b>{_esc(value)}</b>'
        '</article>'
    )


def _ops_bar_map(title: str, values: dict[str, Any]) -> str:
    if not values:
        return f'<section class="ops-panel"><h2>{_esc(title)}</h2><p class="muted">데이터 대기</p></section>'
    max_value = max([float(value or 0) for value in values.values()] or [1]) or 1
    rows = []
    for key, value in sorted(values.items()):
        try:
            width = max(5, min(100, float(value) / max_value * 100))
        except (TypeError, ValueError):
            width = 5
        rows.append(
            '<div class="ops-bar">'
            f'<span>{_esc(key)}</span><b>{_esc(value)}</b>'
            f'<i style="width:{width:.2f}%"></i>'
            '</div>'
        )
    return f'<section class="ops-panel"><h2>{_esc(title)}</h2>{"".join(rows)}</section>'


def _ops_tone(status: Any) -> str:
    value = str(status or "").lower()
    if value in {"pass", "ready", "ok", "available"}:
        return "ok"
    if value in {"fail", "failed", "blocked", "error", "bad"}:
        return "bad"
    if value in {"watch", "warning", "locked", "missing", "unknown"}:
        return "watch"
    return "watch"


def _ops_pill(label: str, value: Any, status: Any = None) -> str:
    tone = _ops_tone(status if status is not None else value)
    return (
        f'<span class="ops-pill {tone}">'
        f'<b>{_esc(label)}</b>'
        f'<i>{_esc(value)}</i>'
        '</span>'
    )


def _ops_status_panel(status: dict[str, Any]) -> str:
    source = status.get("source_health") or {}
    cost = status.get("cost_guard") or {}
    publish = status.get("publish") or {}
    collection = status.get("collection") or {}
    return (
        '<section class="ops-panel">'
        '<h2>Service Health</h2>'
        '<div class="ops-pill-grid">'
        f'{_ops_pill("sources", source.get("status"), source.get("status"))}'
        f'{_ops_pill("collection", collection.get("status"), collection.get("status"))}'
        f'{_ops_pill("cost", cost.get("status"), cost.get("status"))}'
        f'{_ops_pill("publish", publish.get("status"), publish.get("status"))}'
        '</div>'
        f'<p class="muted">{_esc(status.get("recommendation") or "운영 판단 대기")}</p>'
        '</section>'
    )


def _ops_collection_panel(status: dict[str, Any]) -> str:
    collection = status.get("collection") or {}
    totals = collection.get("totals") or {}
    rows = "".join(
        '<li>'
        f'<b>{_esc(row.get("name"))}</b>'
        f'<span>{_esc(row.get("publish_ready"))} / {_esc(row.get("reports"))} ready · '
        f'price {_esc(row.get("price_trend_ready"))} · volume {_esc(row.get("volume_change_ready"))}</span>'
        '</li>'
        for row in collection.get("pipelines") or []
    )
    warnings = collection.get("warnings") or {}
    warning_text = ", ".join(f"{key}: {value}" for key, value in warnings.items()) or "warnings 없음"
    return (
        '<section class="ops-panel">'
        '<h2>Collection Workers</h2>'
        '<div class="ops-pill-grid">'
        f'{_ops_pill("reports", totals.get("reports", 0), collection.get("status"))}'
        f'{_ops_pill("publish ready", totals.get("publish_ready", 0), collection.get("status"))}'
        f'{_ops_pill("market snapshots", totals.get("market_snapshots_attached", 0), collection.get("status"))}'
        '</div>'
        f'<ul class="ops-list">{rows or "<li><b>대기</b><span>collection summary 없음</span></li>"}</ul>'
        f'<p class="muted">{_esc(warning_text)}</p>'
        '</section>'
    )


def _ops_cost_panel(status: dict[str, Any]) -> str:
    cost = status.get("cost_guard") or {}
    allowed = "allowed" if cost.get("paid_model_allowed") else "locked"
    return (
        '<section class="ops-panel">'
        '<h2>Cost Guard</h2>'
        '<div class="ops-pill-grid">'
        f'{_ops_pill("local mode", cost.get("status"), cost.get("status"))}'
        f'{_ops_pill("paid model", allowed, "pass" if cost.get("paid_model_allowed") else "watch")}'
        f'{_ops_pill("shortfall", cost.get("ready_shortfall", 0), "watch" if cost.get("ready_shortfall") else "pass")}'
        f'{_ops_pill("12m validation", "not now" if not cost.get("twelve_month_required_now") else "required", "pass" if not cost.get("twelve_month_required_now") else "watch")}'
        '</div>'
        f'<p class="muted">{_esc(cost.get("llm_policy"))}</p>'
        '</section>'
    )


def _ops_publish_panel(status: dict[str, Any]) -> str:
    publish = status.get("publish") or {}
    by_kind = publish.get("by_kind") or {}
    max_value = max([int(value or 0) for value in by_kind.values()] or [1]) or 1
    kind_rows = "".join(
        '<div class="ops-bar compact">'
        f'<span>{_kind_label(key)}</span><b>{_esc(value)}</b>'
        f'<i style="width:{max(5, min(100, int(value or 0) / max_value * 100)):.2f}%"></i>'
        '</div>'
        for key, value in sorted(by_kind.items())
    )
    kind_chart = kind_rows or '<p class="muted">발행 asset 대기</p>'
    return (
        '<section class="ops-panel">'
        '<h2>Publish Gate</h2>'
        '<div class="ops-pill-grid">'
        f'{_ops_pill("public assets", publish.get("public_assets", 0), publish.get("status"))}'
        f'{_ops_pill("ready", publish.get("publish_ready_assets", 0), publish.get("status"))}'
        f'{_ops_pill("review data", publish.get("review_available_assets", 0), publish.get("status"))}'
        '</div>'
        f'<div class="ops-subchart"><h3>Publish by Kind</h3>{kind_chart}</div>'
        '</section>'
    )


def _ops_source_panel(status: dict[str, Any]) -> str:
    source = status.get("source_health") or {}
    issues = source.get("issue_codes") or {}
    issue_text = ", ".join(f"{key}: {value}" for key, value in issues.items()) or "issue 없음"
    return (
        '<section class="ops-panel">'
        '<h2>Source Intake</h2>'
        '<div class="ops-pill-grid">'
        f'{_ops_pill("status", source.get("status"), source.get("status"))}'
        f'{_ops_pill("ready inputs", source.get("ready_inputs", 0), source.get("status"))}'
        f'{_ops_pill("errors", source.get("errors", 0), "bad" if source.get("errors") else "pass")}'
        f'{_ops_pill("warnings", source.get("warnings", 0), "watch" if source.get("warnings") else "pass")}'
        '</div>'
        f'<p class="muted">{_esc(issue_text)}</p>'
        '</section>'
    )


def _ops_html(config: ServiceApiConfig) -> str:
    status = load_ops_status(config)
    queue = _read_json(config.candidate_queue_path)
    gap = _read_json(config.candidate_gap_path)
    rows = queue.get("rows") or []
    slots = gap.get("slot_plan") or []
    candidate_rows = "".join(
        '<tr>'
        f'<td><b>{_esc(row.get("ticker"))}</b><small>{_esc(row.get("name"))}</small></td>'
        f'<td>{_kind_label(row.get("content_type"))}</td>'
        f'<td>{_esc(row.get("market"))}</td>'
        f'<td><span class="ops-badge">{_esc(row.get("status"))}</span></td>'
        f'<td>{_esc(", ".join(row.get("missing_inputs") or []))}</td>'
        '</tr>'
        for row in rows[:18]
    )
    slot_rows = "".join(
        '<li>'
        f'<b>{_esc(slot.get("preferred_market"))} {_kind_label(slot.get("preferred_content_type"))}</b>'
        f'<span>{_esc(slot.get("required_input"))}</span>'
        '</li>'
        for slot in slots[:12]
    )
    return _ops_shell(
        title="Research Gateway Ops",
        body=f"""
        <main class="ops-main">
          <section class="ops-hero">
            <div>
              <span class="ops-eyebrow">Operations</span>
              <h1>Research Gateway Ops</h1>
              <p>공개 서비스에 내보내기 전 후보, 데이터, 비용 상태를 분리해서 점검합니다.</p>
            </div>
            <div class="ops-actions">
              <a href="/api/ops/status">status json</a>
              <a href="/api/assets">public assets</a>
              <a href="/">public service</a>
            </div>
          </section>
          <section class="ops-metrics">
            {_ops_metric("status", status.get("status"), "watch")}
            {_ops_metric("ready", f"{status.get('ready_candidates')} / {status.get('target_candidates')}", "ok")}
            {_ops_metric("shortfall", status.get("ready_shortfall"), "watch")}
            {_ops_metric("queue", status.get("queue_status"), "watch")}
            {_ops_metric("gap", status.get("gap_status"), "watch")}
          </section>
          <section class="ops-grid">
            {_ops_status_panel(status)}
            {_ops_cost_panel(status)}
          </section>
          <section class="ops-grid">
            {_ops_source_panel(status)}
            {_ops_collection_panel(status)}
          </section>
          <section class="ops-grid">
            {_ops_publish_panel(status)}
            {_ops_bar_map("Public Markets", (status.get("publish") or {}).get("by_market") or {})}
          </section>
          <section class="ops-grid">
            {_ops_bar_map("Market Coverage", status.get("markets") or {})}
            {_ops_bar_map("Content Types", status.get("content_types") or {})}
          </section>
          <section class="ops-grid large">
            <div class="ops-panel">
              <h2>Candidate Queue</h2>
              <div class="ops-table-wrap">
                <table>
                  <thead><tr><th>Asset</th><th>Type</th><th>Market</th><th>Status</th><th>Missing</th></tr></thead>
                  <tbody>{candidate_rows or '<tr><td colspan="5">후보 큐 데이터 대기</td></tr>'}</tbody>
                </table>
              </div>
            </div>
            <div class="ops-panel">
              <h2>Next Slots</h2>
              <ul class="slot-list">{slot_rows or '<li><b>대기</b><span>candidate_gap 데이터 없음</span></li>'}</ul>
            </div>
          </section>
        </main>
        """,
    )


def _ops_shell(*, title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <style>
    :root {{
      --bg:#f7f9fc; --panel:#ffffff; --ink:#111827; --muted:#667085; --line:#d8dee8;
      --nav:#101820; --nav2:#182331; --orange:#f38020; --green:#15803d; --amber:#9a6700; --red:#b42318;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    a {{ color:inherit; text-decoration:none; }}
    .ops-shell {{ min-height:100vh; display:grid; grid-template-columns:230px 1fr; }}
    aside {{ background:var(--nav); color:#cbd5e1; padding:16px 12px; }}
    .ops-brand {{ display:flex; align-items:center; gap:9px; padding:8px 8px 16px; border-bottom:1px solid rgba(255,255,255,.12); }}
    .ops-mark {{ width:30px; height:30px; border-radius:6px; background:var(--orange); color:#111; display:grid; place-items:center; font-weight:900; }}
    .ops-brand b {{ display:block; color:#fff; }}
    .ops-brand span {{ display:block; color:#8fa1b3; font-size:11px; }}
    nav {{ display:grid; gap:5px; margin-top:14px; }}
    nav a {{ display:flex; justify-content:space-between; padding:9px 10px; border-radius:6px; }}
    nav a.active, nav a:hover {{ background:var(--nav2); color:#fff; }}
    .ops-main {{ padding:20px clamp(16px,3vw,36px) 42px; min-width:0; }}
    .ops-hero {{ display:flex; justify-content:space-between; gap:16px; background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:18px; }}
    .ops-eyebrow {{ color:var(--orange); font-size:12px; font-weight:800; text-transform:uppercase; }}
    h1,h2,p {{ margin-top:0; }}
    h1 {{ font-size:30px; margin-bottom:6px; }}
    h2 {{ font-size:16px; margin-bottom:10px; }}
    h3 {{ font-size:13px; margin:12px 0 8px; color:var(--muted); }}
    p,.muted {{ color:var(--muted); }}
    .ops-actions {{ display:flex; flex-wrap:wrap; gap:8px; align-content:flex-start; }}
    .ops-actions a {{ border:1px solid var(--line); background:#fbfcfe; border-radius:6px; padding:8px 10px; }}
    .ops-metrics {{ display:grid; grid-template-columns:repeat(5,minmax(120px,1fr)); gap:10px; margin:12px 0; }}
    .ops-metric,.ops-panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:13px; }}
    .ops-metric span {{ display:block; color:var(--muted); font-size:12px; }}
    .ops-metric b {{ display:block; font-size:20px; margin-top:4px; overflow-wrap:anywhere; }}
    .ops-metric.ok b {{ color:var(--green); }}
    .ops-metric.watch b {{ color:var(--amber); }}
    .ops-metric.bad b {{ color:var(--red); }}
    .ops-pill-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:8px; margin-bottom:10px; }}
    .ops-pill {{ border:1px solid var(--line); border-radius:8px; background:#f8fafc; padding:9px; display:grid; gap:2px; }}
    .ops-pill b {{ color:var(--muted); font-size:11px; text-transform:uppercase; }}
    .ops-pill i {{ font-style:normal; font-weight:800; overflow-wrap:anywhere; }}
    .ops-pill.ok i {{ color:var(--green); }}
    .ops-pill.watch i {{ color:var(--amber); }}
    .ops-pill.bad i {{ color:var(--red); }}
    .ops-list {{ list-style:none; padding:0; margin:10px 0 0; display:grid; gap:8px; }}
    .ops-list li {{ border-top:1px solid var(--line); padding-top:8px; display:flex; justify-content:space-between; gap:12px; }}
    .ops-list span {{ color:var(--muted); text-align:right; }}
    .ops-subchart {{ border-top:1px solid var(--line); margin-top:10px; padding-top:4px; }}
    .ops-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px; }}
    .ops-grid.large {{ grid-template-columns:minmax(0,1.45fr) minmax(260px,.55fr); }}
    .ops-bar {{ display:grid; grid-template-columns:1fr auto; gap:10px; position:relative; padding-bottom:10px; margin:8px 0; }}
    .ops-bar span {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .ops-bar b {{ color:var(--muted); }}
    .ops-bar i {{ position:absolute; left:0; bottom:0; height:4px; border-radius:999px; background:linear-gradient(90deg,var(--orange),#2563eb); }}
    .ops-bar.compact {{ margin:6px 0; }}
    .ops-table-wrap {{ overflow-x:auto; }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{ border-bottom:1px solid var(--line); padding:8px 7px; text-align:left; vertical-align:top; }}
    th {{ color:var(--muted); font-size:12px; }}
    td small {{ display:block; color:var(--muted); }}
    .ops-badge {{ display:inline-flex; border:1px solid var(--line); border-radius:999px; padding:3px 8px; font-size:12px; background:#f8fafc; }}
    .slot-list {{ list-style:none; padding:0; margin:0; display:grid; gap:8px; }}
    .slot-list li {{ border:1px solid var(--line); border-radius:7px; padding:9px; display:flex; justify-content:space-between; gap:10px; }}
    .slot-list span {{ color:var(--muted); text-align:right; }}
    @media (max-width:900px) {{
      .ops-shell {{ grid-template-columns:1fr; }}
      .ops-hero,.ops-grid,.ops-grid.large {{ display:block; }}
      .ops-panel {{ margin-top:12px; }}
      .ops-metrics {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
    }}
  </style>
</head>
<body>
  <div class="ops-shell">
    <aside>
      <div class="ops-brand"><div class="ops-mark">RG</div><div><b>Gateway Ops</b><span>control plane</span></div></div>
      <nav>
        <a class="active" href="/ops"><span>Overview</span><small>live</small></a>
        <a href="/api/ops/status"><span>Status API</span><small>json</small></a>
        <a href="/api/assets"><span>Public API</span><small>json</small></a>
        <a href="/"><span>Public Service</span><small>home</small></a>
      </nav>
    </aside>
    {body}
  </div>
</body>
</html>"""


def create_app(config: ServiceApiConfig | None = None):
    """Create a FastAPI app for public service data."""
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import HTMLResponse

    config = config or ServiceApiConfig()
    app = FastAPI(title="TradingAgents Research Service API")

    @app.get("/", response_class=HTMLResponse)
    def home() -> HTMLResponse:
        return HTMLResponse(_home_html(load_public_assets(config)))

    @app.get("/search", response_class=HTMLResponse)
    def search_page(
        q: str | None = Query(default=None),
        kind: str | None = Query(default=None),
    ) -> HTMLResponse:
        return HTMLResponse(_search_html(load_public_assets(config), q=q, kind=kind))

    @app.get("/learn", response_class=HTMLResponse)
    def learn_page() -> HTMLResponse:
        return HTMLResponse(_learn_html())

    @app.get("/review", response_class=HTMLResponse)
    def review_page() -> HTMLResponse:
        return HTMLResponse(_review_html(load_public_assets(config)))

    @app.get("/stocks/{ticker}", response_class=HTMLResponse)
    def stock_page(ticker: str) -> HTMLResponse:
        asset = _find_public_asset(load_public_assets(config), kind="stock", slug=ticker)
        return _asset_page_or_404(asset)

    @app.get("/etfs/{ticker}", response_class=HTMLResponse)
    def etf_page(ticker: str) -> HTMLResponse:
        asset = _find_public_asset(load_public_assets(config), kind="etf", slug=ticker)
        return _asset_page_or_404(asset)

    @app.get("/themes/{slug}", response_class=HTMLResponse)
    def theme_page(slug: str) -> HTMLResponse:
        asset = _find_public_asset(load_public_assets(config), kind="theme", slug=slug)
        return _asset_page_or_404(asset)

    @app.get("/assets/{asset_id}", response_class=HTMLResponse)
    def asset_page(asset_id: str) -> HTMLResponse:
        asset = find_asset(load_public_assets(config), asset_id)
        return _asset_page_or_404(asset)

    @app.get("/ops", response_class=HTMLResponse)
    def ops_page() -> HTMLResponse:
        return HTMLResponse(_ops_html(config))

    @app.get("/api/assets")
    def assets(
        kind: str | None = Query(default=None),
        q: str | None = Query(default=None),
    ) -> dict[str, Any]:
        rows = _filter_assets(load_public_assets(config), kind=kind, q=q)
        return {
            "schema_version": 1,
            "artifact": "service_asset_list",
            "count": len(rows),
            "assets": [_asset_summary(asset) for asset in rows],
        }

    @app.get("/api/assets/{asset_id}")
    def asset_detail(asset_id: str) -> dict[str, Any]:
        asset = find_asset(load_public_assets(config), asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="asset not found")
        return {
            "schema_version": 1,
            "artifact": "service_asset_detail",
            "asset": asset,
        }

    @app.get("/api/themes")
    def themes() -> dict[str, Any]:
        rows = theme_assets(load_public_assets(config))
        return {
            "schema_version": 1,
            "artifact": "service_theme_list",
            "count": len(rows),
            "themes": [_asset_summary(asset) for asset in rows],
        }

    @app.get("/api/reviews")
    def reviews() -> dict[str, Any]:
        rows = load_public_assets(config)
        return {
            "schema_version": 1,
            "artifact": "service_review_list",
            "count": len(rows),
            "reviews": [_review_summary(asset) for asset in rows],
        }

    @app.get("/api/ops/status")
    def ops_status() -> dict[str, Any]:
        return load_ops_status(config)

    return app
