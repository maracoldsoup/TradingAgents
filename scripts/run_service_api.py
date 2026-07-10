#!/usr/bin/env python3
"""Run the public TradingAgents research service API."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from tradingagents.research_gateway import create_app
from tradingagents.service_api import DEFAULT_ASSET_DIRS, ServiceApiConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8653)
    parser.add_argument("--assets", type=Path, action="append", default=[])
    parser.add_argument("--candidate-queue", type=Path, default=Path(".pilot/candidates/candidate_queue.json"))
    parser.add_argument("--candidate-gap", type=Path, default=Path(".pilot/candidates/candidate_gap.json"))
    parser.add_argument("--assessment", type=Path, default=Path(".pilot/assessment/pilot_assessment.json"))
    parser.add_argument("--rankings-snapshot-dir", type=Path, default=Path(".pilot/toss_rankings"))
    parser.add_argument(
        "--enable-background-jobs",
        action="store_true",
        help="Run the Toss rankings collector in-process on a timer instead of a separate cron job.",
    )
    parser.add_argument("--rankings-poll-interval", type=float, default=300)
    args = parser.parse_args()

    api_key = os.environ.get("RESEARCH_GATEWAY_API_KEY", "")
    if not api_key:
        print("warning: RESEARCH_GATEWAY_API_KEY not set — /api/* routes are unauthenticated")

    config = ServiceApiConfig(
        asset_dirs=tuple(args.assets) or DEFAULT_ASSET_DIRS,
        candidate_queue_path=args.candidate_queue,
        candidate_gap_path=args.candidate_gap,
        assessment_path=args.assessment,
        rankings_snapshot_dir=args.rankings_snapshot_dir,
        api_key=api_key,
        enable_background_jobs=args.enable_background_jobs,
        rankings_poll_interval_seconds=args.rankings_poll_interval,
    )
    uvicorn.run(create_app(config), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
