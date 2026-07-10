#!/usr/bin/env python3
"""Run the local low-cost pilot API backend."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from tradingagents.pilot_api import PilotApiConfig, create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8652)
    parser.add_argument("--output-root", type=Path, default=Path(".pilot"))
    parser.add_argument("--reports-dir", type=Path, default=None)
    parser.add_argument("--market-snapshot-dir", type=Path, default=Path(".pilot/toss_market"))
    parser.add_argument("--profiles", type=Path, action="append", default=[])
    parser.add_argument("--candidates", type=Path, action="append", default=[])
    parser.add_argument("--target-candidates", type=int, default=20)
    args = parser.parse_args()

    profile_paths = tuple(args.profiles) or PilotApiConfig().profile_paths
    candidate_files = tuple(args.candidates) or PilotApiConfig().candidate_files
    base = PilotApiConfig()
    config = PilotApiConfig(
        reports_dir=args.reports_dir or base.reports_dir,
        output_root=args.output_root,
        target_candidates=args.target_candidates,
        profile_paths=profile_paths,
        candidate_files=candidate_files,
        market_snapshot_dir=args.market_snapshot_dir,
    )
    uvicorn.run(create_app(config), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
