#!/usr/bin/env python3
"""Analyze local candidate queue gaps before paid-model comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.candidate_gap import write_candidate_gap


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate-queue",
        type=Path,
        default=Path(".pilot/candidates/candidate_queue.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path(".pilot/candidates"))
    parser.add_argument("--target-candidates", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = write_candidate_gap(
        candidate_queue_path=args.candidate_queue,
        output_dir=args.output_dir,
        target_candidates=args.target_candidates,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    summary = payload.get("summary") or {}
    print(f"status: {payload.get('status')}")
    print(f"reasons: {', '.join(payload.get('reasons') or []) if payload.get('reasons') else 'none'}")
    print(f"ready_for_local_pilot: {summary.get('ready_for_local_pilot', 0)}")
    print(f"ready_shortfall: {summary.get('ready_shortfall', 0)}")
    print(f"wrote: {args.output_dir / 'candidate_gap.json'}")


if __name__ == "__main__":
    main()
