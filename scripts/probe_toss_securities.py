#!/usr/bin/env python3
"""Safely inspect/probe Toss Securities credentials for read-only data use."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.dataflows.toss_securities import (
    credential_status,
    merged_env,
    read_only_probe,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument(
        "--path",
        default=None,
        help="Optional read-only API path to GET, e.g. /api/v1/prices. Sensitive paths are refused.",
    )
    parser.add_argument("--param", action="append", default=[], help="Query param as key=value.")
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    env = merged_env(env_file=args.env_file)
    status = credential_status(env)
    payload = {
        "credential_status": status.to_dict(),
        "probe": None,
    }

    if args.path:
        params = {}
        for raw in args.param:
            if "=" not in raw:
                raise SystemExit(f"Invalid --param {raw!r}; use key=value.")
            key, value = raw.split("=", 1)
            params[key] = value
        payload["probe"] = read_only_probe(
            env=env,
            path=args.path,
            params=params,
            timeout=args.timeout,
        )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    cred = payload["credential_status"]
    print("credential_status:")
    for key, value in cred.items():
        print(f"- {key}: {value}")
    if payload["probe"] is not None:
        print()
        print("probe:")
        print(json.dumps(payload["probe"], ensure_ascii=False, indent=2))
    elif cred["ready_for_probe"]:
        print()
        print("next_step: probe a documented read-only path, e.g. --path /api/v1/prices --param symbols=005930")
    else:
        print()
        print("next_step: set Toss client_id/client_secret env vars before probing.")


if __name__ == "__main__":
    main()
