#!/usr/bin/env python3
"""Generate stock/ETF/theme content snapshots from structured profile JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from tradingagents.content_pilot import (
    attach_market_snapshot,
    content_pilot_row,
    format_content_pilot_table,
    load_market_snapshot_index,
    summarize_content_pilot,
)
from tradingagents.content_profiles import final_state_from_profile, load_profiles
from tradingagents.content_snapshot import build_content_snapshot


def _safe_component(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return normalized.strip("._-") or "profile"


def run_profile_content_pilot(
    profiles_path: Path,
    output_dir: Path | None = None,
    market_snapshot_dir: Path | None = None,
) -> dict:
    profiles = load_profiles(profiles_path)
    market_snapshot_index = load_market_snapshot_index(market_snapshot_dir)
    rows = []
    snapshots = []

    for profile in profiles:
        state, ticker, generated_at = final_state_from_profile(profile)
        attach_market_snapshot(state, ticker, market_snapshot_index)
        content = build_content_snapshot(state, ticker, generated_at)
        report_name = f"{ticker}_{profile.get('profile_type', 'profile')}"
        row = content_pilot_row(Path(report_name), content)
        rows.append(row)
        snapshots.append(content)

        if output_dir:
            target_dir = output_dir / _safe_component(report_name)
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "content_snapshot.json").write_text(
                json.dumps(content, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    payload = {
        "summary": summarize_content_pilot(rows),
        "profiles_path": str(profiles_path),
        "output_dir": str(output_dir) if output_dir else None,
        "market_snapshot_dir": str(market_snapshot_dir) if market_snapshot_dir else None,
        "rows": rows,
    }
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "profile_content_pilot_summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return {"summary": payload["summary"], "rows": rows, "snapshots": snapshots}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, required=True, help="Profile JSON file or directory of profile JSON files.")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--market-snapshot-dir", type=Path, default=None)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a table.")
    args = parser.parse_args()

    result = run_profile_content_pilot(args.profiles, args.output_dir, args.market_snapshot_dir)
    payload = {"summary": result["summary"], "rows": result["rows"]}

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(format_content_pilot_table(result["rows"]))
    print()
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    if args.output_dir:
        print(f"\nWrote profile pilot outputs under {args.output_dir}")


if __name__ == "__main__":
    main()
