#!/usr/bin/env python3
"""Generate beginner content snapshots from saved reports without LLM calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.content_pilot import (
    DEFAULT_REPORTS_DIR,
    format_content_pilot_table,
    run_content_pilot,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--limit", type=int, default=20, help="Most recent report dirs to process.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional directory for generated content snapshots and pilot summary.",
    )
    parser.add_argument(
        "--write-back",
        action="store_true",
        help="Write content_snapshot.json into each original report directory.",
    )
    parser.add_argument(
        "--market-snapshot-dir",
        type=Path,
        default=None,
        help="Optional directory or JSON file of toss_market_snapshot artifacts to attach.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the pilot payload as JSON instead of a table.",
    )
    args = parser.parse_args()

    result = run_content_pilot(
        args.reports_dir,
        limit=args.limit,
        output_dir=args.output_dir,
        write_back=args.write_back,
        market_snapshot_dir=args.market_snapshot_dir,
    )

    payload = {
        "summary": result["summary"],
        "rows": result["rows"],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(format_content_pilot_table(result["rows"]))
    print()
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    if args.output_dir:
        print(f"\nWrote pilot outputs under {args.output_dir}")


if __name__ == "__main__":
    main()
