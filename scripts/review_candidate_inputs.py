#!/usr/bin/env python3
"""Review local candidate/profile inputs before queueing them."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.candidate_input_review import write_candidate_input_review


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, action="append", default=[])
    parser.add_argument("--candidates", type=Path, action="append", default=[])
    parser.add_argument("--market-snapshot-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path(".pilot/candidates"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = write_candidate_input_review(
        output_dir=args.output_dir,
        profile_paths=args.profiles,
        candidate_files=args.candidates,
        market_snapshot_dir=args.market_snapshot_dir,
    )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    summary = payload["summary"]
    print(f"status: {summary['status']}")
    print(f"rows: {summary['rows']}")
    print(f"errors: {summary['errors']}")
    print(f"warnings: {summary['warnings']}")
    print(f"issue_codes: {json.dumps(summary['issue_codes'], ensure_ascii=False)}")
    print(f"wrote: {args.output_dir / 'candidate_input_review.json'}")


if __name__ == "__main__":
    main()
