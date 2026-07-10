#!/usr/bin/env python3
"""Audit saved TradingAgents report directories without making LLM calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.report_audit import (
    DEFAULT_REPORTS_DIR,
    audit_report_dir,
    find_report_dirs,
    format_table,
    summarize,
    to_jsonable,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--limit", type=int, default=20, help="Most recent report dirs to audit.")
    parser.add_argument("--json-out", type=Path, default=None, help="Optional JSON output path.")
    args = parser.parse_args()

    report_dirs = find_report_dirs(args.reports_dir, args.limit)
    audits = [audit_report_dir(path) for path in report_dirs]
    summary = summarize(audits)

    print(format_table(audits))
    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.json_out:
        payload = {
            "summary": summary,
            "reports": [to_jsonable(audit) for audit in audits],
        }
        args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json_out}")


if __name__ == "__main__":
    main()
