#!/usr/bin/env python3
"""Import a local ETF holdings CSV/JSON file into a content profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.etf_profile_importer import import_etf_profile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings", type=Path, required=True, help="Local ETF holdings CSV or JSON file.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--issuer", default=None)
    parser.add_argument("--benchmark", default=None)
    parser.add_argument("--expense-ratio-pct", type=float, default=None)
    parser.add_argument("--aum", default=None)
    parser.add_argument("--currency", default=None)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--source", default=None)
    parser.add_argument("--weight-scale", choices=("percent", "fraction", "auto"), default="percent")
    parser.add_argument("--top-n", type=int, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--bare-profile", action="store_true", help="Write only the profile object, not {profiles:[...]}.")
    args = parser.parse_args()

    profile = import_etf_profile(
        holdings_path=args.holdings,
        ticker=args.ticker,
        name=args.name,
        issuer=args.issuer,
        benchmark=args.benchmark,
        expense_ratio_pct=args.expense_ratio_pct,
        aum=args.aum,
        currency=args.currency,
        as_of=args.as_of,
        source=args.source,
        weight_scale=args.weight_scale,
        top_n=args.top_n,
    )
    payload = profile if args.bare_profile else {"profiles": [profile]}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote: {args.output}")
        print(f"holdings: {len(profile.get('holdings') or [])}")
        print(f"sectors: {len(profile.get('sectors') or [])}")
        print(f"countries: {len(profile.get('countries') or [])}")
        return
    print(text)


if __name__ == "__main__":
    main()

