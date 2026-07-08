# TradingAgents/backtest/engine.py
"""Phase 4-2 backtest engine.

Design invariants (see DIRECTION.md):
- **No lookahead**: a signal produced from day D's data trades at day D+1's
  open. Stops are evaluated intraday against the day's low (fill at the stop
  price — an optimistic-but-standard approximation, documented here).
- **No invented numbers**: only signal.json fields drive execution. A signal
  without levels trades at open with the default sizing; it never guesses.
- **Signals are cached** per (ticker, date) under the run directory, so an
  interrupted backtest resumes without re-paying LLM calls, and metric logic
  can be iterated offline against recorded signals.
- **Costs are explicit config**: commission and sell-side transaction tax are
  parameters. Defaults are placeholders — verify current KRX rates before
  interpreting results (rates have changed year to year).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


class SignalProvider(Protocol):
    """Returns a signal dict (signal.json shape) for one ticker/date."""

    def get_signal(
        self, ticker: str, trade_date: str, position: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


def current_config_meta() -> dict[str, Any]:
    """Fingerprint of the model configuration that produces signals.

    Stored with every cached signal so a backtest can refuse to silently
    mix signals produced under different configurations (e.g. half the
    dates on deep=flash, half on deep=pro after an .env change).
    """
    from tradingagents.default_config import DEFAULT_CONFIG

    return {
        "provider": DEFAULT_CONFIG.get("llm_provider"),
        "deep": DEFAULT_CONFIG.get("deep_think_llm"),
        "quick": DEFAULT_CONFIG.get("quick_think_llm"),
        "temperature": DEFAULT_CONFIG.get("temperature"),
    }


class ConfigMismatchError(RuntimeError):
    """Cached signal was produced under a different model configuration."""


class CachedSignalProvider:
    """Reads/writes signals under ``run_dir/signals/{date}.json``.

    Wraps an inner provider (the live pipeline); on cache hit the inner
    provider is never called. This is what makes 250-day backtests
    resumable and affordable.

    Every write records a config fingerprint (``_meta``); every read
    verifies it against ``expected_meta`` and fails loud on mismatch
    unless ``allow_mixed=True`` — a mixed-config backtest is not a
    backtest, it's noise with a CSV.
    """

    def __init__(
        self,
        inner: SignalProvider | None,
        run_dir: Path,
        expected_meta: dict[str, Any] | None = None,
        allow_mixed: bool = False,
    ):
        self.inner = inner
        self.dir = Path(run_dir) / "signals"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.expected_meta = expected_meta
        self.allow_mixed = allow_mixed

    def get_signal(
        self, ticker: str, trade_date: str, position: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        path = self.dir / f"{trade_date}.json"
        if path.exists():
            signal = json.loads(path.read_text(encoding="utf-8"))
            cached_meta = signal.get("_meta")
            if not self.allow_mixed and self.expected_meta is not None:
                if cached_meta is None:
                    # 지문 도입 이전(또는 외부 생성) 캐시 — 출처 불명은 신뢰 불가
                    raise ConfigMismatchError(
                        f"{trade_date} 캐시에 구성 지문이 없습니다(지문 도입 이전 생성 "
                        f"추정). 해당 파일을 삭제해 재생성하거나 --allow-mixed로 "
                        f"명시적으로 허용하세요: {path}"
                    )
                if cached_meta != self.expected_meta:
                    raise ConfigMismatchError(
                        f"{trade_date} 캐시는 다른 구성으로 생성됨: cached={cached_meta} "
                        f"current={self.expected_meta}. 캐시 폴더를 보존·개명 후 새로 "
                        f"시작하거나 --allow-mixed로 명시적으로 허용하세요."
                    )
            return signal
        if self.inner is None:
            raise FileNotFoundError(
                f"no cached signal for {trade_date} and no live provider configured"
            )
        signal = dict(self.inner.get_signal(ticker, trade_date, position=position))
        if self.expected_meta is not None:
            signal["_meta"] = self.expected_meta
        path.write_text(json.dumps(signal, ensure_ascii=False, indent=2), encoding="utf-8")
        return signal


class LivePipelineProvider:
    """Runs the real TradingAgents pipeline for each date (expensive)."""

    def get_signal(
        self, ticker: str, trade_date: str, position: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        import sys
        from time import monotonic

        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        # 첫 시그널이 수 분 걸리는 동안 침묵하면 행업과 구분이 안 된다.
        print(f"  [signal] {trade_date} 파이프라인 실행 중...", flush=True)
        started = monotonic()
        graph = TradingAgentsGraph(debug=False, config=DEFAULT_CONFIG.copy())
        final_state, _ = graph.propagate(ticker, trade_date, position=position)
        signal = final_state.get("final_trade_signal") or {}
        print(
            f"  [signal] {trade_date} 완료 ({monotonic() - started:.0f}s) → "
            f"{signal.get('rating', '?')}",
            flush=True,
        )
        return signal


@dataclass
class CostModel:
    """Explicit, verifiable trading costs.

    Defaults are conservative placeholders for KRX equities; confirm the
    current commission schedule and transaction/농특세 rates before drawing
    conclusions from absolute returns.
    """

    commission_rate: float = 0.00015  # 매수·매도 각각 (0.015%)
    sell_tax_rate: float = 0.0015     # 매도 시 거래세성 비용 (0.15% 가정 — 검증 필요)
    slippage_rate: float = 0.0005     # 체결 슬리피지 가정 (0.05%)

    def buy_cost(self, notional: float) -> float:
        return notional * (self.commission_rate + self.slippage_rate)

    def sell_cost(self, notional: float) -> float:
        return notional * (self.commission_rate + self.sell_tax_rate + self.slippage_rate)


@dataclass
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float


@dataclass
class BacktestResult:
    equity_curve: list[tuple[str, float]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    daily_signals: list[dict[str, Any]] = field(default_factory=list)


ACTION_TARGET = {
    # action → 목표 보유 비중 결정 방식: Buy는 시그널 비중(없으면 기본),
    # Hold는 현 상태 유지, Sell은 전량 청산.
    "Buy": "enter",
    "Hold": "keep",
    "Sell": "exit",
}


def run_backtest(
    bars: list[Bar],
    provider: SignalProvider,
    ticker: str,
    initial_cash: float = 100_000_000.0,
    default_size_pct: float = 5.0,
    size_override_pct: float | None = None,
    cost_model: CostModel | None = None,
    on_day: Callable[[str, float], None] | None = None,
) -> BacktestResult:
    """Run the day loop. ``bars`` must be in ascending date order.

    Timing model per day i:
      1. If a stop was armed and today's low pierces it → exit at stop price.
      2. Execute yesterday's signal at today's OPEN (no lookahead).
         ``size_override_pct`` forces every entry to that size, ignoring the
         signal's own sizing — used to separate directional skill from the
         committee's sizing timidity (pilot #2: 77% win rate at 3.5% size).
      3. After close, request the signal for today (it will act tomorrow).
    """
    costs = cost_model or CostModel()
    cash = initial_cash
    shares = 0.0
    armed_stop: float | None = None
    pending: dict[str, Any] | None = None
    result = BacktestResult()

    def equity(price: float) -> float:
        return cash + shares * price

    def sell_all(price: float, date: str, reason: str) -> None:
        nonlocal cash, shares, armed_stop
        if shares <= 0:
            return
        notional = shares * price
        cash += notional - costs.sell_cost(notional)
        result.trades.append(
            {"date": date, "side": "sell", "price": price, "shares": shares, "reason": reason}
        )
        shares = 0.0
        armed_stop = None

    for i, bar in enumerate(bars):
        # 1) 손절: 장중 저가가 스탑을 뚫으면 스탑가 체결로 근사
        if armed_stop is not None and shares > 0 and bar.low <= armed_stop:
            sell_all(min(armed_stop, bar.open), bar.date, "stop_loss")

        # 2) 전일 시그널을 오늘 시가에 집행
        if pending is not None:
            action = pending.get("action", "Hold")
            mode = ACTION_TARGET.get(action, "keep")
            levels = pending.get("levels") or {}
            if mode == "exit":
                sell_all(bar.open, bar.date, "signal_sell")
            elif mode == "enter" and shares == 0:
                size_pct = (
                    size_override_pct
                    if size_override_pct is not None
                    else levels.get("position_size_pct") or default_size_pct
                )
                budget = equity(bar.open) * (size_pct / 100.0)
                price = bar.open
                # 예산은 비용 포함 총지출 기준: notional*(1+비용률) ≤ budget.
                # 아니면 100% 비중이 수수료만큼 항상 미체결로 새는 버그가 된다.
                cost_rate = costs.commission_rate + costs.slippage_rate
                buy_shares = (budget / (1.0 + cost_rate)) / price if price > 0 else 0.0
                if buy_shares > 0:
                    notional = buy_shares * price
                    total = notional + costs.buy_cost(notional)
                    if total <= cash + 1e-6:
                        cash -= total
                        shares += buy_shares
                        result.trades.append(
                            {"date": bar.date, "side": "buy", "price": price,
                             "shares": buy_shares, "reason": "signal_buy"}
                        )
            # 진입/보유 공통: 시그널이 명시한 스탑을 무장
            if mode != "exit" and levels.get("stop"):
                armed_stop = float(levels["stop"])
            pending = None

        # 3) 오늘 종가 이후의 시그널 생성 (내일 집행)
        is_last = i == len(bars) - 1
        if not is_last:
            current_position = (
                {
                    "shares": shares,
                    "entry_price": result.trades[-1]["price"] if shares > 0 and result.trades else None,
                    "entry_date": result.trades[-1]["date"] if shares > 0 and result.trades else None,
                    "current_price": bar.close,
                    "stop": armed_stop,
                }
                if shares > 0
                else {"shares": 0}
            )
            signal = provider.get_signal(ticker, bar.date, position=current_position)
            result.daily_signals.append({"date": bar.date, **signal})
            pending = signal

        result.equity_curve.append((bar.date, equity(bar.close)))
        if on_day:
            on_day(bar.date, equity(bar.close))

    return result
