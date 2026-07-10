#!/usr/bin/env python3
"""Build a local-only product assessment from local pilot reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.pilot_assessment import write_assessment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "reports",
        nargs="*",
        type=Path,
        default=[
            Path(".pilot/local/local_pilot_report.json"),
            Path(".pilot/local_imported_batch/local_pilot_report.json"),
        ],
        help="One or more local_pilot_report.json files.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path(".pilot/assessment"))
    parser.add_argument("--target-candidates", type=int, default=20)
    parser.add_argument(
        "--candidate-queue",
        type=Path,
        default=Path(".pilot/candidates/candidate_queue.json"),
        help="Optional candidate_queue.json. If present, its deduplicated ready count drives the scale gate.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = write_assessment(
        args.reports,
        output_dir=args.output_dir,
        target_candidates=args.target_candidates,
        candidate_queue_path=args.candidate_queue,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    verdict = payload["verdict"]
    totals = payload["aggregate"]["totals"]
    print(f"status: {verdict['status']}")
    print(f"recommendation: {verdict['recommendation']}")
    print(f"ready_candidates_used: {verdict['ready_candidates_used']}")
    print(f"candidate_count_source: {verdict['candidate_count_source']}")
    print(f"saved_stock_reports: {totals['saved_stock_reports']}")
    print(f"profile_reports: {totals['profile_reports']}")
    print(f"market_snapshots_attached: {totals['market_snapshots_attached']}")
    print(f"wrote: {args.output_dir / 'pilot_assessment.json'}")


if __name__ == "__main__":
    main()
