#!/usr/bin/env python3
"""Collect a no-LLM Toss rankings snapshot (top gainers/losers, volume)."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from tradingagents.dataflows.toss_rankings import (
    DEFAULT_RANKING_TYPES,
    MARKET_COUNTRIES,
    collect_toss_rankings_snapshot,
)
from tradingagents.dataflows.toss_securities import merged_env


def _default_output_path(output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_dir / f"toss_rankings_{timestamp}.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--output-dir", type=Path, default=Path(".pilot/toss_rankings"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--market",
        action="append",
        dest="market_countries",
        choices=list(MARKET_COUNTRIES),
        help="Repeatable. Default: KR and US.",
    )
    parser.add_argument(
        "--type",
        action="append",
        dest="ranking_types",
        help="Repeatable. Default: TOP_GAINERS and TOP_LOSERS.",
    )
    parser.add_argument("--duration", default="1d")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--include-investment-caution", action="store_true")
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--json", action="store_true", help="Print the full snapshot.")
    args = parser.parse_args()

    env = merged_env(env_file=args.env_file)
    snapshot = collect_toss_rankings_snapshot(
        env=env,
        market_countries=tuple(args.market_countries) if args.market_countries else MARKET_COUNTRIES,
        ranking_types=tuple(args.ranking_types) if args.ranking_types else DEFAULT_RANKING_TYPES,
        duration=args.duration,
        count=args.count,
        exclude_investment_caution=not args.include_investment_caution,
        timeout=args.timeout,
    )

    output = args.output or _default_output_path(args.output_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return

    print(f"wrote: {output}")
    print(f"market_countries: {', '.join(snapshot['market_countries'])}")
    print(f"ranking_types: {', '.join(snapshot['ranking_types'])}")
    print(f"llm_used: {snapshot['source_policy']['llm_used']}")
    print(f"coverage: {json.dumps(snapshot['coverage'], ensure_ascii=False)}")
    if snapshot["errors"]:
        print(f"errors: {json.dumps(snapshot['errors'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
