#!/usr/bin/env python3
"""Phase 4-3: 재현성(반복 실행 분산) 측정.

같은 종목·같은 날짜로 파이프라인을 N회 돌려 등급·가격 레벨이 얼마나
흔들리는지 측정한다. 결정이 회차마다 다르면 백테스트 결과도 난수이므로,
백테스트(4-2) 착수 전에 이 수치부터 확보한다.

사용법 (저장소 루트, .env 세팅 상태):

    python scripts/measure_repeatability.py 005930.KS --runs 5
    python scripts/measure_repeatability.py NVDA --date 2026-07-08 --runs 3

비용 주의: 1회 = LLM 30여 회 호출. 5회면 유료 티어 기준으로도 몇 분·몇 센트가
아니라 수십 분·상응하는 토큰이 든다. --runs 는 3~5를 권장.

출력: 회차별 표 + 일치율/분산 요약 + JSON 저장(repeatability_<ticker>_<date>.json)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date as _date
from pathlib import Path


def run_once(ticker: str, trade_date: str) -> dict:
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph(debug=False, config=DEFAULT_CONFIG.copy())
    final_state, _decision = graph.propagate(ticker, trade_date)
    signal = final_state.get("final_trade_signal") or {}
    levels = signal.get("levels") or {}
    return {
        "rating": signal.get("rating"),
        "action": signal.get("action"),
        "score": signal.get("score"),
        "entry": levels.get("entry"),
        "stop": levels.get("stop"),
        "target": levels.get("target"),
        "position_size_pct": levels.get("position_size_pct"),
    }


def coefficient_of_variation(values: list[float]) -> float | None:
    vals = [v for v in values if isinstance(v, (int, float))]
    if len(vals) < 2:
        return None
    mean = statistics.mean(vals)
    if mean == 0:
        return None
    return statistics.stdev(vals) / mean


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticker")
    parser.add_argument("--date", default=_date.today().isoformat())
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()

    results: list[dict] = []
    for i in range(1, args.runs + 1):
        print(f"\n=== run {i}/{args.runs} — {args.ticker} @ {args.date} ===", flush=True)
        try:
            r = run_once(args.ticker, args.date)
        except Exception as exc:  # 한 회차 실패는 기록하고 계속
            print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            r = {"error": str(exc)}
        results.append(r)
        print("  →", json.dumps(r, ensure_ascii=False))

    ok = [r for r in results if "error" not in r]
    print("\n" + "=" * 60)
    print(f"재현성 요약 — {args.ticker} @ {args.date} ({len(ok)}/{args.runs} 성공)")
    print("=" * 60)

    summary: dict = {"ticker": args.ticker, "date": args.date, "runs": results}
    if ok:
        ratings = [r["rating"] for r in ok]
        mode_rating = max(set(ratings), key=ratings.count)
        agreement = ratings.count(mode_rating) / len(ratings)
        print(f"등급 분포: {ratings}")
        print(f"최빈 등급 일치율: {agreement:.0%}  ({mode_rating})")
        summary["rating_agreement"] = agreement
        summary["mode_rating"] = mode_rating

        for field in ("entry", "stop", "target", "position_size_pct"):
            vals = [r[field] for r in ok if r.get(field) is not None]
            missing = len(ok) - len(vals)
            cv = coefficient_of_variation(vals)
            cv_txt = f"CV {cv:.1%}" if cv is not None else "CV n/a"
            print(f"{field:>18}: {vals}  결측 {missing}  {cv_txt}")
            summary[f"{field}_cv"] = cv
            summary[f"{field}_missing"] = missing

        # 4-1 완료 판정 보조: Hold가 아닌데 레벨 결측이면 경고
        non_hold = [r for r in ok if r.get("action") != "Hold"]
        misses = sum(1 for r in non_hold if r.get("entry") is None or r.get("stop") is None)
        if misses:
            print(f"\n⚠ Hold가 아닌 결정 {len(non_hold)}건 중 {misses}건에서 레벨 결측 — 4-1 판정 기준 미달")
        else:
            print(f"\n✓ 레벨 결측 0 (Hold 제외 {len(non_hold)}건) — 4-1 판정 기준 충족 방향")

    out = Path(f"repeatability_{args.ticker.replace('.','_')}_{args.date}.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
