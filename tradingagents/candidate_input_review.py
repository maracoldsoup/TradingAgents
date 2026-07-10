"""Review local candidate/profile inputs before adding them to the pilot queue."""

from __future__ import annotations

import contextlib
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from tradingagents.candidate_queue import _content_type, _infer_market
from tradingagents.content_pilot import load_market_snapshot_index
from tradingagents.content_profiles import normalize_profile
from tradingagents.dataflows.toss_market_snapshot import normalize_toss_symbol


def _read_json_payload(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _as_profile_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        profiles = payload.get("profiles")
        if profiles is None and (
            payload.get("profile_type") or payload.get("asset_type") or payload.get("content_type")
        ):
            profiles = [payload]
    elif isinstance(payload, list):
        profiles = payload
    else:
        profiles = []
    return [profile for profile in profiles or [] if isinstance(profile, dict)]


def _read_candidate_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    payload = _read_json_payload(path)
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
        rows = payload["candidates"]
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def _profile_files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(child for child in path.glob("*.json") if child.is_file())
    return [path]


def _expand_profile_paths(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        expanded = _profile_files(path)
        files.extend(expanded if expanded else [path])
    return files


def _aliases(ticker: str) -> set[str]:
    values = {str(ticker or "").strip().upper()}
    with contextlib.suppress(ValueError):
        values.add(normalize_toss_symbol(ticker))
    return {value for value in values if value}


def _has_market_snapshot(ticker: str, market_snapshot_keys: set[str]) -> bool:
    return bool(_aliases(ticker) & market_snapshot_keys)


def _issue(severity: str, code: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}


def _profile_issues(profile: dict[str, Any], market_snapshot_keys: set[str]) -> tuple[list[dict[str, str]], str]:
    issues: list[dict[str, str]] = []
    content_type = str(profile.get("profile_type") or "")
    ticker = str(profile.get("ticker") or profile.get("name") or "").strip()

    if not ticker:
        issues.append(_issue("error", "missing_ticker", "Profile needs ticker or name."))
    if content_type not in {"stock", "etf", "theme"}:
        issues.append(_issue("error", "unsupported_profile_type", "Profile type must be stock, etf, or theme."))

    if content_type == "stock":
        if not _has_market_snapshot(ticker, market_snapshot_keys):
            issues.append(_issue("warning", "stock_market_snapshot_missing", "Stock profile needs a local market snapshot to become queue-ready."))
        if not (profile.get("products") or profile.get("business_lines") or profile.get("regions")):
            issues.append(_issue("warning", "stock_composition_thin", "Add products, business_lines, or regions for richer composition cards."))
    elif content_type == "etf":
        for field in ("holdings", "sectors", "countries"):
            if not profile.get(field):
                issues.append(_issue("error", f"etf_{field}_missing", f"ETF profile needs {field}."))
    elif content_type == "theme":
        if not profile.get("value_chain"):
            issues.append(_issue("error", "theme_value_chain_missing", "Theme profile needs value_chain."))
        if not (profile.get("domestic_names") or profile.get("global_names")):
            issues.append(_issue("error", "theme_representative_names_missing", "Theme profile needs domestic_names or global_names."))

    errors = sum(1 for issue in issues if issue["severity"] == "error")
    if errors:
        status = "invalid"
    elif any(issue["severity"] == "warning" for issue in issues):
        status = "usable_with_warnings"
    else:
        status = "ready_input"
    return issues, status


def _candidate_issues(row: dict[str, Any]) -> tuple[list[dict[str, str]], str]:
    issues: list[dict[str, str]] = []
    ticker = str(row.get("ticker") or row.get("symbol") or "").strip()
    content_type = _content_type(row.get("content_type") or row.get("profile_type") or row.get("asset_type"))
    market = str(row.get("market") or _infer_market(ticker) or "").strip()

    if not ticker:
        issues.append(_issue("error", "missing_ticker", "Candidate row needs ticker or symbol."))
    if content_type not in {"stock", "etf", "theme"}:
        issues.append(_issue("error", "unsupported_content_type", "Candidate content_type must be stock, etf, or theme."))
    if market not in {"KR", "US", "unknown"}:
        issues.append(_issue("warning", "nonstandard_market", "Use KR or US for the current pilot gates."))

    issues.append(_issue("info", "seed_only", "Candidate seed still needs a saved report or structured profile before it can be queue-ready."))
    errors = sum(1 for issue in issues if issue["severity"] == "error")
    return issues, "invalid" if errors else "seed_valid"


def _review_profile_file(path: Path, market_snapshot_keys: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    payload = _read_json_payload(path)
    if payload is None:
        return [{
            "source_path": str(path),
            "kind": "profile",
            "ticker": "",
            "content_type": "",
            "market": "",
            "status": "invalid",
            "issues": [_issue("error", "profile_file_unreadable", "Profile file is missing or invalid JSON.")],
        }]
    raw_profiles = _as_profile_rows(payload)
    if not raw_profiles:
        return [{
            "source_path": str(path),
            "kind": "profile",
            "ticker": "",
            "content_type": "",
            "market": "",
            "status": "invalid",
            "issues": [_issue("error", "profile_file_empty", "No profile rows found.")],
        }]
    for raw in raw_profiles:
        try:
            profile = normalize_profile(raw)
            issues, status = _profile_issues(profile, market_snapshot_keys)
            ticker = str(profile.get("ticker") or profile.get("name") or "")
            content_type = str(profile.get("profile_type") or "")
            market = _infer_market(ticker, profile)
        except (TypeError, ValueError) as exc:
            issues = [_issue("error", "profile_normalization_failed", str(exc))]
            status = "invalid"
            ticker = str(raw.get("ticker") or raw.get("name") or "")
            content_type = str(raw.get("profile_type") or raw.get("content_type") or raw.get("asset_type") or "")
            market = str(raw.get("market") or "")
        rows.append({
            "source_path": str(path),
            "kind": "profile",
            "ticker": ticker,
            "content_type": content_type,
            "market": market,
            "status": status,
            "issues": issues,
        })
    return rows


def review_candidate_inputs(
    *,
    profile_paths: list[Path] | None = None,
    candidate_files: list[Path] | None = None,
    market_snapshot_dir: Path | None = None,
) -> dict[str, Any]:
    """Review local candidate intake files without network or LLM calls."""
    profile_paths = profile_paths or []
    candidate_files = candidate_files or []
    market_snapshot_keys = set(load_market_snapshot_index(market_snapshot_dir))
    rows: list[dict[str, Any]] = []

    for path in _expand_profile_paths(profile_paths):
        rows.extend(_review_profile_file(path, market_snapshot_keys))

    for path in candidate_files:
        candidate_rows = _read_candidate_rows(path)
        if not candidate_rows and path.exists() and path.suffix.lower() == ".csv":
            rows.append({
                "source_path": str(path),
                "kind": "candidate_seed",
                "ticker": "",
                "content_type": "",
                "market": "",
                "status": "empty",
                "issues": [_issue("info", "candidate_file_empty", "Candidate file has no rows.")],
            })
        elif not candidate_rows:
            rows.append({
                "source_path": str(path),
                "kind": "candidate_seed",
                "ticker": "",
                "content_type": "",
                "market": "",
                "status": "invalid",
                "issues": [_issue("error", "candidate_file_unreadable", "Candidate file is missing, empty, or invalid.")],
            })
        for row in candidate_rows:
            ticker = str(row.get("ticker") or row.get("symbol") or "").strip()
            content_type = _content_type(row.get("content_type") or row.get("profile_type") or row.get("asset_type"))
            issues, status = _candidate_issues(row)
            rows.append({
                "source_path": str(path),
                "kind": "candidate_seed",
                "ticker": ticker,
                "content_type": content_type,
                "market": str(row.get("market") or _infer_market(ticker)),
                "status": status,
                "issues": issues,
            })

    statuses = Counter(row["status"] for row in rows)
    issue_codes = Counter(issue["code"] for row in rows for issue in row["issues"])
    errors = sum(1 for row in rows for issue in row["issues"] if issue["severity"] == "error")
    warnings = sum(1 for row in rows for issue in row["issues"] if issue["severity"] == "warning")
    status = "fail" if errors else "pass"
    if not rows:
        status = "empty"

    return {
        "schema_version": 1,
        "artifact": "candidate_input_review",
        "llm_policy": "no external LLM API; local input files only",
        "market_snapshot_dir": str(market_snapshot_dir) if market_snapshot_dir else None,
        "summary": {
            "status": status,
            "rows": len(rows),
            "errors": errors,
            "warnings": warnings,
            "statuses": dict(statuses),
            "issue_codes": dict(issue_codes),
        },
        "rows": rows,
    }


def build_markdown_review(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Candidate Input Review",
        "",
        f"- status: {summary['status']}",
        f"- rows: {summary['rows']}",
        f"- errors: {summary['errors']}",
        f"- warnings: {summary['warnings']}",
        f"- llm_policy: {payload['llm_policy']}",
        f"- issue_codes: {summary['issue_codes']}",
        "",
        "## Rows",
        "",
        "| kind | ticker | type | market | status | issues |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["rows"]:
        issues = ", ".join(issue["code"] for issue in row["issues"]) or "-"
        lines.append(
            "| {kind} | {ticker} | {content_type} | {market} | {status} | {issues} |".format(
                kind=row.get("kind") or "-",
                ticker=row.get("ticker") or "-",
                content_type=row.get("content_type") or "-",
                market=row.get("market") or "-",
                status=row.get("status") or "-",
                issues=issues,
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_candidate_input_review(
    *,
    output_dir: Path = Path(".pilot/candidates"),
    profile_paths: list[Path] | None = None,
    candidate_files: list[Path] | None = None,
    market_snapshot_dir: Path | None = None,
) -> dict[str, Any]:
    payload = review_candidate_inputs(
        profile_paths=profile_paths,
        candidate_files=candidate_files,
        market_snapshot_dir=market_snapshot_dir,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "candidate_input_review.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "candidate_input_review.md").write_text(
        build_markdown_review(payload),
        encoding="utf-8",
    )
    return payload
