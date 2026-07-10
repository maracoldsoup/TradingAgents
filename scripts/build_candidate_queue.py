#!/usr/bin/env python3
"""Build a local-only candidate queue for the content pilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.candidate_queue import write_candidate_queue
from tradingagents.content_pilot import DEFAULT_REPORTS_DIR


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--report-limit", type=int, default=20)
    parser.add_argument("--profiles", type=Path, action="append", default=[])
    parser.add_argument("--candidates", type=Path, action="append", default=[])
    parser.add_argument("--market-snapshot-dir", type=Path, default=None)
    parser.add_argument("--target-candidates", type=int, default=20)
    parser.add_argument("--output-dir", type=Path, default=Path(".pilot/candidates"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = write_candidate_queue(
        output_dir=args.output_dir,
        reports_dir=args.reports_dir,
        report_limit=args.report_limit,
        profile_paths=args.profiles,
        candidate_files=args.candidates,
        market_snapshot_dir=args.market_snapshot_dir,
        target_candidates=args.target_candidates,
    )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    summary = payload["summary"]
    gate = payload["gate"]
    print(f"status: {gate['status']}")
    print(f"reasons: {', '.join(gate['reasons']) if gate['reasons'] else 'none'}")
    print(f"candidates: {summary['candidates']}")
    print(f"ready_for_local_pilot: {summary['ready_for_local_pilot']}")
    print(f"remaining_ready_to_target: {summary['remaining_ready_to_target']}")
    print(f"markets: {json.dumps(summary['markets'], ensure_ascii=False)}")
    print(f"content_types: {json.dumps(summary['content_types'], ensure_ascii=False)}")
    print(f"missing_inputs: {json.dumps(summary['missing_inputs'], ensure_ascii=False)}")
    print(f"wrote: {args.output_dir / 'candidate_queue.json'}")


if __name__ == "__main__":
    main()
