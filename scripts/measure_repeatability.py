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


def run_once(ticker: str, trade_date: str, temperature: float | None = None) -> dict:
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    config = DEFAULT_CONFIG.copy()
    if temperature is not None:
        config["temperature"] = temperature
    graph = TradingAgentsGraph(debug=False, config=config)
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
    parser.add_argument("ticker", nargs="?",
                        help="측정할 종목. 생략하고 --list / --compare 사용 가능")
    parser.add_argument("--date", default=_date.today().isoformat())
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--temperature", type=float, default=None,
                        help="이번 측정의 샘플링 온도 (예: 0.2). 미지정 시 .env/기본값")
    parser.add_argument("--list", action="store_true",
                        help="저장된 재현성 결과 파일을 찾아 요약표로 출력")
    parser.add_argument("--compare", nargs=2, metavar=("A", "B"),
                        help="결과 JSON 두 개를 나란히 비교")
    args = parser.parse_args()

    if args.list:
        return list_results()
    if args.compare:
        return compare_results(Path(args.compare[0]), Path(args.compare[1]))
    if not args.ticker:
        parser.error("ticker가 필요합니다 (또는 --list / --compare)")

    results: list[dict] = []
    for i in range(1, args.runs + 1):
        print(f"\n=== run {i}/{args.runs} — {args.ticker} @ {args.date} ===", flush=True)
        try:
            r = run_once(args.ticker, args.date, args.temperature)
        except Exception as exc:  # 한 회차 실패는 기록하고 계속
            print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            r = {"error": str(exc)}
        results.append(r)
        print("  →", json.dumps(r, ensure_ascii=False))

    ok = [r for r in results if "error" not in r]
    print("\n" + "=" * 60)
    print(f"재현성 요약 — {args.ticker} @ {args.date} ({len(ok)}/{args.runs} 성공)")
    print("=" * 60)

    from tradingagents.default_config import DEFAULT_CONFIG
    effective_temp = args.temperature if args.temperature is not None else DEFAULT_CONFIG.get("temperature")
    summary: dict = {
        "ticker": args.ticker,
        "date": args.date,
        "temperature": effective_temp,
        "runs": results,
    }
    print(f"온도 설정: {effective_temp if effective_temp is not None else '프로바이더 기본값'}")
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

    temp_tag = f"_t{args.temperature}" if args.temperature is not None else ""
    out = Path(f"repeatability_{args.ticker.replace('.','_')}_{args.date}{temp_tag}.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out}")


def _find_result_files() -> list[Path]:
    """레포 루트·홈·현재 위치에서 재현성 결과를 전부 수집."""
    seen: dict[str, Path] = {}
    for base in (Path.cwd(), Path.home(), Path.home() / "TradingAgents"):
        if not base.exists():
            continue
        for f in base.glob("repeatability_*.json"):
            seen[str(f.resolve())] = f.resolve()
    return sorted(seen.values(), key=lambda f: f.stat().st_mtime, reverse=True)


def list_results() -> None:
    files = _find_result_files()
    if not files:
        print("저장된 재현성 결과가 없습니다. 먼저 측정을 실행하세요.")
        return
    print(f"{'파일':<58} {'온도':>6} {'일치율':>7} {'최빈등급':>12}")
    print("-" * 90)
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        temp = d.get("temperature")
        agree = d.get("rating_agreement")
        print(f"{f.name:<58} {str(temp) if temp is not None else '기본':>6} "
              f"{f'{agree:.0%}' if agree is not None else 'n/a':>7} "
              f"{d.get('mode_rating') or '-':>12}")
    print(f"\n총 {len(files)}건. 비교: --compare <A> <B>")


def compare_results(a: Path, b: Path) -> None:
    da = json.loads(a.read_text(encoding="utf-8"))
    db = json.loads(b.read_text(encoding="utf-8"))
    rows = [
        ("온도", da.get("temperature"), db.get("temperature")),
        ("등급 일치율", da.get("rating_agreement"), db.get("rating_agreement")),
        ("최빈 등급", da.get("mode_rating"), db.get("mode_rating")),
    ]
    for field in ("entry", "stop", "target", "position_size_pct"):
        rows.append((f"{field} CV", da.get(f"{field}_cv"), db.get(f"{field}_cv")))
        rows.append((f"{field} 결측", da.get(f"{field}_missing"), db.get(f"{field}_missing")))
    def fmt(name: str, v) -> str:
        if v is None:
            return "-"
        # 비율 성격의 필드만 퍼센트로 (온도 0.2가 20%로 찍히는 사고 방지)
        if isinstance(v, float) and ("일치율" in name or "CV" in name):
            return f"{v:.1%}"
        return str(v)

    print(f"{'항목':<22} {a.name[:28]:>30} {b.name[:28]:>30}")
    print("-" * 86)
    for name, va, vb in rows:
        print(f"{name:<22} {fmt(name, va):>30} {fmt(name, vb):>30}")


if __name__ == "__main__":
    main()
