#!/usr/bin/env python3
"""Import a local theme map CSV/JSON file into a content profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.theme_profile_importer import import_theme_profile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme-map", type=Path, required=True, help="Local theme map CSV or JSON file.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--description", default=None)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--source", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--bare-profile", action="store_true", help="Write only the profile object, not {profiles:[...]}.")
    args = parser.parse_args()

    profile = import_theme_profile(
        theme_map_path=args.theme_map,
        ticker=args.ticker,
        name=args.name,
        description=args.description,
        as_of=args.as_of,
        source=args.source,
    )
    payload = profile if args.bare_profile else {"profiles": [profile]}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote: {args.output}")
        print(f"stages: {len(profile.get('value_chain') or [])}")
        print(f"domestic_names: {len(profile.get('domestic_names') or [])}")
        print(f"global_names: {len(profile.get('global_names') or [])}")
        return
    print(text)


if __name__ == "__main__":
    main()

