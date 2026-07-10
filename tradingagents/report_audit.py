"""No-LLM audit helpers for saved TradingAgents report directories."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_REPORTS_DIR = Path.home() / ".tradingagents" / "logs" / "reports"
LEVEL_FIELDS = ("entry", "stop", "target", "position_size_pct")
SECTION_FILES = (
    "1_analysts/market.md",
    "1_analysts/sentiment.md",
    "1_analysts/news.md",
    "1_analysts/fundamentals.md",
    "2_research/bull.md",
    "2_research/bear.md",
    "2_research/manager.md",
    "3_trading/trader.md",
    "4_risk/aggressive.md",
    "4_risk/conservative.md",
    "4_risk/neutral.md",
    "5_portfolio/decision.md",
)


@dataclass(frozen=True)
class ReportAudit:
    report_dir: Path
    ticker: str
    asset_type: str
    market_adapter: str
    generated_at: str
    rating: str
    action: str
    bias: str
    has_signal: bool
    level_fields_present: list[str]
    level_fields_missing: list[str]
    section_files_present: int
    section_files_missing: list[str]
    section_chars: int
    dossier_chars: int
    complete_report_chars: int
    source_flags_false: list[str]
    warnings: list[str]

    @property
    def levels_complete(self) -> bool:
        return not self.level_fields_missing

    @property
    def report_name(self) -> str:
        return self.report_dir.name


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _file_size(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8"))
    except OSError:
        return 0


def _infer_ticker_from_dir(report_dir: Path) -> str:
    name = report_dir.name
    if "_" not in name:
        return name
    return name.split("_", 1)[0]


def _infer_market_adapter(ticker: str, snapshot: dict[str, Any]) -> str:
    market = snapshot.get("market_adapter")
    if market:
        return str(market)
    upper = ticker.upper()
    if upper.endswith((".KS", ".KQ")):
        return "KR"
    if "." not in upper and "-" not in upper:
        return "US"
    if upper.endswith("-USD"):
        return "CRYPTO"
    return "GLOBAL"


def content_ready_score(audit: ReportAudit) -> int:
    score = 0
    if audit.has_signal:
        score += 20
    if audit.levels_complete:
        score += 15
    if audit.section_files_present == len(SECTION_FILES):
        score += 20
    if audit.section_chars and audit.section_chars <= 80_000:
        score += 15
    if audit.complete_report_chars:
        score += 10
    if audit.dossier_chars:
        score += 10
    if len(audit.source_flags_false) <= 1:
        score += 10
    return score


def audit_report_dir(report_dir: Path) -> ReportAudit:
    snapshot = _read_json(report_dir / "analysis_snapshot.json")
    signal = _read_json(report_dir / "5_portfolio" / "signal.json")
    has_signal = bool(signal)
    ticker = str(snapshot.get("ticker") or _infer_ticker_from_dir(report_dir))

    levels = signal.get("levels") or {}
    present = [field for field in LEVEL_FIELDS if levels.get(field) not in (None, "")]
    missing = [field for field in LEVEL_FIELDS if field not in present]

    section_missing = [rel for rel in SECTION_FILES if not (report_dir / rel).exists()]
    section_chars = sum(_file_size(report_dir / rel) for rel in SECTION_FILES)

    source_flags = snapshot.get("source_flags") or {}
    false_sources = sorted(key for key, value in source_flags.items() if value is False)

    warnings: list[str] = []
    if not has_signal:
        warnings.append("missing_signal")
    if missing:
        warnings.append("incomplete_levels")
    if section_missing:
        warnings.append("missing_sections")
    if section_chars > 80_000:
        warnings.append("large_agent_outputs")
    if _file_size(report_dir / "dossier.md") > 120_000:
        warnings.append("large_dossier")
    if false_sources:
        warnings.append("source_gaps")

    return ReportAudit(
        report_dir=report_dir,
        ticker=ticker,
        asset_type=str(snapshot.get("asset_type") or "stock"),
        market_adapter=_infer_market_adapter(ticker, snapshot),
        generated_at=str(snapshot.get("generated_at") or ""),
        rating=str(signal.get("rating") or ""),
        action=str(signal.get("action") or ""),
        bias=str(signal.get("bias") or ""),
        has_signal=has_signal,
        level_fields_present=present,
        level_fields_missing=missing,
        section_files_present=len(SECTION_FILES) - len(section_missing),
        section_files_missing=section_missing,
        section_chars=section_chars,
        dossier_chars=_file_size(report_dir / "dossier.md"),
        complete_report_chars=_file_size(report_dir / "complete_report.md"),
        source_flags_false=false_sources,
        warnings=warnings,
    )


def find_report_dirs(reports_dir: Path, limit: int | None) -> list[Path]:
    if not reports_dir.exists():
        return []
    dirs = [path for path in reports_dir.iterdir() if path.is_dir()]
    dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    if limit is not None:
        dirs = dirs[:limit]
    return dirs


def summarize(audits: list[ReportAudit]) -> dict[str, Any]:
    ratings = Counter(audit.rating or "missing" for audit in audits)
    actions = Counter(audit.action or "missing" for audit in audits)
    markets = Counter(audit.market_adapter or "missing" for audit in audits)
    warnings = Counter(warning for audit in audits for warning in audit.warnings)
    level_complete = sum(1 for audit in audits if audit.levels_complete)
    return {
        "reports": len(audits),
        "signals_present": sum(1 for audit in audits if audit.has_signal),
        "levels_complete": level_complete,
        "levels_complete_pct": round(level_complete / len(audits) * 100, 1) if audits else 0.0,
        "avg_section_chars": round(sum(audit.section_chars for audit in audits) / len(audits), 1)
        if audits
        else 0.0,
        "avg_content_ready_score": round(
            sum(content_ready_score(audit) for audit in audits) / len(audits), 1
        )
        if audits
        else 0.0,
        "markets": dict(markets),
        "ratings": dict(ratings),
        "actions": dict(actions),
        "warnings": dict(warnings),
    }


def to_jsonable(audit: ReportAudit) -> dict[str, Any]:
    data = audit.__dict__.copy()
    data["report_dir"] = str(audit.report_dir)
    data["report_name"] = audit.report_name
    data["levels_complete"] = audit.levels_complete
    data["content_ready_score"] = content_ready_score(audit)
    return data


def audit_reports(reports_dir: Path = DEFAULT_REPORTS_DIR, limit: int | None = 20) -> dict[str, Any]:
    report_dirs = find_report_dirs(reports_dir, limit)
    audits = [audit_report_dir(path) for path in report_dirs]
    return {
        "summary": summarize(audits),
        "reports": [to_jsonable(audit) for audit in audits],
    }


def format_table(audits: list[ReportAudit]) -> str:
    headers = [
        "report",
        "ticker",
        "market",
        "rating",
        "action",
        "levels",
        "sections",
        "score",
        "chars",
        "warnings",
    ]
    rows = []
    for audit in audits:
        rows.append([
            audit.report_name,
            audit.ticker,
            audit.market_adapter,
            audit.rating or "-",
            audit.action or "-",
            "ok" if audit.levels_complete else "missing:" + ",".join(audit.level_fields_missing),
            f"{audit.section_files_present}/{len(SECTION_FILES)}",
            str(content_ready_score(audit)),
            str(audit.section_chars),
            ",".join(audit.warnings) if audit.warnings else "ok",
        ])

    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        if rows
        else len(headers[index])
        for index in range(len(headers))
    ]
    lines = [
        "  ".join(headers[index].ljust(widths[index]) for index in range(len(headers))),
        "  ".join("-" * widths[index] for index in range(len(headers))),
    ]
    for row in rows:
        lines.append("  ".join(row[index].ljust(widths[index]) for index in range(len(headers))))
    return "\n".join(lines)
