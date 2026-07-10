"""Clean public Research Gateway site built from local TradingAgents assets."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from tradingagents.service_api import DEFAULT_ASSET_DIRS, ServiceApiConfig, load_breaking_list, load_ops_status
from tradingagents.service_assets import find_asset, load_assets, theme_assets


def _esc(value: Any) -> str:
    return "" if value is None else html.escape(str(value), quote=True)


def _slug(value: Any) -> str:
    raw = str(value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9가-힣]+", "-", raw)
    return slug.strip("-") or "asset"


def _kind_label(kind: Any) -> str:
    return {"stock": "종목", "etf": "ETF", "theme": "테마"}.get(str(kind or ""), str(kind or "-"))


def _excerpt(value: Any, *, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _asset_href(asset: dict[str, Any]) -> str:
    slug = _slug(asset.get("ticker") or asset.get("id"))
    if asset.get("kind") == "stock":
        return f"/stocks/{slug}"
    if asset.get("kind") == "etf":
        return f"/etfs/{slug}"
    if asset.get("kind") == "theme":
        return f"/themes/{slug}"
    return f"/assets/{_esc(asset.get('id'))}"


def _find_public_asset(assets: list[dict[str, Any]], *, kind: str, slug: str) -> dict[str, Any] | None:
    normalized = _slug(slug)
    for asset in assets:
        if asset.get("kind") == kind and _slug(asset.get("ticker") or asset.get("id")) == normalized:
            return asset
    return None


def _fmt_pct(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{'+' if number > 0 else ''}{number:.2f}%"


def _pct_class(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "neutral"
    if number > 0:
        return "positive"
    if number < 0:
        return "negative"
    return "neutral"


def _fmt_weight(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):g}%"
    except (TypeError, ValueError):
        return "-"


def _bar_rows(rows: list[dict[str, Any]], *, limit: int = 8) -> str:
    if not rows:
        return '<p class="empty-note">구성 데이터 대기</p>'
    parts = []
    for row in rows[:limit]:
        label = row.get("name") or row.get("ticker") or row.get("stage") or "-"
        ticker = row.get("ticker") or row.get("role") or ""
        weight = row.get("weight_pct")
        try:
            width = max(5, min(100, float(weight)))
            value = f"{float(weight):g}%"
        except (TypeError, ValueError):
            width = 10
            value = ticker
        parts.append(
            '<div class="weight-row">'
            f'<span><b>{_esc(label)}</b><small>{_esc(ticker)}</small></span>'
            f'<em>{_esc(value)}</em><i style="width:{width:.2f}%"></i>'
            '</div>'
        )
    return "".join(parts)


def _source_badges(asset: dict[str, Any]) -> str:
    sources = asset.get("sources") or []
    labels = {
        "toss_securities_openapi": "토스증권 시세",
        "issuer_download": "운용사 구성",
        "manual_theme_map": "테마 맵",
        "structured_profile": "구성 프로필",
        "schema_sample_only_not_market_data": "구성 샘플",
    }
    return "".join(
        f'<span>{_esc(source.get("kind"))}: {_esc(labels.get(str(source.get("label")), source.get("label")))}</span>'
        for source in sources[:4]
    ) or "<span>출처 대기</span>"


def _movement_row(asset: dict[str, Any], rank: int) -> str:
    review = asset.get("review") or {}
    metrics = review.get("metrics") or {}
    return_1d = metrics.get("return_1d_pct")
    return (
        '<a class="movement-row" href="' + _asset_href(asset) + '">'
        f'<strong>{rank:02d}</strong>'
        '<span>'
        f'<b>{_esc(asset.get("name"))}</b>'
        f'<small>{_esc(asset.get("ticker"))} · {_kind_label(asset.get("kind"))} · {_esc(asset.get("market"))}</small>'
        '</span>'
        f'<p>{_esc(_excerpt((asset.get("why_moved") or {}).get("summary") or "원인 데이터 대기", limit=180))}</p>'
        f'<em class="pct {_pct_class(return_1d)}">{_fmt_pct(return_1d)}</em>'
        '</a>'
    )


def _movement_list(assets: list[dict[str, Any]]) -> str:
    return "".join(_movement_row(asset, index + 1) for index, asset in enumerate(assets[:8])) or (
        '<p class="empty-note">발행 가능한 콘텐츠가 없습니다.</p>'
    )


def _asset_card(asset: dict[str, Any]) -> str:
    one_liner = (asset.get("one_liner") or {}).get("summary")
    why = (asset.get("why_moved") or {}).get("summary")
    metrics = (asset.get("review") or {}).get("metrics") or {}
    return_5d = metrics.get("return_5d_pct")
    return (
        '<article class="asset-card">'
        f'<a href="{_asset_href(asset)}">'
        '<div class="card-meta">'
        f'<span>{_kind_label(asset.get("kind"))} · {_esc(asset.get("market"))}</span>'
        f'<em class="pct {_pct_class(return_5d)}">{_fmt_pct(return_5d)}</em>'
        '</div>'
        f'<h3>{_esc(asset.get("name"))}</h3>'
        f'<small>{_esc(asset.get("ticker"))}</small>'
        f'<p>{_esc(_excerpt(why or one_liner or "요약 데이터 대기", limit=150))}</p>'
        f'<div class="source-badges">{_source_badges(asset)}</div>'
        '</a>'
        '</article>'
    )


def _theme_feature(themes: list[dict[str, Any]]) -> str:
    theme = themes[0] if themes else None
    if not theme:
        return '<section class="feature-card"><span>Theme Map</span><h2>테마 데이터 대기</h2></section>'
    stages = ((theme.get("composition") or {}).get("value_chain") or [])[:5]
    chips = "".join(
        '<i>'
        f'<b>{_esc(stage.get("stage") or stage.get("name"))}</b>'
        f'<small>국내 {len(stage.get("domestic_names") or [])} · 해외 {len(stage.get("global_names") or [])}</small>'
        '</i>'
        for stage in stages
    )
    return (
        '<section class="feature-card theme-card">'
        '<span>Theme Map</span>'
        f'<h2><a href="{_asset_href(theme)}">{_esc(theme.get("name"))}</a></h2>'
        f'<p>{_esc(_excerpt((theme.get("why_moved") or {}).get("summary") or "테마 설명 대기", limit=150))}</p>'
        f'<div class="value-chain">{chips or "<i><b>밸류체인 대기</b><small>data pending</small></i>"}</div>'
        '</section>'
    )


def _etf_feature(etfs: list[dict[str, Any]]) -> str:
    etf = etfs[0] if etfs else None
    if not etf:
        return '<section class="feature-card"><span>ETF X-ray</span><h2>ETF 데이터 대기</h2></section>'
    composition = etf.get("composition") or {}
    return (
        '<section class="feature-card etf-card">'
        '<span>ETF X-ray</span>'
        f'<h2><a href="{_asset_href(etf)}">{_esc(etf.get("name"))}</a></h2>'
        f'<p>{_esc(composition.get("issuer") or etf.get("ticker"))} · {_esc(composition.get("benchmark") or "benchmark pending")}</p>'
        f'{_bar_rows(composition.get("holdings") or [], limit=5)}'
        '</section>'
    )


def _review_feature(assets: list[dict[str, Any]]) -> str:
    reviewed = [asset for asset in assets if (asset.get("review") or {}).get("status") == "available"]
    rows = "".join(
        '<a href="' + _asset_href(asset) + '">'
        f'<b>{_esc(asset.get("name"))}</b>'
        f'<span class="pct {_pct_class(((asset.get("review") or {}).get("metrics") or {}).get("return_5d_pct"))}">{_fmt_pct(((asset.get("review") or {}).get("metrics") or {}).get("return_5d_pct"))}</span>'
        '</a>'
        for asset in reviewed[:5]
    )
    return (
        '<section class="feature-card review-card">'
        '<span>After Check</span>'
        '<h2><a href="/review">사후 점검</a></h2>'
        f'<p>{len(reviewed)}개 콘텐츠의 발행 후 흐름을 추적합니다.</p>'
        f'<div class="review-mini">{rows or "<p class=\"empty-note\">검증 데이터 대기</p>"}</div>'
        '</section>'
    )


def _home_html(assets: list[dict[str, Any]]) -> str:
    stocks = [asset for asset in assets if asset.get("kind") == "stock"]
    etfs = [asset for asset in assets if asset.get("kind") == "etf"]
    themes = [asset for asset in assets if asset.get("kind") == "theme"]
    lead = assets[0] if assets else None
    lead_href = _asset_href(lead) if lead else "/search"
    lead_name = lead.get("name") if lead else "오늘의 리서치"
    lead_why = _excerpt((lead.get("why_moved") or {}).get("summary") if lead else "검색으로 시작하세요.", limit=170)
    counts = [
        ("종목", len(stocks), "/search?kind=stock"),
        ("ETF", len(etfs), "/search?kind=etf"),
        ("테마", len(themes), "/search?kind=theme"),
    ]
    count_links = "".join(
        f'<a href="{href}"><b>{count}</b><span>{label}</span></a>'
        for label, count, href in counts
    )
    return _page(
        "Research Gateway",
        f"""
        <main class="home">
          <section class="hero">
            <div class="hero-copy">
              <span class="kicker">Research Wiki</span>
              <h1>시장 이슈를 종목, ETF, 테마로 번역합니다</h1>
              <p>왜 움직였는지 먼저 읽고, 구성과 출처를 확인한 뒤 다음 관찰 포인트로 넘어갑니다.</p>
              <form class="search-bar" method="get" action="/search">
                <input name="q" placeholder="삼성전자, Apple, AI 반도체, ETF">
                <button>검색</button>
              </form>
              <div class="quick-links">
                <a href="/search?kind=theme">섹터·테마</a>
                <a href="/search?kind=stock">종목 탐색</a>
                <a href="/search?kind=etf">ETF 구성</a>
                <a href="/learn">처음 보는 ETF·테마</a>
              </div>
            </div>
            <a class="lead-story" href="{lead_href}">
              <span>오늘 먼저 볼 흐름</span>
              <b>{_esc(lead_name)}</b>
              <p>{_esc(lead_why)}</p>
            </a>
          </section>
          <section class="market-rails" aria-label="콘텐츠 현황">{count_links}</section>
          <section class="movement">
            <div class="section-title">
              <h2>왜 움직였나</h2>
              <p>숫자판보다 먼저 읽는 오늘의 흐름입니다.</p>
            </div>
            <div class="movement-list">{_movement_list(assets)}</div>
          </section>
          <section class="feature-grid">
            {_theme_feature(themes)}
            {_etf_feature(etfs)}
            {_review_feature(assets)}
          </section>
          <section class="library">
            <div class="section-title">
              <h2>위키 라이브러리</h2>
              <p>{len(stocks)}개 종목, {len(etfs)}개 ETF, {len(themes)}개 테마</p>
            </div>
            <div class="card-grid">{''.join(_asset_card(asset) for asset in assets[:12])}</div>
          </section>
        </main>
        """,
    )


def _search_html(assets: list[dict[str, Any]], *, q: str | None = None, kind: str | None = None) -> str:
    rows = assets
    if kind:
        rows = [asset for asset in rows if asset.get("kind") == kind]
    if q:
        needle = q.lower()
        rows = [
            asset for asset in rows
            if needle in str(asset.get("name") or "").lower()
            or needle in str(asset.get("ticker") or "").lower()
            or needle in str((asset.get("why_moved") or {}).get("summary") or "").lower()
        ]
    options = "".join(
        f'<a class="{"active" if value == (kind or "") else ""}" href="/search{("?kind=" + value) if value else ""}">{label}</a>'
        for value, label in (("", "전체"), ("stock", "종목"), ("etf", "ETF"), ("theme", "테마"))
    )
    cards = "".join(_asset_card(asset) for asset in rows) or '<p class="empty-note">검색 결과가 없습니다.</p>'
    return _page(
        "검색 - Research Gateway",
        f"""
        <main class="sub-page">
          <section class="search-head">
            <span class="kicker">Search</span>
            <h1>종목·ETF·테마 검색</h1>
            <form class="search-bar" method="get" action="/search">
              <input name="q" value="{_esc(q or "")}" placeholder="티커, 이름, 테마 키워드">
              <select name="kind">
                <option value="">전체</option>
                <option value="stock"{" selected" if kind == "stock" else ""}>종목</option>
                <option value="etf"{" selected" if kind == "etf" else ""}>ETF</option>
                <option value="theme"{" selected" if kind == "theme" else ""}>테마</option>
              </select>
              <button>검색</button>
            </form>
            <div class="filter-tabs">{options}</div>
          </section>
          <section class="library">
            <div class="section-title"><h2>검색 결과 {len(rows)}개</h2><p>공개 가능한 콘텐츠만 보여줍니다.</p></div>
            <div class="card-grid">{cards}</div>
          </section>
        </main>
        """,
    )


def _point_list(title: str, rows: list[str]) -> str:
    items = "".join(f"<li>{_esc(row)}</li>" for row in rows[:5])
    return f'<section class="detail-panel"><h2>{_esc(title)}</h2><ul>{items or "<li>데이터 대기</li>"}</ul></section>'


def _detail_html(asset: dict[str, Any]) -> str:
    composition = asset.get("composition") or {}
    kind = asset.get("kind")
    if kind == "etf":
        composition_html = (
            '<section class="detail-panel wide"><h2>ETF 구성</h2>'
            '<div class="composition-grid">'
            f'<div><h3>상위 보유 종목</h3>{_bar_rows(composition.get("holdings") or [], limit=10)}</div>'
            f'<div><h3>섹터 비중</h3>{_bar_rows(composition.get("sectors") or [], limit=8)}</div>'
            f'<div><h3>국가 비중</h3>{_bar_rows(composition.get("countries") or [], limit=8)}</div>'
            '</div></section>'
        )
    elif kind == "theme":
        stages = "".join(
            '<article>'
            f'<b>{_esc(stage.get("stage") or stage.get("name"))}</b>'
            f'<p>{_esc(stage.get("description") or "설명 대기")}</p>'
            f'<small>국내 {len(stage.get("domestic_names") or [])} · 해외 {len(stage.get("global_names") or [])}</small>'
            '</article>'
            for stage in composition.get("value_chain") or []
        )
        composition_html = (
            '<section class="detail-panel wide"><h2>테마 밸류체인</h2>'
            f'<div class="stage-map">{stages or "<p class=\"empty-note\">밸류체인 데이터 대기</p>"}</div>'
            '</section>'
        )
    else:
        products = _bar_rows(composition.get("business_lines") or composition.get("products") or [], limit=8)
        regions = _bar_rows(composition.get("regions") or [], limit=8)
        composition_html = (
            '<section class="detail-panel wide"><h2>사업/지역 구성</h2>'
            '<div class="composition-grid">'
            f'<div><h3>사업/제품</h3>{products}</div>'
            f'<div><h3>지역 노출</h3>{regions}</div>'
            '</div></section>'
        )
    review = asset.get("review") or {}
    metrics = review.get("metrics") or {}
    trust = (
        '<section class="detail-panel trust">'
        '<h2>데이터 신뢰</h2>'
        f'<div class="source-badges">{_source_badges(asset)}</div>'
        f'<p>시각화 {sum(1 for visual in asset.get("visuals") or [] if visual.get("status") == "ready")} / {len(asset.get("visuals") or [])} ready</p>'
        f'<p>1일 {_fmt_pct(metrics.get("return_1d_pct"))} · 5일 {_fmt_pct(metrics.get("return_5d_pct"))} · 20일 {_fmt_pct(metrics.get("return_20d_pct"))}</p>'
        '</section>'
    )
    return _page(
        f"{asset.get('name')} - Research Gateway",
        f"""
        <main class="detail-page">
          <section class="detail-hero">
            <a class="back-link" href="/">홈</a>
            <span class="kicker">{_kind_label(kind)} · {_esc(asset.get("market"))}</span>
            <h1>{_esc(asset.get("name"))}</h1>
            <p class="ticker-line">{_esc(asset.get("ticker"))}</p>
            <p>{_esc((asset.get("one_liner") or {}).get("summary"))}</p>
          </section>
          <section class="why-panel">
            <h2>왜 움직였나</h2>
            <p>{_esc((asset.get("why_moved") or {}).get("summary"))}</p>
          </section>
          <div class="detail-grid">
            {composition_html}
            {trust}
            {_point_list("상승 관점", asset.get("bull_points") or [])}
            {_point_list("주의 관점", asset.get("bear_points") or [])}
            {_point_list("다음 관찰", asset.get("watch_points") or [])}
          </div>
        </main>
        """,
    )


def _review_html(assets: list[dict[str, Any]]) -> str:
    rows = "".join(_movement_row(asset, index + 1) for index, asset in enumerate(assets))
    return _page(
        "사후 점검 - Research Gateway",
        f"""
        <main class="sub-page">
          <section class="search-head">
            <span class="kicker">Review</span>
            <h1>발행 후 실제 흐름</h1>
            <p>콘텐츠를 발행한 뒤 1일·5일·20일 변화를 남깁니다.</p>
          </section>
          <section class="movement"><div class="movement-list">{rows}</div></section>
        </main>
        """,
    )


def _learn_html() -> str:
    concepts = [
        ("ETF", "여러 종목을 한 바구니에 담아 거래하는 상품입니다. 가격보다 구성과 비중을 먼저 봅니다."),
        ("테마", "정책, 기술, 사건으로 묶인 투자 이야기입니다. 밸류체인과 대표 종목을 같이 봅니다."),
        ("왜 움직였나", "뉴스, 실적, 금리, 환율, 수급 중 어떤 배경이 큰지 분리해서 읽습니다."),
        ("사후 점검", "발행 후 실제 가격 변화를 남겨 콘텐츠 품질을 검증합니다."),
    ]
    cards = "".join(f'<article class="asset-card"><h3>{_esc(title)}</h3><p>{_esc(body)}</p></article>' for title, body in concepts)
    return _page("처음 보는 ETF·테마 - Research Gateway", f'<main class="sub-page"><section class="search-head"><h1>처음 보는 ETF·테마</h1></section><div class="card-grid">{cards}</div></main>')


def _ops_html(config: ServiceApiConfig) -> str:
    status = load_ops_status(config)
    return _page(
        "Ops - Research Gateway",
        f"""
        <main class="sub-page ops-lite">
          <section class="search-head">
            <span class="kicker">Operations</span>
            <h1>Research Gateway Ops</h1>
            <p>공개 서비스와 분리된 운영 상태입니다.</p>
          </section>
          <div class="card-grid">
            <article class="asset-card"><h3>Service Health</h3><p>{_esc(status.get("status"))}</p></article>
            <article class="asset-card"><h3>Cost Guard</h3><p>paid model: {"allowed" if (status.get("cost_guard") or {}).get("paid_model_allowed") else "locked"}</p></article>
            <article class="asset-card"><h3>Publish Gate</h3><p>{_esc((status.get("publish") or {}).get("publish_ready_assets"))} ready assets</p></article>
            <article class="asset-card"><h3>Candidate Queue</h3><p>{_esc(status.get("ready_candidates"))} / {_esc(status.get("target_candidates"))}</p></article>
          </div>
        </main>
        """,
    )


def _asset_summary(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": asset.get("id"),
        "kind": asset.get("kind"),
        "ticker": asset.get("ticker"),
        "name": asset.get("name"),
        "market": asset.get("market"),
        "one_liner": (asset.get("one_liner") or {}).get("summary"),
        "why_moved": (asset.get("why_moved") or {}).get("summary"),
        "as_of": asset.get("as_of"),
        "publish_status": asset.get("publish_status"),
    }


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <style>
    :root {{
      --bg:#F8FAFC; --paper:#FFFFFF; --ink:#0F172A; --muted:#64748B; --line:#CBD5E1;
      --navy:#1E3A5F; --blue:#2563EB; --amber:#A16207; --soft:#E9EEF5;
      --positive:#14845F; --negative:#B42318; --shadow:0 1px 2px rgba(15,23,42,.06),0 12px 30px rgba(15,23,42,.05);
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 "IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    a {{ color:inherit; text-decoration:none; }}
    a,button,select,input {{ transition:border-color .18s ease,box-shadow .18s ease,background .18s ease,color .18s ease,transform .18s ease; }}
    a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible {{ outline:3px solid rgba(37,99,235,.28); outline-offset:2px; }}
    button,a[href] {{ cursor:pointer; }}
    .topbar {{ position:sticky; top:0; z-index:10; min-height:60px; display:flex; align-items:center; gap:22px; padding:10px clamp(18px,4vw,54px); background:rgba(255,255,255,.96); border-bottom:1px solid var(--line); backdrop-filter:blur(12px); }}
    .brand {{ font-weight:900; letter-spacing:0; color:var(--navy); }}
    nav {{ margin-left:auto; display:flex; gap:4px; color:var(--muted); font-size:14px; }}
    nav a {{ border-radius:8px; padding:8px 10px; }}
    nav a:hover {{ background:var(--soft); color:var(--ink); }}
    main {{ padding:18px clamp(18px,4vw,54px) 52px; }}
    .hero {{ display:grid; grid-template-columns:minmax(0,1.45fr) minmax(300px,.55fr); gap:12px; min-height:340px; }}
    .hero-copy,.lead-story,.feature-card,.asset-card,.movement,.search-head,.detail-hero,.why-panel,.detail-panel,.market-rails {{ background:var(--paper); border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow); }}
    .hero-copy {{ padding:30px; display:grid; align-content:center; border-left:4px solid var(--navy); }}
    .kicker,.feature-card > span,.lead-story span {{ color:var(--blue); font-weight:900; font-size:12px; text-transform:uppercase; letter-spacing:0; }}
    h1,h2,h3,p {{ margin-top:0; }}
    h1 {{ font-size:clamp(32px,4.4vw,58px); line-height:1.04; letter-spacing:0; max-width:860px; }}
    h2 {{ font-size:23px; letter-spacing:0; }}
    h3 {{ font-size:17px; letter-spacing:0; }}
    p {{ color:#334155; }}
    .search-bar {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; margin-top:12px; max-width:760px; }}
    .search-bar input,.search-bar select {{ min-width:0; border:1px solid var(--line); border-radius:8px; background:#fff; padding:13px 14px; font:inherit; }}
    .search-bar select {{ width:130px; }}
    .search-bar button {{ border:0; border-radius:8px; background:var(--navy); color:#fff; padding:0 18px; font:inherit; font-weight:800; }}
    .search-bar button:hover {{ background:#16324F; }}
    .quick-links,.filter-tabs {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; }}
    .quick-links a,.filter-tabs a {{ border:1px solid var(--line); border-radius:999px; padding:8px 11px; color:var(--muted); background:#fff; font-weight:700; }}
    .quick-links a:hover,.filter-tabs a:hover {{ border-color:var(--blue); color:var(--blue); }}
    .filter-tabs a.active {{ background:var(--navy); color:#fff; border-color:var(--navy); }}
    .lead-story {{ padding:22px; display:grid; align-content:end; background:var(--navy); color:#fff; }}
    .lead-story:hover,.asset-card:hover,.feature-card:hover {{ transform:translateY(-1px); }}
    .lead-story b {{ display:block; font-size:28px; line-height:1.12; margin:8px 0; }}
    .lead-story p {{ color:#d5dde5; }}
    .market-rails {{ display:grid; grid-template-columns:repeat(3,1fr); gap:0; margin-top:12px; overflow:hidden; }}
    .market-rails a {{ display:flex; align-items:baseline; justify-content:space-between; min-height:74px; padding:16px 18px; border-right:1px solid var(--line); }}
    .market-rails a:last-child {{ border-right:0; }}
    .market-rails b {{ font-size:28px; color:var(--navy); }}
    .market-rails span {{ color:var(--muted); font-weight:800; }}
    .section-title {{ display:flex; justify-content:space-between; align-items:end; gap:18px; margin:26px 0 10px; }}
    .section-title p {{ margin:0; color:var(--muted); }}
    .movement {{ padding:12px; }}
    .movement-row {{ display:grid; grid-template-columns:48px minmax(170px,.45fr) minmax(240px,1fr) 82px; gap:14px; align-items:start; padding:13px 8px; border-bottom:1px solid var(--line); }}
    .movement-row:last-child {{ border-bottom:0; }}
    .movement-row:hover {{ background:#F8FAFC; }}
    .movement-row strong {{ color:var(--blue); }}
    .movement-row small {{ display:block; color:var(--muted); }}
    .movement-row p {{ margin:0; color:#334155; overflow-wrap:anywhere; }}
    .pct {{ font-style:normal; text-align:right; font-weight:900; font-variant-numeric:tabular-nums; color:var(--muted); }}
    .pct.positive {{ color:var(--positive); }}
    .pct.negative {{ color:var(--negative); }}
    .feature-grid {{ display:grid; grid-template-columns:1.1fr 1.1fr .8fr; gap:14px; margin-top:18px; }}
    .feature-card,.asset-card {{ padding:18px; }}
    .value-chain {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:8px; margin-top:12px; }}
    .value-chain i {{ border:1px solid var(--line); border-radius:8px; padding:10px; font-style:normal; background:var(--soft); }}
    .value-chain small {{ display:block; color:var(--muted); }}
    .weight-row {{ position:relative; display:grid; grid-template-columns:1fr auto; gap:12px; padding-bottom:10px; margin:10px 0; }}
    .weight-row small {{ display:block; color:var(--muted); }}
    .weight-row em {{ font-style:normal; font-weight:800; color:var(--muted); }}
    .weight-row i {{ position:absolute; left:0; bottom:0; height:4px; border-radius:999px; background:var(--blue); }}
    .review-mini {{ display:grid; gap:8px; margin-top:12px; }}
    .review-mini a {{ display:flex; justify-content:space-between; gap:12px; border-bottom:1px solid var(--line); padding-bottom:8px; }}
    .library {{ margin-top:18px; }}
    .card-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:12px; }}
    .card-meta {{ display:flex; justify-content:space-between; gap:12px; align-items:center; }}
    .asset-card h3 {{ margin:6px 0 0; }}
    .asset-card small,.asset-card span,.empty-note {{ color:var(--muted); }}
    .asset-card p,.movement-row p,.lead-story p {{ overflow-wrap:anywhere; display:-webkit-box; -webkit-box-orient:vertical; overflow:hidden; }}
    .asset-card p,.movement-row p {{ -webkit-line-clamp:3; }}
    .lead-story p {{ -webkit-line-clamp:5; }}
    .source-badges {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:12px; }}
    .source-badges span {{ border:1px solid var(--line); border-radius:999px; padding:4px 8px; color:#475569; background:#F8FAFC; font-size:12px; }}
    .sub-page,.detail-page {{ max-width:1180px; margin:0 auto; }}
    .search-head,.detail-hero,.why-panel,.detail-panel {{ padding:22px; margin-bottom:14px; }}
    .detail-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px; }}
    .wide {{ grid-column:1/-1; }}
    .composition-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; }}
    .stage-map {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; }}
    .stage-map article {{ border:1px solid var(--line); border-radius:8px; padding:12px; background:var(--soft); }}
    .back-link {{ color:var(--muted); display:inline-block; margin-bottom:10px; }}
    .ticker-line {{ color:var(--muted); font-weight:800; }}
    .ops-lite {{ max-width:960px; }}
    @media (prefers-reduced-motion:reduce) {{
      *,*::before,*::after {{ transition:none!important; scroll-behavior:auto!important; }}
    }}
    @media (max-width:820px) {{
      .topbar {{ height:auto; align-items:flex-start; flex-direction:column; padding-top:12px; padding-bottom:12px; }}
      nav {{ margin-left:0; flex-wrap:wrap; }}
      .hero,.feature-grid,.movement-row,.market-rails {{ grid-template-columns:1fr; }}
      .market-rails a {{ border-right:0; border-bottom:1px solid var(--line); }}
      .market-rails a:last-child {{ border-bottom:0; }}
      .pct {{ text-align:left; }}
      .search-bar {{ grid-template-columns:1fr; }}
      .search-bar select {{ width:100%; }}
    }}
  </style>
</head>
<body>
  <header class="topbar">
    <a class="brand" href="/">Research Gateway</a>
    <nav>
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
    return load_assets(config.asset_dirs)


def create_app(config: ServiceApiConfig | None = None):
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import HTMLResponse

    config = config or ServiceApiConfig()
    app = FastAPI(title="Research Gateway")

    @app.get("/", response_class=HTMLResponse)
    def home() -> HTMLResponse:
        return HTMLResponse(_home_html(load_public_assets(config)))

    @app.get("/search", response_class=HTMLResponse)
    def search(q: str | None = Query(default=None), kind: str | None = Query(default=None)) -> HTMLResponse:
        return HTMLResponse(_search_html(load_public_assets(config), q=q, kind=kind))

    @app.get("/stocks/{ticker}", response_class=HTMLResponse)
    def stock(ticker: str) -> HTMLResponse:
        asset = _find_public_asset(load_public_assets(config), kind="stock", slug=ticker)
        if not asset:
            raise HTTPException(status_code=404, detail="asset not found")
        return HTMLResponse(_detail_html(asset))

    @app.get("/etfs/{ticker}", response_class=HTMLResponse)
    def etf(ticker: str) -> HTMLResponse:
        asset = _find_public_asset(load_public_assets(config), kind="etf", slug=ticker)
        if not asset:
            raise HTTPException(status_code=404, detail="asset not found")
        return HTMLResponse(_detail_html(asset))

    @app.get("/themes/{slug}", response_class=HTMLResponse)
    def theme(slug: str) -> HTMLResponse:
        asset = _find_public_asset(load_public_assets(config), kind="theme", slug=slug)
        if not asset:
            raise HTTPException(status_code=404, detail="asset not found")
        return HTMLResponse(_detail_html(asset))

    @app.get("/review", response_class=HTMLResponse)
    def review() -> HTMLResponse:
        return HTMLResponse(_review_html(load_public_assets(config)))

    @app.get("/learn", response_class=HTMLResponse)
    def learn() -> HTMLResponse:
        return HTMLResponse(_learn_html())

    @app.get("/ops", response_class=HTMLResponse)
    def ops() -> HTMLResponse:
        return HTMLResponse(_ops_html(config))

    @app.get("/assets/{asset_id}", response_class=HTMLResponse)
    def legacy_asset(asset_id: str) -> HTMLResponse:
        asset = find_asset(load_public_assets(config), asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="asset not found")
        return HTMLResponse(_detail_html(asset))

    @app.get("/api/assets")
    def assets(kind: str | None = Query(default=None), q: str | None = Query(default=None)) -> dict[str, Any]:
        rows = load_public_assets(config)
        if kind:
            rows = [asset for asset in rows if asset.get("kind") == kind]
        if q:
            needle = q.lower()
            rows = [
                asset for asset in rows
                if needle in str(asset.get("name") or "").lower()
                or needle in str(asset.get("ticker") or "").lower()
                or needle in str((asset.get("why_moved") or {}).get("summary") or "").lower()
            ]
        return {"schema_version": 1, "artifact": "service_asset_list", "count": len(rows), "assets": [_asset_summary(asset) for asset in rows]}

    @app.get("/api/assets/{asset_id}")
    def asset_detail(asset_id: str) -> dict[str, Any]:
        asset = find_asset(load_public_assets(config), asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="asset not found")
        return {"schema_version": 1, "artifact": "service_asset_detail", "asset": asset}

    @app.get("/api/themes")
    def themes() -> dict[str, Any]:
        rows = theme_assets(load_public_assets(config))
        return {"schema_version": 1, "artifact": "service_theme_list", "count": len(rows), "themes": [_asset_summary(asset) for asset in rows]}

    @app.get("/api/reviews")
    def reviews() -> dict[str, Any]:
        rows = [
            asset
            for asset in load_public_assets(config)
            if (asset.get("review") or {}).get("status") == "available"
        ]
        return {
            "schema_version": 1,
            "artifact": "service_review_list",
            "count": len(rows),
            "reviews": [
                {
                    **_asset_summary(asset),
                    "metrics": (asset.get("review") or {}).get("metrics") or {},
                }
                for asset in rows
            ],
        }

    @app.get("/api/ops/status")
    def ops_status() -> dict[str, Any]:
        return load_ops_status(config)

    @app.get("/api/breaking")
    def breaking() -> dict[str, Any]:
        return load_breaking_list(config)

    return app
