#!/usr/bin/env python3
"""Run the no-LLM local TradingAgents pilot bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.content_pilot import DEFAULT_REPORTS_DIR
from tradingagents.local_pilot import run_local_pilot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--output-dir", type=Path, default=Path(".pilot/local"))
    parser.add_argument("--env-file", type=Path, default=Path(".env.lowcost.example"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--market-snapshot-dir", type=Path, default=None)
    parser.add_argument("--profiles", type=Path, default=Path("docs/examples/content_profiles.sample.json"), help="Profile JSON file or directory of profile JSON files.")
    parser.add_argument("--allow-external-llm", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = run_local_pilot(
        reports_dir=args.reports_dir,
        output_dir=args.output_dir,
        env_file=args.env_file,
        limit=args.limit,
        market_snapshot_dir=args.market_snapshot_dir,
        profiles_path=args.profiles,
        local_only=not args.allow_external_llm,
    )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(f"status: {payload['gate']['status']}")
    print(f"reasons: {', '.join(payload['gate']['reasons']) if payload['gate']['reasons'] else 'none'}")
    print(f"cost_guard: {payload['cost_guard']['status']} {payload['cost_guard']['score']}/100")
    print(f"reports: {payload['report_audit']['summary'].get('reports', 0)}")
    print(f"content_publish_ready_pct: {payload['content_pilot']['summary'].get('publish_ready_pct', 0)}")
    print(f"market_snapshots_attached: {payload['content_pilot']['summary'].get('market_snapshots_attached', 0)}")
    print(f"wrote: {args.output_dir / 'local_pilot_report.json'}")


if __name__ == "__main__":
    main()
