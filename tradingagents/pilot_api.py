"""FastAPI backend for the local low-cost pilot."""

from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tradingagents.candidate_gap import write_candidate_gap
from tradingagents.candidate_input_review import write_candidate_input_review
from tradingagents.candidate_queue import write_candidate_queue
from tradingagents.content_preview import find_content_snapshot_files
from tradingagents.content_pilot import DEFAULT_REPORTS_DIR
from tradingagents.pilot_assessment import write_assessment
from tradingagents.pilot_dashboard import render_pilot_dashboard


def _read_json(path: Path) -> dict[str, Any]:
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


@dataclass(frozen=True)
class PilotApiConfig:
    """Local artifact paths used by the pilot API."""

    reports_dir: Path = DEFAULT_REPORTS_DIR
    output_root: Path = Path(".pilot")
    report_limit: int = 20
    target_candidates: int = 20
    profile_paths: tuple[Path, ...] = (
        Path("docs/examples/content_profiles.sample.json"),
        Path(".pilot/imported_profiles"),
    )
    candidate_files: tuple[Path, ...] = (Path(".pilot/candidates/manual_candidates.csv"),)
    market_snapshot_dir: Path = Path(".pilot/toss_market")
    local_pilot_reports: tuple[Path, ...] = (
        Path(".pilot/local/local_pilot_report.json"),
        Path(".pilot/local_imported_batch/local_pilot_report.json"),
    )
    preview_links: dict[str, str] = field(default_factory=lambda: {
        "종목 콘텐츠": "/static/preview/index.html",
        "프로필 콘텐츠": "/static/preview/profiles.html",
    })

    @property
    def candidate_dir(self) -> Path:
        return self.output_root / "candidates"

    @property
    def assessment_dir(self) -> Path:
        return self.output_root / "assessment"

    @property
    def dashboard_file(self) -> Path:
        return self.output_root / "dashboard" / "index.html"

    @property
    def candidate_input_review_file(self) -> Path:
        return self.candidate_dir / "candidate_input_review.json"

    @property
    def candidate_queue_file(self) -> Path:
        return self.candidate_dir / "candidate_queue.json"

    @property
    def candidate_gap_file(self) -> Path:
        return self.candidate_dir / "candidate_gap.json"

    @property
    def assessment_file(self) -> Path:
        return self.assessment_dir / "pilot_assessment.json"

    @property
    def manual_profile_file(self) -> Path:
        return self.candidate_dir / "manual_profiles.json"


ARTIFACTS = {
    "candidate_input_review": "candidate_input_review_file",
    "candidate_queue": "candidate_queue_file",
    "candidate_gap": "candidate_gap_file",
    "pilot_assessment": "assessment_file",
}

CANDIDATE_FIELDS = ("ticker", "name", "content_type", "market", "notes")

SNAPSHOT_DIRS = (
    "content_with_market",
    "profile_content",
    "profiles",
    "content",
)


def _artifact_path(config: PilotApiConfig, name: str) -> Path | None:
    attr = ARTIFACTS.get(name)
    if not attr:
        return None
    return getattr(config, attr)


def _ensure_candidate_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()


def _candidate_files_for_rebuild(config: PilotApiConfig) -> list[Path]:
    files = list(config.candidate_files)
    if not files:
        files = [config.candidate_dir / "manual_candidates.csv"]
    for path in files:
        _ensure_candidate_file(path)
    return files


def _profile_paths_for_rebuild(config: PilotApiConfig) -> list[Path]:
    paths = list(config.profile_paths)
    if config.manual_profile_file.exists():
        paths.append(config.manual_profile_file)
    return paths


def append_candidate_seed(config: PilotApiConfig, payload: dict[str, Any]) -> dict[str, Any]:
    """Append a local candidate seed row and rebuild artifacts."""
    ticker = str(payload.get("ticker") or "").strip()
    content_type = str(payload.get("content_type") or "stock").strip().lower()
    market = str(payload.get("market") or "").strip().upper()
    if not ticker:
        raise ValueError("ticker is required")
    if content_type not in {"stock", "etf", "theme"}:
        raise ValueError("content_type must be stock, etf, or theme")
    if market and market not in {"KR", "US", "UNKNOWN"}:
        raise ValueError("market must be KR or US")

    target = _candidate_files_for_rebuild(config)[0]
    with target.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS)
        writer.writerow({
            "ticker": ticker,
            "name": str(payload.get("name") or ticker).strip(),
            "content_type": content_type,
            "market": market or "unknown",
            "notes": str(payload.get("notes") or "").strip(),
        })
    status = rebuild_pilot_artifacts(config)
    return {"added": {"ticker": ticker, "content_type": content_type, "market": market or "unknown"}, "status": status}


