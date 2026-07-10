#!/usr/bin/env python3
"""Render no-LLM content snapshots as a static HTML preview."""

from __future__ import annotations

import argparse
from pathlib import Path

from tradingagents.content_preview import render_content_preview


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path(".pilot/content_with_market"))
    parser.add_argument("--output", type=Path, default=Path(".pilot/preview/index.html"))
    parser.add_argument("--title", default="TradingAgents Local Content Preview")
    args = parser.parse_args()

    output = render_content_preview(args.input_dir, args.output, title=args.title)
    print(f"wrote: {output}")


if __name__ == "__main__":
    main()
