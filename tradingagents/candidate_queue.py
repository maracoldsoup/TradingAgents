"""Local-only candidate queue for scaling the content pilot."""

from __future__ import annotations

import contextlib
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from tradingagents.content_pilot import (
    DEFAULT_REPORTS_DIR,
    find_report_dirs,
    infer_ticker_from_report_dir,
    load_market_snapshot_index,
    read_json,
)
from tradingagents.content_profiles import load_profiles
from tradingagents.dataflows.toss_market_snapshot import normalize_toss_symbol


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _content_type(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"stock", "equity", "company", "종목"}:
        return "stock"
    if raw in {"etf", "fund"}:
        return "etf"
    if raw in {"theme", "thematic", "테마"}:
        return "theme"
    return raw or "stock"


def _ticker_aliases(ticker: str) -> set[str]:
    aliases = {_clean(ticker).upper()}
    with contextlib.suppress(ValueError):
        aliases.add(normalize_toss_symbol(ticker))
    return {alias for alias in aliases if alias}


def _candidate_key(ticker: str, content_type: str) -> str:
    aliases = sorted(_ticker_aliases(ticker))
    symbol = aliases[0] if aliases else _clean(ticker).upper()
    return f"{content_type}:{symbol}"


def _infer_market(ticker: str, profile: dict[str, Any] | None = None) -> str:
    if profile:
        currency = str(profile.get("currency") or "").upper()
        country = str(profile.get("country") or "").lower()
        exchange = str(profile.get("exchange") or "").upper()
        if currency == "USD" or "united states" in country or exchange in {"NASDAQ", "NYSE", "AMEX"}:
            return "US"
        if currency == "KRW" or "korea" in country or exchange in {"KOSPI", "KOSDAQ", "KRX"}:
            return "KR"
    symbol = _clean(ticker).upper()
    if symbol.endswith((".KS", ".KQ", ".KR")) or symbol.isdigit():
        return "KR"
    if symbol.startswith("KR-"):
        return "KR"
    if "-" in symbol and not symbol.endswith((".KS", ".KQ")):
        return "KR"
    return "US" if symbol.isalpha() else "unknown"


def _market_snapshot_ready(ticker: str, market_snapshot_keys: set[str]) -> bool:
    return bool(_ticker_aliases(ticker) & market_snapshot_keys)


