"""Batch Toss market snapshot collection for saved report tickers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from tradingagents.content_pilot import (
    DEFAULT_REPORTS_DIR,
    find_report_dirs,
    infer_ticker_from_report_dir,
    read_json,
)
from tradingagents.dataflows.toss_market_snapshot import (
    ReadOnlyGetter,
    collect_toss_market_snapshot,
    normalize_toss_symbol,
)
from tradingagents.dataflows.utils import safe_ticker_component


def report_symbol_plan(reports_dir: Path = DEFAULT_REPORTS_DIR, limit: int | None = 20) -> list[dict[str, Any]]:
    by_symbol: dict[str, dict[str, Any]] = {}
    for report_dir in find_report_dirs(reports_dir, limit):
        snapshot = read_json(report_dir / "analysis_snapshot.json")
        ticker = str(snapshot.get("ticker") or infer_ticker_from_report_dir(report_dir))
        try:
            symbol = normalize_toss_symbol(ticker)
        except ValueError:
            continue
        row = by_symbol.setdefault(
            symbol,
            {
                "symbol": symbol,
                "tickers": [],
                "reports": [],
                "asset_types": [],
            },
        )
        if ticker not in row["tickers"]:
            row["tickers"].append(ticker)
        row["reports"].append(report_dir.name)
        asset_type = str(snapshot.get("asset_type") or "stock")
        if asset_type not in row["asset_types"]:
            row["asset_types"].append(asset_type)
    return list(by_symbol.values())


def _default_output_path(output_dir: Path, symbols: list[str], generated_at: datetime) -> Path:
    timestamp = generated_at.strftime("%Y%m%d_%H%M%S")
    label = "__".join(safe_ticker_component(symbol, max_len=32) for symbol in symbols[:6])
    if len(symbols) > 6:
        label += f"__plus{len(symbols) - 6}"
    label = label or "reports"
    return output_dir / f"reports_{label}_{timestamp}.json"


def build_dry_run_payload(
    *,
    reports_dir: Path,
    limit: int | None,
    plan: list[dict[str, Any]],
    generated_at: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact": "toss_market_snapshot_plan",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "reports_dir": str(reports_dir),
        "limit": limit,
        "symbols": [row["symbol"] for row in plan],
        "report_symbol_map": plan,
        "source_policy": {
            "llm_used": False,
            "network_used": False,
            "scope": "dry-run only; no Toss API request was made",
        },
    }


def collect_toss_market_snapshots_for_reports(
    *,
    env: Mapping[str, str],
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    output_dir: Path = Path(".pilot/toss_market"),
    output: Path | None = None,
    limit: int | None = 20,
    candle_count: int = 60,
    trade_date: str | None = None,
    timeout: float = 10,
    dry_run: bool = False,
    getter: ReadOnlyGetter | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now()
    plan = report_symbol_plan(reports_dir, limit)
    symbols = [row["symbol"] for row in plan]

    if dry_run:
        return build_dry_run_payload(
            reports_dir=reports_dir,
            limit=limit,
            plan=plan,
            generated_at=generated_at,
        )
    if not symbols:
        raise ValueError("No report tickers found for Toss market snapshot collection.")

    snapshot = collect_toss_market_snapshot(
        env=env,
        symbols=symbols,
        candle_count=candle_count,
        trade_date=trade_date,
        timeout=timeout,
        getter=getter,
        generated_at=generated_at,
    )
    snapshot["report_symbol_map"] = plan

    output_path = output or _default_output_path(output_dir, symbols, generated_at)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    snapshot["output_file"] = str(output_path)
    return snapshot
