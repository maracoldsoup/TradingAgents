#!/usr/bin/env python3
"""Collect a no-LLM Toss market snapshot for content pilots."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from tradingagents.dataflows.toss_market_snapshot import (
    collect_toss_market_snapshot,
    normalize_toss_symbol,
)
from tradingagents.dataflows.toss_securities import merged_env
from tradingagents.dataflows.utils import safe_ticker_component


def _default_output_path(output_dir: Path, symbols: list[str]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_symbols = [
        safe_ticker_component(normalize_toss_symbol(symbol), max_len=32)
        for symbol in symbols
    ]
    return output_dir / f"{'__'.join(safe_symbols)}_{timestamp}.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="+", help="Toss symbols, e.g. 005930.KS AAPL")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--output-dir", type=Path, default=Path(".pilot/toss_market"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--candle-count", type=int, default=60)
    parser.add_argument("--date", default=None, help="Optional market calendar date, YYYY-MM-DD.")
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--json", action="store_true", help="Print the full snapshot.")
    args = parser.parse_args()

    env = merged_env(env_file=args.env_file)
    snapshot = collect_toss_market_snapshot(
        env=env,
        symbols=args.symbols,
        candle_count=args.candle_count,
        trade_date=args.date,
        timeout=args.timeout,
    )

    output = args.output or _default_output_path(args.output_dir, args.symbols)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return

    print(f"wrote: {output}")
    print(f"symbols: {', '.join(snapshot['symbols'])}")
    print(f"llm_used: {snapshot['source_policy']['llm_used']}")
    print(f"coverage: {json.dumps(snapshot['coverage'], ensure_ascii=False)}")
    if snapshot["errors"]:
        print(f"errors: {json.dumps(snapshot['errors'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
