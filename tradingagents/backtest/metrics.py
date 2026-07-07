# TradingAgents/backtest/metrics.py
"""Performance metrics (paper-compatible: CR / ARR / Sharpe / MDD) + alpha."""

from __future__ import annotations

import math
import statistics

TRADING_DAYS_PER_YEAR = 252


def daily_returns(equity: list[float]) -> list[float]:
    return [
        (equity[i] / equity[i - 1]) - 1.0
        for i in range(1, len(equity))
        if equity[i - 1] > 0
    ]


def cumulative_return(equity: list[float]) -> float:
    if len(equity) < 2 or equity[0] <= 0:
        return 0.0
    return equity[-1] / equity[0] - 1.0


def annualized_return(equity: list[float]) -> float:
    cr = cumulative_return(equity)
    n = len(equity) - 1
    if n <= 0:
        return 0.0
    return (1.0 + cr) ** (TRADING_DAYS_PER_YEAR / n) - 1.0


def sharpe_ratio(equity: list[float], risk_free_daily: float = 0.0) -> float | None:
    rets = daily_returns(equity)
    if len(rets) < 2:
        return None
    excess = [r - risk_free_daily for r in rets]
    sd = statistics.stdev(excess)
    if sd == 0:
        return None
    return (statistics.mean(excess) / sd) * math.sqrt(TRADING_DAYS_PER_YEAR)


def max_drawdown(equity: list[float]) -> float:
    peak = float("-inf")
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return abs(mdd)


def alpha_vs_benchmark(equity: list[float], benchmark_closes: list[float]) -> float | None:
    """Simple cumulative-return spread vs the benchmark over the same window."""
    if len(benchmark_closes) < 2 or benchmark_closes[0] <= 0:
        return None
    bench_cr = benchmark_closes[-1] / benchmark_closes[0] - 1.0
    return cumulative_return(equity) - bench_cr


def summarize(equity_curve: list[tuple[str, float]], benchmark_closes: list[float] | None = None) -> dict:
    equity = [v for _, v in equity_curve]
    out = {
        "cumulative_return": cumulative_return(equity),
        "annualized_return": annualized_return(equity),
        "sharpe": sharpe_ratio(equity),
        "max_drawdown": max_drawdown(equity),
        "days": len(equity),
    }
    if benchmark_closes:
        out["alpha_vs_benchmark"] = alpha_vs_benchmark(equity, benchmark_closes)
    return out


# ---------------------------------------------------------------------------
# Baselines (paper comparison set, minimal versions)
# ---------------------------------------------------------------------------


def buy_and_hold_equity(closes: list[float], initial: float = 100_000_000.0) -> list[float]:
    if not closes or closes[0] <= 0:
        return []
    shares = initial / closes[0]
    return [shares * c for c in closes]


def sma_cross_equity(
    closes: list[float],
    fast: int = 10,
    slow: int = 50,
    initial: float = 100_000_000.0,
) -> list[float]:
    """Long when fast SMA > slow SMA, else cash. Next-day execution semantics."""
    equity = [initial]
    cash, shares = initial, 0.0
    signal_long = False
    for i in range(1, len(closes)):
        # 어제까지의 SMA로 오늘 행동 (룩어헤드 차단)
        if i >= slow:
            f = sum(closes[i - fast:i]) / fast
            s = sum(closes[i - slow:i]) / slow
            want_long = f > s
            if want_long and not signal_long:
                shares = cash / closes[i]
                cash = 0.0
                signal_long = True
            elif not want_long and signal_long:
                cash = shares * closes[i]
                shares = 0.0
                signal_long = False
        equity.append(cash + shares * closes[i])
    return equity
