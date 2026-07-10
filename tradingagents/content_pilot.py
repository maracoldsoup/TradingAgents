"""No-LLM pilot helpers for turning saved report trees into content snapshots."""

from __future__ import annotations

import contextlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from tradingagents.content_snapshot import build_content_snapshot
from tradingagents.dataflows.toss_market_snapshot import normalize_toss_symbol

DEFAULT_REPORTS_DIR = Path.home() / ".tradingagents" / "logs" / "reports"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def infer_ticker_from_report_dir(report_dir: Path) -> str:
    name = report_dir.name
    if "_" not in name:
        return name
    return name.split("_", 1)[0]


def find_report_dirs(reports_dir: Path = DEFAULT_REPORTS_DIR, limit: int | None = 20) -> list[Path]:
    if not reports_dir.exists():
        return []
    dirs = [
        path
        for path in reports_dir.iterdir()
        if path.is_dir()
        and (
            (path / "analysis_snapshot.json").exists()
            or (path / "5_portfolio" / "signal.json").exists()
            or (path / "complete_report.md").exists()
        )
    ]
    dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    if limit is not None:
        return dirs[:limit]
    return dirs


def generated_at_from_snapshot(snapshot: dict[str, Any]) -> datetime | None:
    raw = snapshot.get("generated_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _ticker_candidates(ticker: str) -> set[str]:
    candidates = {str(ticker or "").strip().upper()}
    with contextlib.suppress(ValueError):
        candidates.add(normalize_toss_symbol(ticker))
    return {candidate for candidate in candidates if candidate}


def _market_snapshot_symbols(snapshot: dict[str, Any]) -> set[str]:
    symbols: set[str] = set()
    for symbol in snapshot.get("symbols") or []:
        if isinstance(symbol, str):
            symbols.update(_ticker_candidates(symbol))
    for row in snapshot.get("stocks") or []:
        if isinstance(row, dict) and row.get("symbol"):
            symbols.update(_ticker_candidates(str(row["symbol"])))
    for row in snapshot.get("prices") or []:
        if isinstance(row, dict) and row.get("symbol"):
            symbols.update(_ticker_candidates(str(row["symbol"])))
    candles = snapshot.get("candles") or {}
    if isinstance(candles, dict):
        for symbol in candles:
            symbols.update(_ticker_candidates(str(symbol)))
    return symbols


def load_market_snapshot_index(path: Path | None) -> dict[str, tuple[dict[str, Any], Path]]:
    """Index saved market snapshots by symbol.

    The index is local-file only: it does not call APIs and does not invoke an
    LLM. Later files win when multiple snapshots contain the same symbol.
    """
    if path is None or not path.exists():
        return {}
    files = [path] if path.is_file() else sorted(path.glob("*.json"))
    index: dict[str, tuple[dict[str, Any], Path]] = {}
    for file_path in files:
        snapshot = read_json(file_path)
        if snapshot.get("artifact") != "toss_market_snapshot":
            continue
        for symbol in _market_snapshot_symbols(snapshot):
            index[symbol] = (snapshot, file_path)
    return index


def attach_market_snapshot(
    state: dict[str, Any],
    ticker: str,
    market_snapshot_index: dict[str, tuple[dict[str, Any], Path]] | None,
) -> None:
    if not market_snapshot_index:
        return
    for candidate in _ticker_candidates(ticker):
        match = market_snapshot_index.get(candidate)
        if match:
            snapshot, file_path = match
            state["market_snapshot"] = snapshot
            state["market_snapshot_file"] = str(file_path)
            return


def final_state_from_report_dir(
    report_dir: Path,
    market_snapshot_index: dict[str, tuple[dict[str, Any], Path]] | None = None,
) -> tuple[dict[str, Any], str, datetime | None]:
    """Reconstruct the subset of final_state needed for content publishing.

    The function only reads saved markdown and JSON artifacts. It makes no
    network calls and does not invoke an LLM.
    """
    snapshot = read_json(report_dir / "analysis_snapshot.json")
    signal = read_json(report_dir / "5_portfolio" / "signal.json")
    ticker = str(snapshot.get("ticker") or infer_ticker_from_report_dir(report_dir))

    investment_debate_state = {
        "bull_history": read_text(report_dir / "2_research" / "bull.md"),
        "bear_history": read_text(report_dir / "2_research" / "bear.md"),
        "judge_decision": read_text(report_dir / "2_research" / "manager.md"),
    }
    risk_debate_state = {
        "aggressive_history": read_text(report_dir / "4_risk" / "aggressive.md"),
        "conservative_history": read_text(report_dir / "4_risk" / "conservative.md"),
        "neutral_history": read_text(report_dir / "4_risk" / "neutral.md"),
        "judge_decision": read_text(report_dir / "5_portfolio" / "decision.md"),
    }

    state: dict[str, Any] = {
        "asset_type": snapshot.get("asset_type", "stock"),
        "trade_date": snapshot.get("trade_date"),
        "instrument_context": snapshot.get("instrument_context"),
        "market_report": read_text(report_dir / "1_analysts" / "market.md"),
        "sentiment_report": read_text(report_dir / "1_analysts" / "sentiment.md"),
        "news_report": read_text(report_dir / "1_analysts" / "news.md"),
        "fundamentals_report": read_text(report_dir / "1_analysts" / "fundamentals.md"),
        "investment_debate_state": investment_debate_state,
        "trader_investment_plan": read_text(report_dir / "3_trading" / "trader.md"),
        "risk_debate_state": risk_debate_state,
        "final_trade_decision": risk_debate_state["judge_decision"],
    }
    if signal:
        state["final_trade_signal"] = signal
    attach_market_snapshot(state, ticker, market_snapshot_index)

    return state, ticker, generated_at_from_snapshot(snapshot)


def build_content_snapshot_from_report_dir(
    report_dir: Path,
    market_snapshot_index: dict[str, tuple[dict[str, Any], Path]] | None = None,
) -> dict[str, Any]:
    state, ticker, generated_at = final_state_from_report_dir(report_dir, market_snapshot_index)
    return build_content_snapshot(state, ticker, generated_at)


def content_pilot_row(report_dir: Path, content: dict[str, Any]) -> dict[str, Any]:
    gate = content.get("publish_gate") or {}
    cards = content.get("cards") or []
    visuals = content.get("visuals") or []
    ready_cards = sum(1 for card in cards if card.get("status") == "ready")
    ready_visuals = sum(1 for visual in visuals if visual.get("status") == "ready")
    required_missing = [
        visual.get("id")
        for visual in visuals
        if visual.get("status") == "required_missing"
    ]
    market_data = content.get("market_data") or {}
    price_trend = next((visual for visual in visuals if visual.get("id") == "price_trend"), {})
    volume_change = next((visual for visual in visuals if visual.get("id") == "volume_change"), {})
    return {
        "report": report_dir.name,
        "ticker": content.get("ticker"),
        "market": content.get("market_adapter"),
        "content_type": content.get("content_type"),
        "publish_status": gate.get("status"),
        "market_data_source": market_data.get("source"),
        "market_snapshot_file": market_data.get("snapshot_file"),
        "market_candle_count": market_data.get("candle_count", 0),
        "price_trend_status": price_trend.get("status"),
        "volume_change_status": volume_change.get("status"),
        "ready_cards": ready_cards,
        "cards": len(cards),
        "ready_visuals": ready_visuals,
        "visuals": len(visuals),
        "required_missing_visuals": [value for value in required_missing if value],
        "warnings": gate.get("warnings") or [],
        "reasons": gate.get("reasons") or [],
    }


def summarize_content_pilot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(str(row.get("publish_status") or "missing") for row in rows)
    markets = Counter(str(row.get("market") or "missing") for row in rows)
    content_types = Counter(str(row.get("content_type") or "missing") for row in rows)
    missing_visuals = Counter(
        visual
        for row in rows
        for visual in row.get("required_missing_visuals", [])
    )
    warnings = Counter(warning for row in rows for warning in row.get("warnings", []))
    market_snapshots_attached = sum(1 for row in rows if row.get("market_snapshot_file"))
    price_trend_ready = sum(1 for row in rows if row.get("price_trend_status") == "ready")
    volume_change_ready = sum(1 for row in rows if row.get("volume_change_status") == "ready")
    total = len(rows)
    ready = statuses.get("ready", 0)
    return {
        "reports": total,
        "publish_ready": ready,
        "publish_ready_pct": round(ready / total * 100, 1) if total else 0.0,
        "statuses": dict(statuses),
        "markets": dict(markets),
        "content_types": dict(content_types),
        "missing_visuals": dict(missing_visuals),
        "warnings": dict(warnings),
        "market_snapshots_attached": market_snapshots_attached,
        "price_trend_ready": price_trend_ready,
        "volume_change_ready": volume_change_ready,
    }


def format_content_pilot_table(rows: list[dict[str, Any]]) -> str:
    headers = [
        "report",
        "ticker",
        "market",
        "type",
        "status",
        "cards",
        "visuals",
        "market_data",
        "missing",
        "warnings",
    ]
    table_rows = []
    for row in rows:
        table_rows.append([
            str(row.get("report") or "-"),
            str(row.get("ticker") or "-"),
            str(row.get("market") or "-"),
            str(row.get("content_type") or "-"),
            str(row.get("publish_status") or "-"),
            f"{row.get('ready_cards', 0)}/{row.get('cards', 0)}",
            f"{row.get('ready_visuals', 0)}/{row.get('visuals', 0)}",
            str(row.get("market_candle_count") or "-"),
            ",".join(row.get("required_missing_visuals", [])) or "-",
            ",".join(row.get("warnings", [])) or "-",
        ])

    widths = [
        max(len(headers[index]), *(len(row[index]) for row in table_rows))
        if table_rows
        else len(headers[index])
        for index in range(len(headers))
    ]
    lines = [
        "  ".join(headers[index].ljust(widths[index]) for index in range(len(headers))),
        "  ".join("-" * widths[index] for index in range(len(headers))),
    ]
    for row in table_rows:
        lines.append("  ".join(row[index].ljust(widths[index]) for index in range(len(headers))))
    return "\n".join(lines)


def run_content_pilot(
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    *,
    limit: int | None = 20,
    output_dir: Path | None = None,
    write_back: bool = False,
    market_snapshot_dir: Path | None = None,
) -> dict[str, Any]:
    report_dirs = find_report_dirs(reports_dir, limit)
    market_snapshot_index = load_market_snapshot_index(market_snapshot_dir)
    rows: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []

    for report_dir in report_dirs:
        content = build_content_snapshot_from_report_dir(report_dir, market_snapshot_index)
        row = content_pilot_row(report_dir, content)
        rows.append(row)
        snapshots.append(content)

        if write_back:
            (report_dir / "content_snapshot.json").write_text(
                json.dumps(content, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if output_dir:
            target_dir = output_dir / report_dir.name
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "content_snapshot.json").write_text(
                json.dumps(content, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    summary = summarize_content_pilot(rows)
    payload = {
        "summary": summary,
        "reports_dir": str(reports_dir),
        "write_back": write_back,
        "output_dir": str(output_dir) if output_dir else None,
        "market_snapshot_dir": str(market_snapshot_dir) if market_snapshot_dir else None,
        "rows": rows,
    }
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "content_pilot_summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return {"summary": summary, "rows": rows, "snapshots": snapshots}
