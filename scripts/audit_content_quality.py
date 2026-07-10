#!/usr/bin/env python3
"""Audit no-LLM content snapshot quality."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.content_quality import audit_content_snapshots, find_content_snapshot_files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path(".pilot/content_with_market"))
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = audit_content_snapshots(find_content_snapshot_files(args.input_dir))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    summary = payload["summary"]
    print(f"snapshots: {summary['snapshots']}")
    print(f"pass_pct: {summary['pass_pct']}")
    print(f"avg_score: {summary['avg_score']}")
    print(f"statuses: {json.dumps(summary['statuses'], ensure_ascii=False)}")
    print(f"issue_codes: {json.dumps(summary['issue_codes'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
