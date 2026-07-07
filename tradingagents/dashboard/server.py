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
from datetime import date as _date
from pathlib import Path
from typing import Any, Callable

from .events import DashboardEventTranslator

_STATIC = Path(__file__).parent / "static"

GraphFactory = Callable[[], Any]


def _default_graph_factory() -> Any:
    """Build the real trading graph. Imported lazily so keys/config resolve
    at request time and importing this module stays cheap for tests."""
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    return TradingAgentsGraph(debug=False, config=DEFAULT_CONFIG.copy())


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def run_graph_to_queue(
    graph: Any,
    ticker: str,
    trade_date: str,
    out: "queue.Queue[dict[str, Any] | None]",
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
        _final_state, decision = graph.propagate(ticker, trade_date, on_chunk=on_chunk)
        out.put({"type": "stage", "stage": "done", "decision": str(decision)})
    except Exception as exc:  # surface, don't swallow — the UI shows it
        out.put({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
    finally:
        out.put(None)  # sentinel: stream finished


def create_app(graph_factory: GraphFactory | None = None):
    """Build the FastAPI app. ``graph_factory`` is injectable for tests."""
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, StreamingResponse

    factory = graph_factory or _default_graph_factory
    app = FastAPI(title="TradingAgents Dashboard")

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
            args=(graph, ticker.strip(), trade_date, q),
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

    return app


def main() -> None:
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8642)


if __name__ == "__main__":
    main()
