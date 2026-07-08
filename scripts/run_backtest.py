#!/usr/bin/env python3
"""Phase 4-2 백테스트 러너.

사용법 (저장소 루트):

    # 1) 시그널 생성 + 백테스트 (LLM 비용 발생 — 날짜 수 × 1회 propagate)
    python scripts/run_backtest.py 005930.KS --start 2026-05-01 --end 2026-07-01

    # 2) 캐시된 시그널로 재계산만 (LLM 호출 0회 — 비용·지표 파라미터 튜닝용)
    python scripts/run_backtest.py 005930.KS --start 2026-05-01 --end 2026-07-01 --cached-only

중단 후 재실행하면 이미 만든 시그널은 캐시에서 읽는다(재과금 없음).
결과: backtests/<ticker>_<start>_<end>/ 아래 signals/, result.json, equity.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_bars(ticker: str, start: str, end: str):
    import yfinance as yf

    from tradingagents.backtest.engine import Bar

    df = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
    if df.empty:
        sys.exit(f"가격 데이터 없음: {ticker} {start}~{end}")
    bars = [
        Bar(date=idx.strftime("%Y-%m-%d"), open=float(r["Open"]), high=float(r["High"]),
            low=float(r["Low"]), close=float(r["Close"]))
        for idx, r in df.iterrows()
    ]
    return bars


def load_benchmark_closes(ticker: str, start: str, end: str) -> list[float]:
    import yfinance as yf

    from tradingagents.default_config import DEFAULT_CONFIG

    bench = ""
    for suffix, symbol in DEFAULT_CONFIG.get("benchmark_map", {}).items():
        if suffix and ticker.upper().endswith(suffix):
            bench = symbol
            break
    bench = bench or DEFAULT_CONFIG.get("benchmark_map", {}).get("", "SPY")
    df = yf.Ticker(bench).history(start=start, end=end, auto_adjust=True)
    return [float(c) for c in df["Close"]] if not df.empty else []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticker")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--allow-mixed", action="store_true",
                        help="구성 지문 불일치 캐시 허용 (실험 오염 감수 — 비권장)")
    parser.add_argument("--cached-only", action="store_true",
                        help="캐시된 시그널만 사용 (LLM 호출 금지)")
    parser.add_argument("--size-pct", type=float, default=5.0,
                        help="시그널에 비중이 없을 때 기본 비중(%%)")
    args = parser.parse_args()

    from tradingagents.backtest.engine import (
        CachedSignalProvider,
        LivePipelineProvider,
        current_config_meta,
        run_backtest,
    )
    from tradingagents.backtest.metrics import (
        buy_and_hold_equity,
        sma_cross_equity,
        summarize,
        trade_diagnostics,
    )

    run_dir = Path("backtests") / f"{args.ticker.replace('.', '_')}_{args.start}_{args.end}"
    run_dir.mkdir(parents=True, exist_ok=True)

    bars = load_bars(args.ticker, args.start, args.end)
    print(f"거래일 {len(bars)}일 로드 ({bars[0].date} ~ {bars[-1].date})")
    if not args.cached_only:
        est = len(bars) - 1
        print(f"⚠ 시그널 미캐시분은 LLM으로 생성됩니다 — 최대 {est}회 propagate. 중단해도 재개 가능.")

    meta = current_config_meta()
    print(f"모델 구성: {meta}")
    inner = None if args.cached_only else LivePipelineProvider()
    provider = CachedSignalProvider(inner, run_dir, expected_meta=meta,
                                    allow_mixed=args.allow_mixed)

    result = run_backtest(
        bars, provider, args.ticker, default_size_pct=args.size_pct,
        on_day=lambda d, eq: print(f"  {d}  equity {eq:,.0f}"),
    )

    closes = [b.close for b in bars]
    bench = load_benchmark_closes(args.ticker, args.start, args.end)
    diag = trade_diagnostics(result.trades, result.equity_curve)
    summary = {
        "strategy": summarize(result.equity_curve, benchmark_closes=bench or None),
        "diagnostics": {k: v for k, v in diag.items() if k != "round_trips"},
        "buy_and_hold": summarize(
            list(zip([b.date for b in bars], buy_and_hold_equity(closes)))
        ),
        "sma_10_50": summarize(
            list(zip([b.date for b in bars], sma_cross_equity(closes)))
        ),
        "trades": len(result.trades),
    }

    (run_dir / "result.json").write_text(
        json.dumps({"summary": summary, "trades": result.trades,
                    "round_trips": diag["round_trips"]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "equity.csv").write_text(
        "date,equity\n" + "\n".join(f"{d},{v:.2f}" for d, v in result.equity_curve),
        encoding="utf-8",
    )

    print("\n" + "=" * 62)
    for name, s in summary.items():
        # 성과 요약 dict만 출력 (diagnostics 같은 비-성과 dict 제외)
        if not isinstance(s, dict) or "cumulative_return" not in s:
            continue
        sr = f"{s['sharpe']:.2f}" if s.get("sharpe") is not None else "n/a"
        alpha = s.get("alpha_vs_benchmark")
        alpha_txt = f"  α {alpha:+.1%}" if alpha is not None else ""
        print(f"{name:>14}: CR {s['cumulative_return']:+.1%}  SR {sr}  MDD {s['max_drawdown']:.1%}{alpha_txt}")
    d = summary["diagnostics"]
    wr = f"{d['win_rate']:.0%}" if d.get("win_rate") is not None else "n/a"
    tim = f"{d['time_in_market_pct']:.0%}" if d.get("time_in_market_pct") is not None else "n/a"
    dep = f"{d['pnl_on_deployed']:+.1%}" if d.get("pnl_on_deployed") is not None else "n/a"
    avgp = f"{d['avg_position_pct_of_initial']:.1%}" if d.get("avg_position_pct_of_initial") is not None else "n/a"
    print(f"거래 횟수: {summary['trades']}  |  승률 {wr}  |  시장 체류 {tim}  |  "
          f"평균 비중 {avgp}  |  투입자본 수익률 {dep}")
    if len(bars) < 50:
        print("⚠ SMA(10/50) 베이스라인은 창이 50일 미만이라 무효 — 거래 0회로 계산 불능")
    print(f"저장: {run_dir}/")


if __name__ == "__main__":
    main()
