"""Phase 4-2 backtest engine tests — synthetic prices, fake signals, no LLM."""

from __future__ import annotations

import json

from tradingagents.backtest.engine import (
    Bar,
    CachedSignalProvider,
    CostModel,
    run_backtest,
)
from tradingagents.backtest.metrics import (
    buy_and_hold_equity,
    max_drawdown,
    sharpe_ratio,
    sma_cross_equity,
    summarize,
)


def _bars(prices):
    """종가 리스트 → 단순 OHLC 바 (시가=전일 종가, 고저=±1%)."""
    bars = []
    prev = prices[0]
    for i, c in enumerate(prices):
        o = prev
        bars.append(Bar(date=f"2026-01-{i+1:02d}", open=o, high=max(o, c) * 1.01,
                        low=min(o, c) * 0.99, close=c))
        prev = c
    return bars


class ScriptedProvider:
    def __init__(self, signals):
        self.signals = signals
        self.calls = 0

    def get_signal(self, ticker, trade_date):
        self.calls += 1
        return self.signals.get(trade_date, {"action": "Hold"})


def test_no_lookahead_buy_fills_next_open():
    bars = _bars([100, 100, 110, 110])
    provider = ScriptedProvider({
        "2026-01-01": {"action": "Buy", "levels": {"position_size_pct": 100}},
    })
    res = run_backtest(bars, provider, "TEST", initial_cash=1_000_000,
                       cost_model=CostModel(0, 0, 0))
    buy = [t for t in res.trades if t["side"] == "buy"][0]
    # 1일차 시그널 → 2일차 시가(=1일차 종가 100)에 체결. 1일차 장중가로 사면 룩어헤드다.
    assert buy["date"] == "2026-01-02" and buy["price"] == 100
    # 이후 110으로 상승분 반영
    assert res.equity_curve[-1][1] > 1_000_000


def test_stop_loss_fires_on_intraday_low():
    bars = _bars([100, 100, 80, 90])  # 3일차 급락으로 스탑 관통
    provider = ScriptedProvider({
        "2026-01-01": {"action": "Buy",
                        "levels": {"position_size_pct": 100, "stop": 95}},
    })
    res = run_backtest(bars, provider, "TEST", initial_cash=1_000_000,
                       cost_model=CostModel(0, 0, 0))
    stops = [t for t in res.trades if t["reason"] == "stop_loss"]
    assert len(stops) == 1 and stops[0]["price"] <= 95
    # 스탑 이후 재진입 시그널이 없으니 반등(90)을 안 먹는다
    final = res.equity_curve[-1][1]
    assert final < 1_000_000  # 손실 확정


def test_sell_signal_exits_and_costs_apply():
    bars = _bars([100, 100, 100, 100])
    provider = ScriptedProvider({
        "2026-01-01": {"action": "Buy", "levels": {"position_size_pct": 100}},
        "2026-01-02": {"action": "Sell"},
    })
    costs = CostModel(commission_rate=0.001, sell_tax_rate=0.002, slippage_rate=0.0)
    res = run_backtest(bars, provider, "TEST", initial_cash=1_000_000, cost_model=costs)
    final = res.equity_curve[-1][1]
    # 가격 변동 0인데 왕복 비용만큼 감소해야 한다 (매수 0.1% + 매도 0.3%)
    assert 995_800 < final < 996_300


def test_hold_signal_keeps_position_and_missing_levels_never_invented():
    bars = _bars([100, 100, 100])
    provider = ScriptedProvider({
        "2026-01-01": {"action": "Buy"},  # levels 없음 → 기본 비중
        "2026-01-02": {"action": "Hold"},
    })
    res = run_backtest(bars, provider, "TEST", initial_cash=1_000_000,
                       default_size_pct=10, cost_model=CostModel(0, 0, 0))
    buy = [t for t in res.trades if t["side"] == "buy"][0]
    assert abs(buy["shares"] * buy["price"] - 100_000) < 1  # 10% 기본 비중
    assert len(res.trades) == 1  # Hold는 아무것도 안 한다


def test_cached_provider_never_repays(tmp_path):
    inner = ScriptedProvider({"2026-01-01": {"action": "Buy"}})
    cached = CachedSignalProvider(inner, tmp_path)
    a = cached.get_signal("T", "2026-01-01")
    b = cached.get_signal("T", "2026-01-01")
    assert a == b and inner.calls == 1  # 두 번째는 캐시
    disk = json.loads((tmp_path / "signals" / "2026-01-01.json").read_text())
    assert disk["action"] == "Buy"


def test_metrics_sanity():
    eq = [100.0, 110.0, 99.0, 120.0]
    assert abs(max_drawdown(eq) - 0.1) < 1e-9
    s = summarize([(str(i), v) for i, v in enumerate(eq)], benchmark_closes=[100, 100, 100, 100])
    assert abs(s["cumulative_return"] - 0.2) < 1e-9
    assert abs(s["alpha_vs_benchmark"] - 0.2) < 1e-9
    assert sharpe_ratio([100.0, 100.0, 100.0]) is None  # 무변동 → 정의 불가

    bh = buy_and_hold_equity([100, 120], initial=100)
    assert bh[-1] == 120
    sma = sma_cross_equity(list(range(100, 200)), fast=3, slow=5, initial=100)
    assert sma[-1] > 100  # 단조 상승장에서 추세 추종은 이긴다
