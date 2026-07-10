#!/bin/sh
# Dispatches one image between the interactive CLI and the research_gateway
# service/collectors. With no args (the historical default), this falls
# through to the `tradingagents` CLI unchanged — docker-compose.yml's
# existing `tradingagents` service keeps working exactly as before.
set -e

case "$1" in
  serve)
    shift
    exec python scripts/run_service_api.py --host 0.0.0.0 "$@"
    ;;
  collect-rankings)
    shift
    exec python scripts/collect_toss_rankings.py "$@"
    ;;
  collect-market-reports)
    shift
    exec python scripts/collect_toss_market_snapshots_for_reports.py "$@"
    ;;
  build-queue)
    shift
    exec python scripts/build_candidate_queue.py "$@"
    ;;
  analyze-gap)
    shift
    exec python scripts/analyze_candidate_gap.py "$@"
    ;;
  *)
    exec tradingagents "$@"
    ;;
esac
