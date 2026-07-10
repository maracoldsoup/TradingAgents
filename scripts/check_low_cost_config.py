#!/usr/bin/env python3
"""Check whether the current TradingAgents env is safe for low-cost pilots."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from tradingagents.cost_guard import assess_low_cost_config, config_from_env, merge_env


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full assessment as JSON.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional env file to assess. Values in the file override the current shell.",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Fail external LLM providers even if their models are cheap.",
    )
    parser.add_argument(
        "--fail-on-risk",
        action="store_true",
        help="Exit non-zero when the assessment status is fail.",
    )
    args = parser.parse_args()

    env = merge_env(os.environ, args.env_file)
    if args.local_only:
        env["TRADINGAGENTS_LOCAL_ONLY"] = "true"
    result = assess_low_cost_config(config_from_env(env))
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"status: {result.status}")
        print(f"score: {result.score}/100")
        print()
        print("findings:")
        for finding in result.findings:
            print(f"- {finding}")
        print()
        print("recommendations:")
        if result.recommendations:
            for recommendation in result.recommendations:
                print(f"- {recommendation}")
        else:
            print("- No changes needed for a low-cost pilot.")

    if args.fail_on_risk and result.status == "fail":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
