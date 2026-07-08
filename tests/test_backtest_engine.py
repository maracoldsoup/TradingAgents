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


def test_cache_refuses_mixed_configs(tmp_path):
    import pytest as _pytest

    from tradingagents.backtest.engine import CachedSignalProvider, ConfigMismatchError

    flash = {"provider": "google", "deep": "flash", "quick": "flash", "temperature": None}
    pro = {"provider": "google", "deep": "pro", "quick": "flash", "temperature": None}

    inner = ScriptedProvider({"2026-01-01": {"action": "Buy"}})
    writer = CachedSignalProvider(inner, tmp_path, expected_meta=flash)
    writer.get_signal("T", "2026-01-01")  # flash 지문으로 캐시 생성

    reader = CachedSignalProvider(None, tmp_path, expected_meta=pro)
    with _pytest.raises(ConfigMismatchError):
        reader.get_signal("T", "2026-01-01")

    # 명시적 허용 시에만 통과
    mixed = CachedSignalProvider(None, tmp_path, expected_meta=pro, allow_mixed=True)
    assert mixed.get_signal("T", "2026-01-01")["action"] == "Buy"

    # 같은 지문이면 정상
    same = CachedSignalProvider(None, tmp_path, expected_meta=flash)
    assert same.get_signal("T", "2026-01-01")["action"] == "Buy"

    # 지문 없는 구세대 캐시도 거부한다 (출처 불명 = 신뢰 불가)
    import json as _json
    legacy = tmp_path / "signals" / "2026-01-02.json"
    legacy.write_text(_json.dumps({"action": "Sell"}), encoding="utf-8")
    with _pytest.raises(ConfigMismatchError):
        CachedSignalProvider(None, tmp_path, expected_meta=pro).get_signal("T", "2026-01-02")


def test_trade_diagnostics_pilot_shape():
    from tradingagents.backtest.metrics import round_trips, trade_diagnostics

    trades = [
        {"date": "d1", "side": "buy", "price": 100.0, "shares": 10, "reason": "signal_buy"},
        {"date": "d3", "side": "sell", "price": 95.0, "shares": 10, "reason": "stop_loss"},
        {"date": "d5", "side": "buy", "price": 100.0, "shares": 10, "reason": "signal_buy"},
        {"date": "d7", "side": "sell", "price": 105.0, "shares": 10, "reason": "signal_sell"},
        {"date": "d9", "side": "buy", "price": 100.0, "shares": 10, "reason": "signal_buy"},
    ]
    trips = round_trips(trades)
    assert len(trips) == 2  # 마지막 미청산 매수는 왕복이 아니다
    assert trips[0]["exit_reason"] == "stop_loss" and trips[0]["pnl_pct"] < 0

    curve = [(f"d{i}", 1000.0) for i in range(1, 10)]
    d = trade_diagnostics(trades, curve)
    assert d["win_rate"] == 0.5
    assert 0 < d["time_in_market_pct"] < 1
    assert abs(d["pnl_on_deployed"] - 0.0) < 1e-9  # -5% + +5% 균등 노출 → 0