def append_manual_profile(config: PilotApiConfig, payload: dict[str, Any]) -> dict[str, Any]:
    """Append a structured local profile JSON row and rebuild artifacts."""
    if not isinstance(payload, dict):
        raise ValueError("profile payload must be an object")
    if not (payload.get("profile_type") or payload.get("asset_type") or payload.get("content_type")):
        raise ValueError("profile_type is required")
    if not (payload.get("ticker") or payload.get("name")):
        raise ValueError("ticker or name is required")

    config.manual_profile_file.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_json(config.manual_profile_file)
    profiles = existing.get("profiles") if isinstance(existing.get("profiles"), list) else []
    profiles.append(payload)
    config.manual_profile_file.write_text(
        json.dumps({"profiles": profiles}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    status = rebuild_pilot_artifacts(config)
    return {"added": {"ticker": payload.get("ticker"), "profile_type": payload.get("profile_type")}, "status": status}


def _clip_text(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _card_text(card: dict[str, Any], limit: int = 190) -> str:
    body = card.get("body") or card.get("headline")
    if body:
        return _clip_text(body, limit)
    bullets = card.get("bullets") or []
    if isinstance(bullets, list):
        return _clip_text(" ".join(str(item) for item in bullets[:3]), limit)
    return ""


def _card_by_id(content: dict[str, Any], card_id: str) -> dict[str, Any]:
    for card in content.get("cards") or []:
        if isinstance(card, dict) and card.get("id") == card_id:
            return card
    return {}


def _type_label(content_type: str) -> str:
    return {"stock": "종목", "etf": "ETF", "theme": "테마"}.get(content_type, content_type or "-")


def _asset_id(ticker: str, content_type: str) -> str:
    raw = f"{content_type}:{ticker}".strip().lower()
    return "".join(char if char.isalnum() else "-" for char in raw).strip("-")


def _content_name(content: dict[str, Any]) -> str:
    data = content.get("composition_data") or {}
    return str(data.get("name") or content.get("name") or content.get("ticker") or "-")


def _ready_visual_count(content: dict[str, Any]) -> tuple[int, int]:
    visuals = [visual for visual in content.get("visuals") or [] if isinstance(visual, dict)]
    ready = sum(1 for visual in visuals if visual.get("status") == "ready")
    return ready, len(visuals)


def load_service_items(config: PilotApiConfig, limit: int = 18) -> list[dict[str, Any]]:
    """Load local content snapshots for the public service surface."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for directory_name in SNAPSHOT_DIRS:
        input_dir = config.output_root / directory_name
        if not input_dir.exists():
            continue
        for snapshot_file in find_content_snapshot_files(input_dir):
            content = _read_json(snapshot_file)
            if content.get("artifact") != "content_snapshot":
                continue
            ticker = str(content.get("ticker") or "").strip()
            content_type = str(content.get("content_type") or "").strip().lower()
            key = f"{content_type}:{ticker.upper()}"
            if not ticker or key in seen:
                continue
            seen.add(key)
            ready_visuals, total_visuals = _ready_visual_count(content)
            gate = content.get("publish_gate") or {}
            items.append({
                "id": _asset_id(ticker, content_type),
                "ticker": ticker,
                "name": _content_name(content),
                "content_type": content_type,
                "type_label": _type_label(content_type),
                "market": content.get("market_adapter") or "-",
                "gate_status": gate.get("status") or "draft",
                "why": _card_text(_card_by_id(content, "why_moved")),
                "what": _card_text(_card_by_id(content, "what_is_it")),
                "composition": _card_text(_card_by_id(content, "composition"), 220),
                "bull_bear": _card_by_id(content, "bull_bear"),
                "ready_visuals": ready_visuals,
                "total_visuals": total_visuals,
                "generated_at": content.get("generated_at"),
                "content": content,
                "path": snapshot_file,
            })
            if len(items) >= limit:
                return items
    return items


def load_service_payload(config: PilotApiConfig) -> dict[str, Any]:
    """Return data used by the Cloudflare-like service surface."""
    status = load_pilot_status(config)
    items = load_service_items(config)
    queue = _read_json(config.candidate_queue_file)
    gap = _read_json(config.candidate_gap_file)
    return {
        "status": status,
        "items": items,
        "queue": queue,
        "gap": gap,
    }


def load_pilot_status(config: PilotApiConfig) -> dict[str, Any]:
    """Return a compact backend status from local artifact JSON files."""
    review = _read_json(config.candidate_input_review_file)
    queue = _read_json(config.candidate_queue_file)
    gap = _read_json(config.candidate_gap_file)
    assessment = _read_json(config.assessment_file)
    local_reports = [_read_json(path) for path in config.local_pilot_reports]
    local_reports = [report for report in local_reports if report.get("artifact") == "local_pilot_report"]
    verdict = assessment.get("verdict") or {}
    queue_summary = queue.get("summary") or {}
    gap_summary = gap.get("summary") or {}
    review_summary = review.get("summary") or {}

    return {
        "schema_version": 1,
        "artifact": "pilot_api_status",
        "llm_policy": "no external LLM API; local artifact backend only",
        "status": verdict.get("status") or "unknown",
        "recommendation": verdict.get("recommendation"),
        "ready_candidates": queue_summary.get("ready_for_local_pilot", 0),
        "target_candidates": queue.get("target_candidates", config.target_candidates),
        "ready_shortfall": gap_summary.get("ready_shortfall", 0),
        "input_review_status": review_summary.get("status") or "missing",
        "candidate_queue_status": (queue.get("gate") or {}).get("status") or "missing",
        "candidate_gap_status": gap.get("status") or "missing",
        "local_pilot_reports": len(local_reports),
        "paths": {
            "candidate_input_review": str(config.candidate_input_review_file),
            "candidate_queue": str(config.candidate_queue_file),
            "candidate_gap": str(config.candidate_gap_file),
            "pilot_assessment": str(config.assessment_file),
            "dashboard": str(config.dashboard_file),
        },
    }


def rebuild_pilot_artifacts(config: PilotApiConfig) -> dict[str, Any]:
    """Rebuild local-only pilot operation artifacts without network or LLM calls."""
    profile_paths = _profile_paths_for_rebuild(config)
    candidate_files = _candidate_files_for_rebuild(config)
    write_candidate_input_review(
        output_dir=config.candidate_dir,
        profile_paths=profile_paths,
        candidate_files=candidate_files,
        market_snapshot_dir=config.market_snapshot_dir,
    )
    write_candidate_queue(
        output_dir=config.candidate_dir,
        reports_dir=config.reports_dir,
        report_limit=config.report_limit,
        profile_paths=profile_paths,
        candidate_files=candidate_files,
        market_snapshot_dir=config.market_snapshot_dir,
        target_candidates=config.target_candidates,
    )
    write_candidate_gap(
        candidate_queue_path=config.candidate_queue_file,
        output_dir=config.candidate_dir,
        target_candidates=config.target_candidates,
    )
    write_assessment(
        list(config.local_pilot_reports),
        output_dir=config.assessment_dir,
        target_candidates=config.target_candidates,
        candidate_queue_path=config.candidate_queue_file,
    )
    render_pilot_dashboard(
        output=config.dashboard_file,
        local_pilot_path=config.local_pilot_reports[0],
        candidate_queue_path=config.candidate_queue_file,
        candidate_gap_path=config.candidate_gap_file,
        assessment_path=config.assessment_file,
        input_review_path=config.candidate_input_review_file,
        preview_links=config.preview_links,
    )
    return load_pilot_status(config)


def _h(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _badge_class(status: Any) -> str:
    text = str(status or "").lower()
    if text in {"ready", "pass", "ready_for_local_pilot"} or text.startswith("continue"):
        return "ok"
    if text in {"fail", "blocked", "required_missing"}:
        return "bad"
    return "warn"


def _composition_preview(content: dict[str, Any]) -> str:
    data = content.get("composition_data") or {}
    content_type = str(content.get("content_type") or "")
    if not isinstance(data, dict):
        return ""

    def bar_row(label: str, value: Any) -> str:
        try:
            pct = max(3.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            pct = 8.0
        return (
            '<div class="bar-row">'
            f'<span>{_h(label)}</span><b>{_h(value)}%</b>'
            f'<i style="width:{pct:.2f}%"></i>'
            '</div>'
        )

    if content_type == "etf":
        rows = []
        for item in (data.get("holdings") or [])[:5]:
            if isinstance(item, dict):
                rows.append(bar_row(item.get("name") or item.get("ticker") or "-", item.get("weight_pct") or 0))
        sectors = []
        for item in (data.get("sectors") or [])[:4]:
            if isinstance(item, dict):
                sectors.append(
                    f'<span class="tag">{_h(item.get("name"))} {_h(item.get("weight_pct"))}%</span>'
                )
        return (
            '<div class="composition-box">'
            '<h4>ETF 구성</h4>'
            f'{"".join(rows) or "<p>보유 종목 데이터 대기</p>"}'
            f'<div class="tag-row">{"".join(sectors)}</div>'
            '</div>'
        )

    if content_type == "theme":
        stages = []
        for item in (data.get("value_chain") or [])[:4]:
            if not isinstance(item, dict):
                continue
            domestic = item.get("domestic_names") or []
            global_names = item.get("global_names") or []
            names = []
            for row in list(domestic[:2]) + list(global_names[:2]):
                if isinstance(row, dict):
                    names.append(row.get("name") or row.get("ticker"))
            stages.append(
                '<article class="stage-card">'
                f'<b>{_h(item.get("stage") or "-")}</b>'
                f'<span>{_h(", ".join(str(name) for name in names if name))}</span>'
                '</article>'
            )
        return (
            '<div class="composition-box">'
            '<h4>테마 밸류체인</h4>'
            f'<div class="stage-strip">{"".join(stages)}</div>'
            '</div>'
        )

    tags = []
    for key in ("products", "business_lines", "regions", "catalysts"):
        for item in (data.get(key) or [])[:3]:
            if isinstance(item, dict):
                tags.append(f'<span class="tag">{_h(item.get("name") or item.get("ticker"))}</span>')
            elif item:
                tags.append(f'<span class="tag">{_h(item)}</span>')
    if not tags:
        return ""
    return (
        '<div class="composition-box">'
        '<h4>종목 위키</h4>'
        f'<div class="tag-row">{"".join(tags[:8])}</div>'
        '</div>'
    )


def _service_card(item: dict[str, Any]) -> str:
    content = item["content"]
    bull_bear = item.get("bull_bear") or {}
    bull = bull_bear.get("bull") or {}
    bear = bull_bear.get("bear") or {}
    status = item.get("gate_status")
    visual_text = f'{item.get("ready_visuals", 0)}/{item.get("total_visuals", 0)}'
    return (
        f'<article class="asset-card" data-type="{_h(item.get("content_type"))}">'
        '<div class="asset-head">'
        '<div>'
        f'<span class="eyebrow">{_h(item.get("type_label"))} · {_h(item.get("market"))}</span>'
        f'<h3>{_h(item.get("name"))}</h3>'
        f'<p class="ticker">{_h(item.get("ticker"))}</p>'
        '</div>'
        f'<span class="badge {_badge_class(status)}">{_h(status)}</span>'
        '</div>'
        '<div class="answer-grid">'
        f'<section><b>무엇인가</b><p>{_h(item.get("what") or "구조화 설명 대기")}</p></section>'
        f'<section><b>왜 움직였나</b><p>{_h(item.get("why") or "원인 카드 대기")}</p></section>'
        '</div>'
        f'{_composition_preview(content)}'
        '<div class="stance-row">'
        f'<div><b>상승</b><span>{_h(_clip_text(bull.get("headline") or bull.get("body") or "근거 대기", 82))}</span></div>'
        f'<div><b>주의</b><span>{_h(_clip_text(bear.get("headline") or bear.get("body") or "리스크 대기", 82))}</span></div>'
        '</div>'
        '<footer>'
        f'<span>visuals {visual_text}</span>'
        f'<span>{_h(_clip_text(item.get("generated_at") or "local", 24))}</span>'
        '</footer>'
        '</article>'
    )


def build_service_html(config: PilotApiConfig) -> str:
    """Cloudflare-like service surface for stock, ETF, and theme content."""
    payload = load_service_payload(config)
    status = payload["status"]
    items = payload["items"]
    queue = payload["queue"]
    gap = payload["gap"]
    by_type = {
        "stock": sum(1 for item in items if item.get("content_type") == "stock"),
        "etf": sum(1 for item in items if item.get("content_type") == "etf"),
        "theme": sum(1 for item in items if item.get("content_type") == "theme"),
    }
    queue_rows = (queue.get("rows") or [])[:9] if queue else []
    gap_rows = (gap.get("slot_plan") or [])[:6] if gap else []
    cards = "".join(_service_card(item) for item in items)
    if not cards:
        cards = (
            '<section class="empty-state">'
            '<h3>콘텐츠 스냅샷이 아직 없습니다</h3>'
            '<p>/console에서 후보를 넣거나 로컬 파일럿을 재빌드하면 여기에 종목, ETF, 테마 카드가 표시됩니다.</p>'
            '</section>'
        )
    queue_html = "".join(
        '<tr>'
        f'<td><b>{_h(row.get("ticker"))}</b><small>{_h(row.get("name"))}</small></td>'
        f'<td>{_h(_type_label(str(row.get("content_type") or "")))}</td>'
        f'<td>{_h(row.get("market"))}</td>'
        f'<td><span class="badge {_badge_class(row.get("status"))}">{_h(row.get("status"))}</span></td>'
        f'<td>{_h(", ".join(row.get("missing_inputs") or []))}</td>'
        '</tr>'
        for row in queue_rows
    )
    gap_html = "".join(
        '<li>'
        f'<b>{_h(row.get("preferred_market"))} {_h(_type_label(str(row.get("preferred_content_type") or "")))}</b>'
        f'<span>{_h(row.get("required_input"))}</span>'
        '</li>'
        for row in gap_rows
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TradingAgents Research Gateway</title>
  <style>
    :root {{
      --bg:#f5f7fa; --panel:#ffffff; --ink:#111827; --muted:#5f6b7a; --line:#d7dde5;
      --nav:#101820; --nav2:#17212b; --orange:#f38020; --blue:#2563eb; --teal:#087f8c;
      --green:#168656; --amber:#9a6700; --red:#b42318; --shadow:0 10px 26px rgba(15,23,42,.08);
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    a {{ color:inherit; text-decoration:none; }}
    .shell {{ min-height:100vh; display:grid; grid-template-columns:240px 1fr; }}
    aside {{ background:var(--nav); color:#d8dee9; padding:18px 14px; position:sticky; top:0; height:100vh; }}
    .brand {{ display:flex; align-items:center; gap:10px; padding:8px 10px 18px; border-bottom:1px solid rgba(255,255,255,.1); }}
    .mark {{ width:30px; height:30px; border-radius:7px; background:linear-gradient(135deg,var(--orange),#ffd166); display:grid; place-items:center; color:#111; font-weight:900; }}
    .brand b {{ display:block; color:#fff; }}
    .brand span {{ display:block; color:#8fa1b3; font-size:11px; margin-top:1px; }}
    nav {{ margin-top:16px; display:grid; gap:4px; }}
    nav a {{ display:flex; justify-content:space-between; align-items:center; padding:9px 10px; border-radius:6px; color:#cbd5e1; }}
    nav a.active, nav a:hover {{ background:var(--nav2); color:#fff; }}
    nav small {{ color:#8fa1b3; font-size:11px; }}
    .side-note {{ position:absolute; left:14px; right:14px; bottom:16px; border:1px solid rgba(255,255,255,.12); border-radius:8px; padding:10px; color:#a7b4c3; font-size:12px; }}
    main {{ min-width:0; }}
    .topbar {{ height:58px; background:#fff; border-bottom:1px solid var(--line); display:flex; align-items:center; gap:12px; padding:0 22px; position:sticky; top:0; z-index:5; }}
    .search {{ flex:1; max-width:520px; border:1px solid var(--line); border-radius:6px; padding:9px 11px; color:var(--muted); background:#fbfcfd; }}
    .pill-btn {{ border:1px solid var(--line); border-radius:6px; padding:8px 10px; background:#fff; color:var(--ink); }}
    .orange {{ background:var(--orange); color:#111; border-color:var(--orange); font-weight:700; }}
    .page {{ padding:22px; }}
    .hero {{ background:#fff; border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow); overflow:hidden; }}
    .hero-main {{ display:grid; grid-template-columns:minmax(0,1.3fr) minmax(280px,.7fr); }}
    .hero-copy {{ padding:24px; }}
    .hero-copy h1 {{ margin:0 0 8px; font-size:28px; letter-spacing:0; }}
    .hero-copy p {{ margin:0; color:var(--muted); max-width:760px; }}
    .hero-status {{ border-left:1px solid var(--line); background:#fbfcfd; padding:18px; display:grid; gap:10px; }}
    .status-row {{ display:flex; justify-content:space-between; gap:12px; border-bottom:1px solid var(--line); padding-bottom:8px; }}
    .status-row:last-child {{ border-bottom:0; padding-bottom:0; }}
    .status-row span {{ color:var(--muted); }}
    .status-row b {{ text-align:right; }}
    .metrics {{ display:grid; grid-template-columns:repeat(5,minmax(120px,1fr)); gap:10px; margin-top:14px; }}
    .metric {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:12px; }}
    .metric span {{ display:block; color:var(--muted); font-size:12px; }}
    .metric b {{ display:block; font-size:22px; margin-top:4px; }}
    .section-head {{ display:flex; align-items:end; justify-content:space-between; gap:12px; margin:24px 0 10px; }}
    .section-head h2 {{ margin:0; font-size:18px; }}
    .section-head p {{ margin:0; color:var(--muted); font-size:13px; }}
    .filters {{ display:flex; gap:6px; flex-wrap:wrap; }}
    .filters button {{ border:1px solid var(--line); background:#fff; border-radius:999px; padding:6px 10px; cursor:pointer; }}
    .filters button.active {{ border-color:var(--orange); background:#fff3e8; }}
    .asset-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr)); gap:12px; }}
    .asset-card {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:15px; box-shadow:0 4px 12px rgba(15,23,42,.04); min-width:0; }}
    .asset-head {{ display:flex; justify-content:space-between; gap:12px; margin-bottom:12px; }}
    .eyebrow {{ color:var(--teal); font-size:12px; font-weight:700; }}
    .asset-card h3 {{ margin:2px 0 0; font-size:18px; letter-spacing:0; }}
    .ticker {{ margin:0; color:var(--muted); font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }}
    .badge {{ display:inline-flex; align-items:center; border-radius:999px; padding:3px 8px; font-size:12px; border:1px solid var(--line); background:#f8fafc; white-space:nowrap; height:max-content; }}
    .badge.ok {{ color:var(--green); background:#ecfdf3; border-color:#b7e4c7; }}
    .badge.warn {{ color:var(--amber); background:#fff7e6; border-color:#ecd08b; }}
    .badge.bad {{ color:var(--red); background:#fff1f0; border-color:#f0b8b2; }}
    .answer-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px; }}
    .answer-grid section {{ border:1px solid var(--line); border-radius:7px; padding:10px; background:#fbfcfd; min-width:0; }}
    .answer-grid b, .composition-box h4, .stance-row b {{ display:block; font-size:12px; color:var(--muted); margin-bottom:5px; }}
    .answer-grid p, .composition-box p {{ margin:0; color:#263241; overflow-wrap:anywhere; }}
    .composition-box {{ border:1px solid var(--line); border-radius:7px; padding:10px; margin-bottom:10px; background:#fff; }}
    .bar-row {{ display:grid; grid-template-columns:1fr auto; gap:8px; align-items:center; margin:7px 0; position:relative; padding-bottom:9px; }}
    .bar-row span {{ min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .bar-row b {{ font-size:12px; color:var(--muted); }}
    .bar-row i {{ position:absolute; left:0; bottom:0; height:4px; border-radius:999px; background:linear-gradient(90deg,var(--orange),var(--blue)); }}
    .tag-row {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }}
    .tag {{ border:1px solid var(--line); border-radius:999px; padding:4px 8px; font-size:12px; background:#f8fafc; }}
    .stage-strip {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:8px; }}
    .stage-card {{ border:1px solid var(--line); border-radius:7px; padding:9px; background:#fbfcfd; }}
    .stage-card b {{ display:block; color:var(--ink); margin-bottom:4px; }}
    .stage-card span {{ display:block; color:var(--muted); font-size:12px; }}
    .stance-row {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
    .stance-row div {{ border:1px solid var(--line); border-radius:7px; padding:9px; background:#fbfcfd; }}
    .stance-row span {{ color:#334155; font-size:13px; }}
    footer {{ display:flex; justify-content:space-between; gap:10px; margin-top:10px; color:var(--muted); font-size:12px; border-top:1px solid var(--line); padding-top:9px; }}
    .ops-grid {{ display:grid; grid-template-columns:minmax(0,1.5fr) minmax(260px,.5fr); gap:12px; }}
    .panel {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:14px; }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{ border-bottom:1px solid var(--line); padding:8px 6px; text-align:left; vertical-align:top; }}
    th {{ color:var(--muted); font-size:12px; }}
    td small {{ display:block; color:var(--muted); }}
    .gap-list {{ list-style:none; padding:0; margin:0; display:grid; gap:8px; }}
    .gap-list li {{ border:1px solid var(--line); border-radius:7px; padding:9px; display:flex; justify-content:space-between; gap:10px; }}
    .gap-list span {{ color:var(--muted); font-size:12px; text-align:right; }}
    .empty-state {{ grid-column:1/-1; background:#fff; border:1px dashed var(--line); border-radius:8px; padding:22px; }}
    @media (max-width:980px) {{
      .shell {{ grid-template-columns:1fr; }}
      aside {{ position:static; height:auto; }}
      .side-note {{ position:static; margin-top:18px; }}
      .hero-main, .ops-grid {{ grid-template-columns:1fr; }}
      .hero-status {{ border-left:0; border-top:1px solid var(--line); }}
      .metrics {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
    }}
    @media (max-width:640px) {{
      .topbar {{ height:auto; flex-wrap:wrap; padding:12px; }}
      .page {{ padding:12px; }}
      .asset-grid {{ grid-template-columns:1fr; }}
      .answer-grid, .stance-row {{ grid-template-columns:1fr; }}
      .metrics {{ grid-template-columns:1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <div class="brand"><div class="mark">TA</div><div><b>Research Gateway</b><span>local edge pilot</span></div></div>
      <nav>
        <a class="active" href="/"><span>Overview</span><small>{len(items)}</small></a>
        <a href="#assets"><span>Assets</span><small>{by_type["stock"]}/{by_type["etf"]}/{by_type["theme"]}</small></a>
        <a href="#queue"><span>Queue</span><small>{_h(status.get("ready_candidates"))}</small></a>
        <a href="/console"><span>Console</span><small>input</small></a>
        <a href="/ops"><span>Ops</span><small>audit</small></a>
        <a href="/api/pilot/service"><span>API</span><small>json</small></a>
      </nav>
      <div class="side-note">외부 LLM 호출 없이 로컬 스냅샷, 후보 큐, 검증 결과만 읽습니다.</div>
    </aside>
    <main>
      <div class="topbar">
        <div class="search">Search symbols, ETFs, themes</div>
        <a class="pill-btn" href="/console">Add candidate</a>
        <a class="pill-btn orange" href="/ops">Pilot status</a>
      </div>
      <div class="page">
        <section class="hero">
          <div class="hero-main">
            <div class="hero-copy">
              <h1>주식·ETF·테마 콘텐츠를 로컬 엣지에서 라우팅합니다</h1>
              <p>방문자는 앤트위키처럼 쉽게 읽고, 운영자는 Cloudflare처럼 후보·검증·콘텐츠 상태를 한 화면에서 봅니다. 지금은 무료/저비용 검증 단계라 API 비용이 드는 LLM 생성은 막아 둔 상태입니다.</p>
            </div>
            <div class="hero-status">
              <div class="status-row"><span>Service status</span><b>{_h(status.get("status"))}</b></div>
              <div class="status-row"><span>Candidate queue</span><b>{_h(status.get("candidate_queue_status"))}</b></div>
              <div class="status-row"><span>Input review</span><b>{_h(status.get("input_review_status"))}</b></div>
              <div class="status-row"><span>Policy</span><b>local only</b></div>
            </div>
          </div>
        </section>

        <section class="metrics" aria-label="service metrics">
          <article class="metric"><span>ready candidates</span><b>{_h(status.get("ready_candidates"))}/{_h(status.get("target_candidates"))}</b></article>
          <article class="metric"><span>shortfall</span><b>{_h(status.get("ready_shortfall"))}</b></article>
          <article class="metric"><span>stocks</span><b>{by_type["stock"]}</b></article>
          <article class="metric"><span>ETFs</span><b>{by_type["etf"]}</b></article>
          <article class="metric"><span>themes</span><b>{by_type["theme"]}</b></article>
        </section>

        <div class="section-head" id="assets">
          <div><h2>콘텐츠 라우트</h2><p>종목, ETF, 테마를 같은 구조로 읽고 구성 시각화를 먼저 봅니다.</p></div>
          <div class="filters" aria-label="asset filters">
            <button class="active" data-filter="all">All</button>
            <button data-filter="stock">Stocks</button>
            <button data-filter="etf">ETF</button>
            <button data-filter="theme">Themes</button>
          </div>
        </div>
        <section class="asset-grid">{cards}</section>

        <div class="section-head" id="queue">
          <div><h2>운영 큐</h2><p>서비스로 확장하기 전에 부족한 입력을 바로 확인합니다.</p></div>
        </div>
        <section class="ops-grid">
          <div class="panel">
            <table>
              <thead><tr><th>Asset</th><th>Type</th><th>Market</th><th>Status</th><th>Missing</th></tr></thead>
              <tbody>{queue_html}</tbody>
            </table>
          </div>
          <div class="panel">
            <h3>다음 슬롯</h3>
            <ul class="gap-list">{gap_html}</ul>
          </div>
        </section>
      </div>
    </main>
  </div>
  <script>
    const buttons = document.querySelectorAll('[data-filter]');
    const cards = document.querySelectorAll('.asset-card');
    buttons.forEach((button) => button.addEventListener('click', () => {{
      buttons.forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      const filter = button.dataset.filter;
      cards.forEach((card) => {{
        card.style.display = filter === 'all' || card.dataset.type === filter ? '' : 'none';
      }});
    }}));
  </script>
</body>
</html>"""


def create_app(config: PilotApiConfig | None = None):
    """Create a FastAPI app for the low-cost pilot backend."""
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles

    config = config or PilotApiConfig()
    app = FastAPI(title="TradingAgents Low-Cost Pilot API")

    preview_dir = config.output_root / "preview"
    if preview_dir.exists():
        app.mount("/static/preview", StaticFiles(directory=preview_dir), name="pilot-preview")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(build_service_html(config))

    @app.get("/console", response_class=HTMLResponse)
    def console() -> HTMLResponse:
        return HTMLResponse(build_console_html())

    @app.get("/ops")
    def ops():
        if config.dashboard_file.exists():
            return FileResponse(config.dashboard_file)
        return HTMLResponse(build_console_html())

    @app.get("/api/pilot/status")
    def status() -> dict[str, Any]:
        return load_pilot_status(config)

    @app.get("/api/pilot/service")
    def service() -> dict[str, Any]:
        payload = load_service_payload(config)
        return {
            "status": payload["status"],
            "items": [
                {
                    "ticker": item["ticker"],
                    "name": item["name"],
                    "content_type": item["content_type"],
                    "market": item["market"],
                    "gate_status": item["gate_status"],
                    "ready_visuals": item["ready_visuals"],
                    "total_visuals": item["total_visuals"],
                    "path": str(item["path"]),
                }
                for item in payload["items"]
            ],
            "queue_summary": (payload["queue"].get("summary") or {}) if payload["queue"] else {},
            "gap_summary": (payload["gap"].get("summary") or {}) if payload["gap"] else {},
        }

    @app.post("/api/pilot/rebuild")
    def rebuild() -> dict[str, Any]:
        return rebuild_pilot_artifacts(config)

    @app.post("/api/pilot/candidate-seeds")
    def candidate_seed(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return append_candidate_seed(config, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/pilot/profiles")
    def profile(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return append_manual_profile(config, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/pilot/artifacts")
    def artifacts() -> dict[str, Any]:
        return {
            "artifacts": [
                {"name": name, "path": str(_artifact_path(config, name))}
                for name in ARTIFACTS
            ],
            "dashboard": str(config.dashboard_file),
        }

    @app.get("/api/pilot/artifacts/{name}")
    def artifact(name: str) -> dict[str, Any]:
        path = _artifact_path(config, name)
        if path is None:
            raise HTTPException(status_code=404, detail="unknown pilot artifact")
        payload = _read_json(path)
        if not payload:
            raise HTTPException(status_code=404, detail="pilot artifact not found")
        return payload

    @app.get("/api/pilot/candidates")
    def candidates() -> dict[str, Any]:
        queue = _read_json(config.candidate_queue_file)
        if not queue:
            raise HTTPException(status_code=404, detail="candidate queue not found")
        return {
            "summary": queue.get("summary") or {},
            "gate": queue.get("gate") or {},
            "rows": queue.get("rows") or [],
        }

    @app.get("/api/pilot/gap")
    def gap() -> dict[str, Any]:
        payload = _read_json(config.candidate_gap_file)
        if not payload:
            raise HTTPException(status_code=404, detail="candidate gap not found")
        return payload

    return app


def build_console_html() -> str:
    """Interactive console served by the pilot API backend."""
    return """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TradingAgents Pilot Console</title>
  <style>
    :root { --paper:#f7f6f0; --panel:#fff; --ink:#202124; --muted:#667085; --line:#d7d3c8; --blue:#146c94; --green:#277a55; --amber:#9a6a00; --red:#b42318; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--paper); color:var(--ink); font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    header { padding:20px clamp(16px,4vw,40px); background:#fff; border-bottom:1px solid var(--line); }
    h1,h2,h3,p { margin-top:0; }
    h1 { font-size:24px; margin-bottom:4px; letter-spacing:0; }
    main { padding:16px clamp(16px,4vw,40px) 44px; }
    section { border-top:1px solid var(--line); padding:18px 0; }
    .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:10px; }
    .metric,.panel { background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:12px; min-width:0; }
    .metric span { display:block; color:var(--muted); font-size:12px; }
    .metric strong { display:block; font-size:21px; margin-top:4px; overflow-wrap:anywhere; }
    .badge { display:inline-flex; min-height:24px; align-items:center; border-radius:999px; padding:3px 9px; border:1px solid var(--line); background:#f3f4f6; font-size:12px; }
    .good { color:var(--green); background:#eef8f1; border-color:#b8dec6; }
    .watch { color:var(--amber); background:#fff7e6; border-color:#efd08a; }
    .bad { color:var(--red); background:#fff1f0; border-color:#f0b8b2; }
    .controls { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:14px; }
    label { display:block; color:var(--muted); font-size:12px; margin:8px 0 4px; }
    input,select,textarea { width:100%; border:1px solid var(--line); border-radius:6px; background:#fff; padding:8px 9px; font:inherit; color:var(--ink); }
    textarea { min-height:154px; resize:vertical; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }
    button { border:1px solid var(--blue); border-radius:6px; background:var(--blue); color:#fff; padding:8px 11px; font:inherit; cursor:pointer; }
    button.secondary { background:#fff; color:var(--blue); }
    button:disabled { opacity:.55; cursor:wait; }
    .row { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:10px; }
    table { width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); border-radius:6px; overflow:hidden; }
    th,td { border-bottom:1px solid var(--line); padding:9px 10px; text-align:left; vertical-align:top; }
    th { color:var(--muted); font-size:12px; background:#fbfaf7; }
    td small { display:block; color:var(--muted); }
    .table-wrap { overflow-x:auto; }
    .message { color:var(--muted); min-height:22px; }
    @media (max-width:760px) { .controls { grid-template-columns:1fr; } th,td { white-space:nowrap; } }
  </style>
</head>
<body>
  <header>
    <h1>TradingAgents Pilot Console</h1>
    <div class="row">
      <span id="statusBadge" class="badge">loading</span>
      <span id="queueBadge" class="badge">queue</span>
      <span id="gapBadge" class="badge">gap</span>
      <button id="rebuildBtn" class="secondary">Rebuild</button>
      <a class="badge" href="/api/pilot/status">status json</a>
      <a class="badge" href="/api/pilot/candidates">candidates json</a>
    </div>
  </header>
  <main>
    <section>
      <h2>현재 상태</h2>
      <div class="grid" id="metrics"></div>
    </section>
    <section>
      <h2>후보 추가</h2>
      <div class="controls">
        <form id="candidateForm" class="panel">
          <h3>Seed row</h3>
          <label>ticker</label><input name="ticker" placeholder="NVDA">
          <label>name</label><input name="name" placeholder="Nvidia">
          <label>content_type</label><select name="content_type"><option>stock</option><option>etf</option><option>theme</option></select>
          <label>market</label><select name="market"><option>US</option><option>KR</option></select>
          <label>notes</label><input name="notes" placeholder="watchlist">
          <div class="row"><button>Add seed</button></div>
        </form>
        <form id="profileForm" class="panel">
          <h3>Profile JSON</h3>
          <textarea name="profile">{ "profile_type": "stock", "ticker": "MSFT", "name": "Microsoft", "currency": "USD", "exchange": "NASDAQ", "products": ["Cloud", "Office"] }</textarea>
          <div class="row"><button>Add profile</button></div>
        </form>
      </div>
      <p class="message" id="message"></p>
    </section>
    <section>
      <h2>후보 큐</h2>
      <div class="table-wrap"><table><thead><tr><th>ticker</th><th>type</th><th>market</th><th>status</th><th>missing</th></tr></thead><tbody id="candidateRows"></tbody></table></div>
    </section>
    <section>
      <h2>추가 슬롯</h2>
      <div class="table-wrap"><table><thead><tr><th>#</th><th>type</th><th>market</th><th>input</th></tr></thead><tbody id="slotRows"></tbody></table></div>
    </section>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    const cls = (s) => ['pass','continue','ready'].includes(String(s)) ? 'badge good' : ['fail','blocked'].includes(String(s)) ? 'badge bad' : 'badge watch';
    async function json(url, opts) {
      const res = await fetch(url, opts);
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || res.statusText);
      return body;
    }
    function metric(label, value) { return `<article class="metric"><span>${label}</span><strong>${value ?? '-'}</strong></article>`; }
    async function refresh() {
      const [status, candidates, gap] = await Promise.all([
        json('/api/pilot/status'),
        json('/api/pilot/candidates'),
        json('/api/pilot/gap')
      ]);
      $('statusBadge').textContent = status.status; $('statusBadge').className = cls(status.status);
      $('queueBadge').textContent = status.candidate_queue_status; $('queueBadge').className = cls(status.candidate_queue_status);
      $('gapBadge').textContent = status.candidate_gap_status; $('gapBadge').className = cls(status.candidate_gap_status);
      $('metrics').innerHTML = [
        metric('ready', `${status.ready_candidates} / ${status.target_candidates}`),
        metric('shortfall', status.ready_shortfall),
        metric('input review', status.input_review_status),
        metric('local reports', status.local_pilot_reports),
        metric('policy', 'local only')
      ].join('');
      $('candidateRows').innerHTML = (candidates.rows || []).map(r => `<tr><td><b>${r.ticker || '-'}</b><small>${r.name || ''}</small></td><td>${r.content_type || '-'}</td><td>${r.market || '-'}</td><td><span class="${cls(r.status)}">${r.status || '-'}</span></td><td>${(r.missing_inputs || []).join(', ') || '-'}</td></tr>`).join('');
      $('slotRows').innerHTML = (gap.slot_plan || []).map(r => `<tr><td>${r.slot}</td><td>${r.preferred_content_type}</td><td>${r.preferred_market}</td><td>${r.required_input}</td></tr>`).join('');
    }
    async function submitCandidate(ev) {
      ev.preventDefault();
      const form = new FormData(ev.currentTarget);
      const payload = Object.fromEntries(form.entries());
      $('message').textContent = 'adding seed...';
      await json('/api/pilot/candidate-seeds', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
      $('message').textContent = 'seed added';
      ev.currentTarget.reset();
      await refresh();
    }
    async function submitProfile(ev) {
      ev.preventDefault();
      const raw = ev.currentTarget.elements.profile.value;
      $('message').textContent = 'adding profile...';
      await json('/api/pilot/profiles', {method:'POST', headers:{'Content-Type':'application/json'}, body:raw});
      $('message').textContent = 'profile added';
      await refresh();
    }
    async function rebuild() {
      $('rebuildBtn').disabled = true; $('message').textContent = 'rebuilding...';
      try { await json('/api/pilot/rebuild', {method:'POST'}); $('message').textContent = 'rebuilt'; await refresh(); }
      finally { $('rebuildBtn').disabled = false; }
    }
    $('candidateForm').addEventListener('submit', submitCandidate);
    $('profileForm').addEventListener('submit', submitProfile);
    $('rebuildBtn').addEventListener('click', rebuild);
    refresh().catch(err => $('message').textContent = err.message);
  </script>
</body>
</html>"""


def main() -> None:
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8652)


if __name__ == "__main__":
    main()
