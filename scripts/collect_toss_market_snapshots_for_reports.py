#!/usr/bin/env python3
"""Collect Toss market snapshots for recent saved report tickers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.content_pilot import DEFAULT_REPORTS_DIR
from tradingagents.dataflows.toss_securities import merged_env
from tradingagents.toss_report_snapshots import collect_toss_market_snapshots_for_reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--output-dir", type=Path, default=Path(".pilot/toss_market"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--candle-count", type=int, default=60)
    parser.add_argument("--date", default=None, help="Optional market calendar date, YYYY-MM-DD.")
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    env = merged_env(env_file=args.env_file)
    payload = collect_toss_market_snapshots_for_reports(
        env=env,
        reports_dir=args.reports_dir,
        output_dir=args.output_dir,
        output=args.output,
        limit=args.limit,
        candle_count=args.candle_count,
        trade_date=args.date,
        timeout=args.timeout,
        dry_run=args.dry_run,
    )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(f"artifact: {payload['artifact']}")
    print(f"symbols: {', '.join(payload.get('symbols', []))}")
    print(f"llm_used: {payload['source_policy']['llm_used']}")
    print(f"dry_run: {payload['source_policy'].get('network_used') is False}")
    if payload.get("output_file"):
        print(f"wrote: {payload['output_file']}")
    if payload.get("coverage"):
        print(f"coverage: {json.dumps(payload['coverage'], ensure_ascii=False)}")
    if payload.get("errors"):
        print(f"errors: {json.dumps(payload['errors'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
