# TradingAgents/dashboard/server.py
"""Live dashboard server: runs the trading graph and streams SSE events.

Run with:  python -m tradingagents.dashboard  (needs `pip install ".[dashboard]"`)
Then open http://127.0.0.1:8642

Design: the worker thread calls the *unmodified* production entrypoint
``TradingAgentsGraph.propagate(..., on_chunk=...)`` so memory-log context,
instrument resolution, checkpoint resume, and report/decision persistence
all behave exactly as in the CLI — the dashboard is an observer, not a
second pipeline.
"""

from __future__ import annotations

import json
import queue
import threading
import uuid
from datetime import date as _date
from pathlib import Path
from typing import Any, Callable

from .events import DashboardEventTranslator

_STATIC = Path(__file__).parent / "static"

GraphFactory = Callable[[], Any]

_GLOBAL_SYMBOLS = [
    {"symbol": "NVDA", "name": "NVIDIA", "market": "US"},
    {"symbol": "AAPL", "name": "Apple", "market": "US"},
    {"symbol": "MSFT", "name": "Microsoft", "market": "US"},
    {"symbol": "GOOGL", "name": "Alphabet", "market": "US"},
    {"symbol": "AMZN", "name": "Amazon", "market": "US"},
    {"symbol": "META", "name": "Meta Platforms", "market": "US"},
    {"symbol": "TSLA", "name": "Tesla", "market": "US"},
    {"symbol": "TSM", "name": "Taiwan Semiconductor", "market": "US ADR"},
    {"symbol": "ASML", "name": "ASML", "market": "US ADR"},
    {"symbol": "SPY", "name": "S&P 500 ETF", "market": "US ETF"},
    {"symbol": "QQQ", "name": "Nasdaq 100 ETF", "market": "US ETF"},
    {"symbol": "^GSPC", "name": "S&P 500 Index", "market": "INDEX"},
    {"symbol": "^IXIC", "name": "Nasdaq Composite", "market": "INDEX"},
    {"symbol": "BTC-USD", "name": "Bitcoin USD", "market": "CRYPTO"},
    {"symbol": "ETH-USD", "name": "Ethereum USD", "market": "CRYPTO"},
    {"symbol": "GC=F", "name": "Gold Futures", "market": "FUTURES"},
    {"symbol": "CL=F", "name": "Crude Oil Futures", "market": "FUTURES"},
    {"symbol": "EURUSD=X", "name": "EUR/USD", "market": "FX"},
    {"symbol": "^KS11", "name": "KOSPI Index", "market": "KR"},
    {"symbol": "^KQ11", "name": "KOSDAQ Index", "market": "KR"},
    {"symbol": "^N225", "name": "Nikkei 225", "market": "JP"},
    {"symbol": "7203.T", "name": "Toyota Motor", "market": "JP"},
    {"symbol": "9984.T", "name": "SoftBank Group", "market": "JP"},
    {"symbol": "0700.HK", "name": "Tencent", "market": "HK"},
    {"symbol": "000001.SS", "name": "Shanghai Composite", "market": "CN"},
]
_POPULAR_SYMBOL_RANK = {
    "005930.KS": 0,
    "000660.KS": 1,
    "NVDA": 2,
    "AAPL": 3,
    "MSFT": 4,
    "TSM": 5,
    "BTC-USD": 6,
}


def _default_graph_factory() -> Any:
    """Build the real trading graph. Imported lazily so keys/config resolve
    at request time and importing this module stays cheap for tests."""
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    return TradingAgentsGraph(debug=False, config=DEFAULT_CONFIG.copy())


