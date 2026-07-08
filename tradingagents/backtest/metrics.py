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


# ---------------------------------------------------------------------------
# Trade diagnostics — 파일럿 1호 실측에서 필요성이 확인된 지표들
# ---------------------------------------------------------------------------


def round_trips(trades: list[dict]) -> list[dict]:
    """buy→sell 쌍을 왕복 매매로 묶어 손익을 계산한다 (단일 포지션 가정)."""
    trips: list[dict] = []
    open_trade: dict | None = None
    for t in trades:
        if t["side"] == "buy":
            open_trade = t
        elif t["side"] == "sell" and open_trade is not None:
            pnl_pct = t["price"] / open_trade["price"] - 1.0
            trips.append({
                "entry_date": open_trade["date"], "exit_date": t["date"],
                "entry": open_trade["price"], "exit": t["price"],
                "hold_days_approx": None,  # 날짜 산술은 러너에서
                "pnl_pct": pnl_pct,
                "notional": open_trade["shares"] * open_trade["price"],
                "exit_reason": t.get("reason"),
            })
            open_trade = None
    return trips


def trade_diagnostics(trades: list[dict], equity_curve: list[tuple[str, float]]) -> dict:
    """노출·체류·승률 진단. 절대수익률만 보면 소액 베팅 전략이 무능해 보인다."""
    trips = round_trips(trades)
    wins = [t for t in trips if t["pnl_pct"] > 0]
    # 시장 체류일: buy~sell 구간의 equity 곡선 날짜 수로 근사
    dates = [d for d, _ in equity_curve]
    in_market = 0
    holding = False
    ti = 0
    for d, _ in equity_curve:
        while ti < len(trades) and trades[ti]["date"] <= d:
            holding = trades[ti]["side"] == "buy"
            ti += 1
        if holding:
            in_market += 1
    avg_notional = (
        sum(t["notional"] for t in trips) / len(trips) if trips else 0.0
    )
    initial = equity_curve[0][1] if equity_curve else 0.0
    deployed_pnl = sum(t["pnl_pct"] * t["notional"] for t in trips)
    return {
        "round_trips": trips,
        "win_rate": len(wins) / len(trips) if trips else None,
        "time_in_market_pct": in_market / len(dates) if dates else None,
        "avg_position_pct_of_initial": (avg_notional / initial) if initial else None,
        "pnl_on_deployed": (deployed_pnl / sum(t["notional"] for t in trips))
        if trips else None,
    }
