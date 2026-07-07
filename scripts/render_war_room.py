#!/usr/bin/env python3
"""Render a standalone war-room HTML file for a saved report directory."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.war_room import main


if __name__ == "__main__":
    raise SystemExit(main())
