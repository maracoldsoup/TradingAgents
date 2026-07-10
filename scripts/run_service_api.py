#!/usr/bin/env python3
"""Run the public TradingAgents research service API."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from tradingagents.research_gateway import DEFAULT_ASSET_DIRS, ServiceApiConfig, create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8653)
    parser.add_argument("--assets", type=Path, action="append", default=[])
    parser.add_argument("--candidate-queue", type=Path, default=Path(".pilot/candidates/candidate_queue.json"))
    parser.add_argument("--candidate-gap", type=Path, default=Path(".pilot/candidates/candidate_gap.json"))
    parser.add_argument("--assessment", type=Path, default=Path(".pilot/assessment/pilot_assessment.json"))
    args = parser.parse_args()

    config = ServiceApiConfig(
        asset_dirs=tuple(args.assets) or DEFAULT_ASSET_DIRS,
        candidate_queue_path=args.candidate_queue,
        candidate_gap_path=args.candidate_gap,
        assessment_path=args.assessment,
    )
    uvicorn.run(create_app(config), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
