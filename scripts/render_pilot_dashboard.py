#!/usr/bin/env python3
"""Render the local pilot operating dashboard."""

from __future__ import annotations

import argparse
from pathlib import Path

from tradingagents.pilot_dashboard import render_pilot_dashboard


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".pilot/dashboard/index.html"))
    parser.add_argument("--local-pilot", type=Path, default=Path(".pilot/local/local_pilot_report.json"))
    parser.add_argument("--candidate-queue", type=Path, default=Path(".pilot/candidates/candidate_queue.json"))
    parser.add_argument("--candidate-gap", type=Path, default=Path(".pilot/candidates/candidate_gap.json"))
    parser.add_argument("--input-review", type=Path, default=Path(".pilot/candidates/candidate_input_review.json"))
    parser.add_argument("--assessment", type=Path, default=Path(".pilot/assessment/pilot_assessment.json"))
    parser.add_argument("--content-preview", default="../preview/index.html")
    parser.add_argument("--profile-preview", default="../preview/profiles.html")
    parser.add_argument("--title", default="TradingAgents Local Pilot Dashboard")
    args = parser.parse_args()

    output = render_pilot_dashboard(
        output=args.output,
        local_pilot_path=args.local_pilot,
        candidate_queue_path=args.candidate_queue,
        candidate_gap_path=args.candidate_gap,
        assessment_path=args.assessment,
        input_review_path=args.input_review,
        preview_links={
            "종목 콘텐츠": args.content_preview,
            "프로필 콘텐츠": args.profile_preview,
        },
        title=args.title,
    )
    print(f"wrote: {output}")


if __name__ == "__main__":
    main()