def _profile_candidates(profile_paths: list[Path]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for profile_path in profile_paths:
        if not profile_path.exists():
            continue
        for profile in load_profiles(profile_path):
            ticker = _clean(profile.get("ticker") or profile.get("name"))
            if not ticker:
                continue
            content_type = _content_type(profile.get("profile_type"))
            candidates.append({
                "ticker": ticker,
                "name": profile.get("name") or ticker,
                "content_type": content_type,
                "market": _infer_market(ticker, profile),
                "source_type": "profile",
                "source_path": str(profile_path),
                "has_profile": True,
                "has_saved_report": False,
                "notes": "",
            })
    return candidates


def _report_candidates(reports_dir: Path, limit: int | None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for report_dir in find_report_dirs(reports_dir, limit):
        snapshot = read_json(report_dir / "analysis_snapshot.json")
        ticker = _clean(snapshot.get("ticker") or infer_ticker_from_report_dir(report_dir))
        if not ticker:
            continue
        content_type = _content_type(snapshot.get("asset_type") or snapshot.get("content_type"))
        candidates.append({
            "ticker": ticker,
            "name": snapshot.get("name") or ticker,
            "content_type": content_type,
            "market": _infer_market(ticker),
            "source_type": "saved_report",
            "source_path": str(report_dir),
            "has_profile": False,
            "has_saved_report": True,
            "notes": "",
        })
    return candidates


def _raw_candidate_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
        rows = payload["candidates"]
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def _file_candidates(candidate_files: list[Path]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for path in candidate_files:
        for row in _raw_candidate_rows(path):
            ticker = _clean(row.get("ticker") or row.get("symbol"))
            if not ticker:
                continue
            content_type = _content_type(
                row.get("content_type") or row.get("profile_type") or row.get("asset_type")
            )
            candidates.append({
                "ticker": ticker,
                "name": row.get("name") or ticker,
                "content_type": content_type,
                "market": row.get("market") or _infer_market(ticker),
                "source_type": "candidate_file",
                "source_path": str(path),
                "has_profile": False,
                "has_saved_report": False,
                "notes": row.get("notes") or row.get("memo") or "",
            })
    return candidates


def _merge_candidate(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    existing["has_profile"] = bool(existing.get("has_profile") or incoming.get("has_profile"))
    existing["has_saved_report"] = bool(
        existing.get("has_saved_report") or incoming.get("has_saved_report")
    )
    existing["source_types"] = sorted(set(existing.get("source_types", [])) | {incoming["source_type"]})
    existing["source_paths"] = sorted(set(existing.get("source_paths", [])) | {incoming["source_path"]})
    if not existing.get("name") or existing.get("name") == existing.get("ticker"):
        existing["name"] = incoming.get("name") or existing.get("name")
    if existing.get("market") in (None, "", "unknown") and incoming.get("market"):
        existing["market"] = incoming["market"]
    if incoming.get("notes"):
        notes = [note for note in [existing.get("notes"), incoming.get("notes")] if note]
        existing["notes"] = " | ".join(dict.fromkeys(notes))
    return existing


def _finalize_candidate(candidate: dict[str, Any], market_snapshot_keys: set[str]) -> dict[str, Any]:
    ticker = str(candidate.get("ticker") or "")
    content_type = str(candidate.get("content_type") or "stock")
    has_market_snapshot = _market_snapshot_ready(ticker, market_snapshot_keys)
    missing: list[str] = []

    if not candidate.get("has_profile") and not candidate.get("has_saved_report"):
        missing.append("saved_report_or_profile")
    if content_type == "stock" and not has_market_snapshot:
        missing.append("market_snapshot")
    if content_type == "etf" and not candidate.get("has_profile"):
        missing.append("etf_profile_holdings_sectors_countries")
    if content_type == "theme" and not candidate.get("has_profile"):
        missing.append("theme_profile_value_chain_representatives")

    if not missing:
        status = "ready_for_local_pilot"
    elif missing == ["market_snapshot"] and (candidate.get("has_profile") or candidate.get("has_saved_report")):
        status = "needs_market_snapshot"
    elif "saved_report_or_profile" in missing:
        status = "needs_seed_data"
    else:
        status = "needs_structured_profile"

    return {
        **candidate,
        "has_market_snapshot": has_market_snapshot,
        "status": status,
        "missing_inputs": missing,
    }


def build_candidate_queue(
    *,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    report_limit: int | None = 20,
    profile_paths: list[Path] | None = None,
    candidate_files: list[Path] | None = None,
    market_snapshot_dir: Path | None = None,
    target_candidates: int = 20,
) -> dict[str, Any]:
    """Build a local queue from saved reports, profiles, and optional CSV/JSON seeds."""
    profile_paths = profile_paths or []
    candidate_files = candidate_files or []
    market_snapshot_index = load_market_snapshot_index(market_snapshot_dir)
    market_snapshot_keys = set(market_snapshot_index)

    merged: dict[str, dict[str, Any]] = {}
    for incoming in (
        _report_candidates(reports_dir, report_limit)
        + _profile_candidates(profile_paths)
        + _file_candidates(candidate_files)
    ):
        key = _candidate_key(str(incoming.get("ticker") or ""), str(incoming.get("content_type") or "stock"))
        base = {
            "ticker": incoming.get("ticker"),
            "name": incoming.get("name") or incoming.get("ticker"),
            "content_type": incoming.get("content_type") or "stock",
            "market": incoming.get("market") or "unknown",
            "has_profile": False,
            "has_saved_report": False,
            "source_types": [],
            "source_paths": [],
            "notes": "",
        }
        merged[key] = _merge_candidate(merged.get(key, base), incoming)

    rows = [
        _finalize_candidate(candidate, market_snapshot_keys)
        for candidate in merged.values()
    ]
    rows.sort(key=lambda row: (row["status"] != "ready_for_local_pilot", row["market"], row["content_type"], row["ticker"]))

    statuses = Counter(row["status"] for row in rows)
    markets = Counter(str(row.get("market") or "unknown") for row in rows)
    content_types = Counter(str(row.get("content_type") or "stock") for row in rows)
    missing_inputs = Counter(missing for row in rows for missing in row["missing_inputs"])
    source_types = Counter(source for row in rows for source in row.get("source_types", []))
    ready = statuses.get("ready_for_local_pilot", 0)

    if not rows:
        gate_status = "blocked"
        gate_reasons = ["no_candidates"]
    elif ready >= target_candidates and {"stock", "etf", "theme"}.issubset(content_types):
        gate_status = "pass"
        gate_reasons = []
    else:
        gate_status = "needs_more_candidates"
        gate_reasons = []
        if ready < target_candidates:
            gate_reasons.append("ready_candidates_below_target")
        if content_types.get("etf", 0) == 0:
            gate_reasons.append("missing_etf_candidates")
        if content_types.get("theme", 0) == 0:
            gate_reasons.append("missing_theme_candidates")
        if markets.get("US", 0) == 0:
            gate_reasons.append("missing_overseas_candidates")

    return {
        "schema_version": 1,
        "artifact": "candidate_queue",
        "llm_policy": "no external LLM API; local files only",
        "target_candidates": target_candidates,
        "reports_dir": str(reports_dir),
        "report_limit": report_limit,
        "profile_paths": [str(path) for path in profile_paths],
        "candidate_files": [str(path) for path in candidate_files],
        "market_snapshot_dir": str(market_snapshot_dir) if market_snapshot_dir else None,
        "summary": {
            "candidates": len(rows),
            "ready_for_local_pilot": ready,
            "remaining_ready_to_target": max(target_candidates - ready, 0),
            "statuses": dict(statuses),
            "markets": dict(markets),
            "content_types": dict(content_types),
            "missing_inputs": dict(missing_inputs),
            "source_types": dict(source_types),
        },
        "gate": {
            "status": gate_status,
            "reasons": gate_reasons,
            "rule": "At least target_candidates ready local candidates with stock, ETF, theme, and overseas coverage before paid-model comparison.",
        },
        "rows": rows,
    }


def build_markdown_queue(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    gate = payload["gate"]
    lines = [
        "# Candidate Queue",
        "",
        f"- status: {gate['status']}",
        f"- reasons: {', '.join(gate['reasons']) if gate['reasons'] else 'none'}",
        f"- llm_policy: {payload['llm_policy']}",
        f"- target_candidates: {payload['target_candidates']}",
        f"- candidates: {summary['candidates']}",
        f"- ready_for_local_pilot: {summary['ready_for_local_pilot']}",
        f"- remaining_ready_to_target: {summary['remaining_ready_to_target']}",
        f"- markets: {summary['markets']}",
        f"- content_types: {summary['content_types']}",
        f"- missing_inputs: {summary['missing_inputs']}",
        "",
        "## Rows",
        "",
        "| ticker | type | market | status | missing | sources |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["rows"]:
        missing = ", ".join(row.get("missing_inputs") or []) or "-"
        sources = ", ".join(row.get("source_types") or []) or "-"
        lines.append(
            "| {ticker} | {content_type} | {market} | {status} | {missing} | {sources} |".format(
                ticker=row.get("ticker") or "-",
                content_type=row.get("content_type") or "-",
                market=row.get("market") or "-",
                status=row.get("status") or "-",
                missing=missing,
                sources=sources,
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_candidate_queue(
    *,
    output_dir: Path = Path(".pilot/candidates"),
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    report_limit: int | None = 20,
    profile_paths: list[Path] | None = None,
    candidate_files: list[Path] | None = None,
    market_snapshot_dir: Path | None = None,
    target_candidates: int = 20,
) -> dict[str, Any]:
    payload = build_candidate_queue(
        reports_dir=reports_dir,
        report_limit=report_limit,
        profile_paths=profile_paths,
        candidate_files=candidate_files,
        market_snapshot_dir=market_snapshot_dir,
        target_candidates=target_candidates,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "candidate_queue.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "candidate_queue.md").write_text(
        build_markdown_queue(payload),
        encoding="utf-8",
    )
    return payload
