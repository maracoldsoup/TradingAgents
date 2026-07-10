"""Static local-only dashboard for the low-cost pilot artifacts."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _pct(value: Any) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "-"


def _num(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def _status_class(value: Any) -> str:
    status = str(value or "unknown").lower()
    if status in {"pass", "ready", "continue"}:
        return "good"
    if status in {"warn", "continue_with_constraints", "needs_more_candidates", "needs_inputs"}:
        return "watch"
    if status in {"fail", "blocked"}:
        return "bad"
    return "neutral"


def _dict_text(value: Any) -> str:
    if not isinstance(value, dict):
        return "{}"
    return ", ".join(f"{key}: {val}" for key, val in value.items()) or "{}"


def _metric(label: str, value: Any, *, status: str | None = None) -> str:
    status_attr = f' data-status="{_esc(status)}"' if status else ""
    return (
        f'<article class="metric"{status_attr}>'
        f'<span>{_esc(label)}</span>'
        f'<strong>{_esc(value)}</strong>'
        '</article>'
    )


def _badge(value: Any) -> str:
    text = str(value or "-")
    return f'<span class="badge {_status_class(text)}">{_esc(text)}</span>'


def _bar(label: str, current: int, minimum: int) -> str:
    width = 100 if minimum <= 0 else min(100, round(current / minimum * 100, 1))
    return (
        '<div class="bar-row">'
        f'<div><b>{_esc(label)}</b><span>{_num(current)} / {_num(minimum)}</span></div>'
        f'<div class="track"><i style="width:{width}%"></i></div>'
        '</div>'
    )


def _queue_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<tr><td colspan="6">후보 없음</td></tr>'
    cells = []
    for row in rows:
        missing = ", ".join(row.get("missing_inputs") or []) or "-"
        cells.append(
            '<tr>'
            f'<td><b>{_esc(row.get("ticker"))}</b><small>{_esc(row.get("name") or "")}</small></td>'
            f'<td>{_esc(row.get("content_type"))}</td>'
            f'<td>{_esc(row.get("market"))}</td>'
            f'<td>{_badge(row.get("status"))}</td>'
            f'<td>{_esc(missing)}</td>'
            f'<td>{_esc(", ".join(row.get("source_types") or []))}</td>'
            '</tr>'
        )
    return "".join(cells)


def _slot_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<tr><td colspan="4">추가 슬롯 없음</td></tr>'
    body = []
    for row in rows:
        body.append(
            '<tr>'
            f'<td>{_num(row.get("slot"))}</td>'
            f'<td>{_esc(row.get("preferred_content_type"))}</td>'
            f'<td>{_esc(row.get("preferred_market"))}</td>'
            f'<td>{_esc(row.get("required_input"))}</td>'
            '</tr>'
        )
    return "".join(body)


def _actions(items: list[Any]) -> str:
    if not items:
        return '<li>대기 중인 액션 없음</li>'
    return "".join(f"<li>{_esc(item)}</li>" for item in items[:8])


def build_pilot_dashboard(
    *,
    local_pilot: dict[str, Any],
    candidate_queue: dict[str, Any],
    candidate_gap: dict[str, Any],
    assessment: dict[str, Any],
    input_review: dict[str, Any] | None = None,
    preview_links: dict[str, str] | None = None,
    title: str = "TradingAgents Local Pilot Dashboard",
) -> str:
    preview_links = preview_links or {}
    input_review = input_review or {}
    gate = local_pilot.get("gate") or {}
    cost = local_pilot.get("cost_guard") or {}
    content = (local_pilot.get("content_pilot") or {}).get("summary") or {}
    content_quality = (local_pilot.get("content_quality") or {}).get("summary") or {}
    profile = (local_pilot.get("profile_pilot") or {}).get("summary") or {}
    profile_quality = (local_pilot.get("profile_content_quality") or {}).get("summary") or {}
    queue_summary = candidate_queue.get("summary") or {}
    queue_gate = candidate_queue.get("gate") or {}
    gap_summary = candidate_gap.get("summary") or {}
    input_summary = input_review.get("summary") or {}
    verdict = assessment.get("verdict") or {}
    type_gaps = candidate_gap.get("type_gaps") or {}
    market_gaps = candidate_gap.get("market_gaps") or {}
    queue_rows = candidate_queue.get("rows") or []
    slot_plan = candidate_gap.get("slot_plan") or []

    type_bars = "".join(
        _bar(str(key), int(value.get("current_ready", 0)), int(value.get("minimum", 0)))
        for key, value in type_gaps.items()
        if isinstance(value, dict)
    )
    market_bars = "".join(
        _bar(str(key), int(value.get("current_ready", 0)), int(value.get("minimum", 0)))
        for key, value in market_gaps.items()
        if isinstance(value, dict)
    )
    links = "".join(
        f'<a href="{_esc(path)}">{_esc(label)}</a>'
        for label, path in preview_links.items()
        if path
    )

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <style>
    :root {{
      --paper: #f8f7f2;
      --panel: #ffffff;
      --ink: #202124;
      --muted: #667085;
      --line: #d7d3c8;
      --blue: #146c94;
      --green: #277a55;
      --amber: #9a6a00;
      --red: #b42318;
      --violet: #6846a3;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: var(--paper);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      background: #fff;
      border-bottom: 1px solid var(--line);
      padding: 22px clamp(16px, 4vw, 42px);
    }}
    h1, h2, h3, p {{ margin-top: 0; }}
    h1 {{ font-size: 26px; margin-bottom: 6px; letter-spacing: 0; }}
    header p {{ margin-bottom: 0; color: var(--muted); max-width: 920px; }}
    main {{ padding: 18px clamp(16px, 4vw, 42px) 48px; }}
    section {{
      border-top: 1px solid var(--line);
      padding: 20px 0;
    }}
    .topline {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-top: 14px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border-radius: 999px;
      padding: 3px 9px;
      font-size: 12px;
      border: 1px solid var(--line);
      white-space: nowrap;
    }}
    .good {{ color: var(--green); background: #eef8f1; border-color: #b8dec6; }}
    .watch {{ color: var(--amber); background: #fff7e6; border-color: #efd08a; }}
    .bad {{ color: var(--red); background: #fff1f0; border-color: #f0b8b2; }}
    .neutral {{ color: var(--muted); background: #f3f4f6; }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px;
      margin-top: 14px;
    }}
    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      min-height: 72px;
      padding: 12px;
    }}
    .metric span {{ display: block; color: var(--muted); font-size: 12px; }}
    .metric strong {{ display: block; margin-top: 4px; font-size: 21px; overflow-wrap: anywhere; }}
    .two-col {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 18px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 14px;
      min-width: 0;
    }}
    .panel h3 {{ margin-bottom: 10px; font-size: 15px; }}
    .bar-row + .bar-row {{ margin-top: 12px; }}
    .bar-row > div:first-child {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 5px;
    }}
    .bar-row span {{ color: var(--muted); }}
    .track {{
      height: 9px;
      border-radius: 999px;
      background: #ece8dc;
      overflow: hidden;
    }}
    .track i {{
      display: block;
      height: 100%;
      background: var(--blue);
      border-radius: inherit;
    }}
    .action-list {{
      margin: 0;
      padding-left: 18px;
    }}
    .action-list li + li {{ margin-top: 6px; }}
    .link-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }}
    .link-row a {{
      display: inline-flex;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 10px;
      color: var(--blue);
      background: #fff;
      text-decoration: none;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 6px;
      overflow: hidden;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 9px 10px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
      background: #fbfaf7;
    }}
    td small {{
      display: block;
      color: var(--muted);
      overflow-wrap: anywhere;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    .table-wrap {{ overflow-x: auto; }}
    .footnote {{ color: var(--muted); margin-bottom: 0; }}
    @media (max-width: 760px) {{
      .two-col {{ grid-template-columns: 1fr; }}
      th, td {{ white-space: nowrap; }}
      h1 {{ font-size: 22px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{_esc(title)}</h1>
    <p>콘텐츠 MVP 준비도와 20개 후보 갭 현황</p>
    <div class="topline">
      {_badge(verdict.get("status"))}
      {_badge(input_summary.get("status"))}
      {_badge(queue_gate.get("status"))}
      {_badge(candidate_gap.get("status"))}
      <span class="badge neutral">candidate source: {_esc(verdict.get("candidate_count_source") or "local")}</span>
    </div>
  </header>
  <main>
    <section>
      <h2>판정</h2>
      <div class="metric-grid">
        {_metric("Local gate", gate.get("status") or "-", status=gate.get("status"))}
        {_metric("Cost guard", f"{cost.get('status', '-')} / {cost.get('score', '-')}", status=cost.get("status"))}
        {_metric("Assessment", verdict.get("status") or "-", status=verdict.get("status"))}
        {_metric("Input review", f"{input_summary.get('status', '-')} / {input_summary.get('rows', 0)} rows", status=input_summary.get("status"))}
        {_metric("Ready candidates", f"{queue_summary.get('ready_for_local_pilot', 0)} / {candidate_queue.get('target_candidates', 20)}")}
        {_metric("Shortfall", gap_summary.get("ready_shortfall", 0), status=candidate_gap.get("status"))}
        {_metric("LLM policy", "local only")}
      </div>
      <div class="link-row">{links}</div>
    </section>

    <section>
      <h2>콘텐츠 품질</h2>
      <div class="metric-grid">
        {_metric("Saved reports", content.get("reports", 0))}
        {_metric("Content ready", _pct(content.get("publish_ready_pct")))}
        {_metric("Content quality", _pct(content_quality.get("pass_pct")))}
        {_metric("Profiles", profile.get("reports", 0))}
        {_metric("Profile ready", _pct(profile.get("publish_ready_pct")))}
        {_metric("Profile quality", _pct(profile_quality.get("pass_pct")))}
        {_metric("Market snapshots", content.get("market_snapshots_attached", 0))}
        {_metric("Price charts", content.get("price_trend_ready", 0))}
      </div>
    </section>

    <section>
      <h2>20개 후보 갭</h2>
      <div class="two-col">
        <div class="panel">
          <h3>유형 균형</h3>
          {type_bars or "<p class='footnote'>유형 갭 없음</p>"}
        </div>
        <div class="panel">
          <h3>시장 균형</h3>
          {market_bars or "<p class='footnote'>시장 갭 없음</p>"}
        </div>
      </div>
    </section>

    <section>
      <h2>다음 액션</h2>
      <div class="panel">
        <ul class="action-list">{_actions(candidate_gap.get("actions") or [])}</ul>
      </div>
    </section>

    <section>
      <h2>후보 큐</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>티커</th><th>유형</th><th>시장</th><th>상태</th><th>부족 입력</th><th>소스</th></tr>
          </thead>
          <tbody>{_queue_rows(queue_rows)}</tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>추가 슬롯</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>#</th><th>우선 유형</th><th>우선 시장</th><th>필요 입력</th></tr>
          </thead>
          <tbody>{_slot_rows(slot_plan)}</tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>근거</h2>
      <div class="metric-grid">
        {_metric("Markets", _dict_text(queue_summary.get("markets")))}
        {_metric("Content types", _dict_text(queue_summary.get("content_types")))}
        {_metric("Missing inputs", _dict_text(queue_summary.get("missing_inputs")))}
        {_metric("Warnings", _dict_text(content.get("warnings")))}
        {_metric("Input issues", _dict_text(input_summary.get("issue_codes")))}
      </div>
      <p class="footnote">투자 성과 검증 화면이 아니라, 유료 모델 사용 전 콘텐츠 생산성과 데이터 준비도를 판단하는 로컬 운영 화면입니다.</p>
    </section>
  </main>
</body>
</html>
"""


def render_pilot_dashboard(
    *,
    output: Path = Path(".pilot/dashboard/index.html"),
    local_pilot_path: Path = Path(".pilot/local/local_pilot_report.json"),
    candidate_queue_path: Path = Path(".pilot/candidates/candidate_queue.json"),
    candidate_gap_path: Path = Path(".pilot/candidates/candidate_gap.json"),
    assessment_path: Path = Path(".pilot/assessment/pilot_assessment.json"),
    input_review_path: Path = Path(".pilot/candidates/candidate_input_review.json"),
    preview_links: dict[str, str] | None = None,
    title: str = "TradingAgents Local Pilot Dashboard",
) -> Path:
    html_text = build_pilot_dashboard(
        local_pilot=_read_json(local_pilot_path),
        candidate_queue=_read_json(candidate_queue_path),
        candidate_gap=_read_json(candidate_gap_path),
        assessment=_read_json(assessment_path),
        input_review=_read_json(input_review_path),
        preview_links=preview_links,
        title=title,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8")
    return output