def search_symbols(query: str = "", limit: int = 30) -> list[dict[str, str]]:
    """Search configured symbols for the dashboard picker."""
    from tradingagents.default_config import DEFAULT_CONFIG

    q = query.strip().lower()
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for item in _GLOBAL_SYMBOLS:
        symbol = item["symbol"]
        haystack = f"{symbol} {item['name']} {item['market']}".lower()
        if not q or q in haystack:
            rows.append(dict(item))
            seen.add(symbol)

    for code, name in (DEFAULT_CONFIG.get("korean_ticker_names") or {}).items():
        if not code or "." in code:
            continue
        symbol = f"{code}.KS"
        haystack = f"{code} {symbol} {name} KR KRX".lower()
        if symbol in seen or (q and q not in haystack):
            continue
        rows.append({"symbol": symbol, "name": str(name), "market": "KR"})
        seen.add(symbol)

    def rank(item: dict[str, str]) -> tuple[int, int, str]:
        symbol = item["symbol"].lower()
        name = item["name"].lower()
        popularity = _POPULAR_SYMBOL_RANK.get(item["symbol"], 999)
        if not q:
            return (2, popularity, item["symbol"])
        if symbol == q or symbol.replace(".ks", "") == q:
            return (0, popularity, item["symbol"])
        if symbol.startswith(q) or name.startswith(q):
            return (1, popularity, item["symbol"])
        return (2, popularity, item["symbol"])

    return sorted(rows, key=rank)[: max(1, min(limit, 80))]


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def run_graph_to_queue(
    graph: Any,
    ticker: str,
    trade_date: str,
    out: "queue.Queue[dict[str, Any] | None]",
    artifact_registry: dict[str, Path] | None = None,
) -> None:
    """Worker thread: run propagate() with a chunk observer feeding the queue."""
    translator = DashboardEventTranslator()

    def on_chunk(chunk: dict[str, Any]) -> None:
        for event in translator.translate(chunk):
            out.put(event)

    try:
        out.put(
            {"type": "stage", "stage": "start", "ticker": ticker, "date": trade_date}
        )
        final_state, decision = graph.propagate(ticker, trade_date, on_chunk=on_chunk)
        if hasattr(graph, "save_reports"):
            report_path = graph.save_reports(final_state, ticker)
            artifact_id = uuid.uuid4().hex
            if artifact_registry is not None:
                artifact_registry[artifact_id] = Path(report_path)
            out.put(
                {
                    "type": "artifact",
                    "kind": "complete_report",
                    "id": artifact_id,
                    "path": str(report_path),
                    "directory": str(Path(report_path).parent),
                    "download_url": f"/api/artifacts/{artifact_id}/download",
                    "text_url": f"/api/artifacts/{artifact_id}/text",
                }
            )
        out.put({"type": "stage", "stage": "done", "decision": str(decision)})
    except Exception as exc:  # surface, don't swallow — the UI shows it
        out.put({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
    finally:
        out.put(None)  # sentinel: stream finished


def create_app(graph_factory: GraphFactory | None = None):
    """Build the FastAPI app. ``graph_factory`` is injectable for tests."""
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

    factory = graph_factory or _default_graph_factory
    app = FastAPI(title="TradingAgents Dashboard")
    artifact_registry: dict[str, Path] = {}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    @app.get("/api/stream")
    def stream(ticker: str, date: str | None = None) -> StreamingResponse:
        trade_date = date or _date.today().isoformat()
        graph = factory()
        q: "queue.Queue[dict[str, Any] | None]" = queue.Queue()
        worker = threading.Thread(
            target=run_graph_to_queue,
            args=(graph, ticker.strip(), trade_date, q, artifact_registry),
            daemon=True,
        )
        worker.start()

        def event_source():
            while True:
                item = q.get()
                if item is None:
                    break
                yield _sse(item)

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/symbols")
    def symbols(q: str = "", limit: int = 30) -> dict[str, Any]:
        return {"symbols": search_symbols(q, limit)}

    def _artifact_path(artifact_id: str) -> Path:
        path = artifact_registry.get(artifact_id)
        if path is None or not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="report artifact not found")
        return path

    @app.get("/api/artifacts/{artifact_id}/download")
    def download_artifact(artifact_id: str) -> FileResponse:
        path = _artifact_path(artifact_id)
        return FileResponse(
            path,
            media_type="text/markdown; charset=utf-8",
            filename=path.name,
        )

    @app.get("/api/artifacts/{artifact_id}/text")
    def artifact_text(artifact_id: str) -> PlainTextResponse:
        path = _artifact_path(artifact_id)
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    return app


def main() -> None:
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8642)


if __name__ == "__main__":
    main()
