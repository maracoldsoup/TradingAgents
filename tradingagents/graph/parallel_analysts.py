# TradingAgents/graph/parallel_analysts.py
"""Parallel analyst execution.

Why this exists: all four analysts share the single ``state["messages"]``
channel for their ReAct tool loops, so they cannot be fanned out with plain
LangGraph edges — concurrent branches would interleave tool calls on the
shared channel. Instead, each analyst runs as its own compiled *subgraph*
(agent ⇄ tools → clear) with fully isolated state, and one main-graph node
invokes those subgraphs concurrently, merging only the report fields back.

Trade-offs (documented, intentional):
- Checkpoint granularity: the analyst stage becomes a single node, so a
  crash mid-stage re-runs all analysts on resume (was: per-analyst resume).
- Rate limits: concurrency multiplies burst RPM against the LLM provider.
  On free tiers this can be slower than sequential due to retry backoff;
  disable via ``TRADINGAGENTS_PARALLEL_ANALYSTS=false`` if that bites.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from tradingagents.agents.utils.agent_states import AgentState

from .analyst_execution import AnalystExecutionPlan, AnalystNodeSpec

# State keys each analyst subgraph needs as input. Report keys and messages
# are intentionally excluded from the merge-back (messages stay isolated).
_SEED_KEYS = (
    "company_of_interest",
    "trade_date",
    "instrument_context",
    "messages",
)


def build_analyst_subgraph(
    spec: AnalystNodeSpec,
    agent_node_fn: Callable,
    tool_node: Any,
    clear_node_fn: Callable,
    should_continue: Callable,
):
    """Compile a self-contained subgraph for one analyst.

    Node names match the main-graph names so the existing
    ``ConditionalLogic.should_continue_<key>`` routers work unchanged.
    """
    sub = StateGraph(AgentState)
    sub.add_node(spec.agent_node, agent_node_fn)
    sub.add_node(spec.tool_node, tool_node)
    sub.add_node(spec.clear_node, clear_node_fn)

    sub.add_edge(START, spec.agent_node)
    sub.add_conditional_edges(
        spec.agent_node,
        should_continue,
        [spec.tool_node, spec.clear_node],
    )
    sub.add_edge(spec.tool_node, spec.agent_node)
    sub.add_edge(spec.clear_node, END)
    return sub.compile()


def create_parallel_analysts_node(
    plan: AnalystExecutionPlan,
    subgraphs: dict[str, Any],
    max_workers: int | None = None,
):
    """Return a main-graph node that runs all analyst subgraphs concurrently.

    Failure policy: fail loud. A dead analyst report would silently skew the
    downstream debate, so the first subgraph exception aborts the run with
    the analyst named — consistent with the vendor-chain "no silent
    fallback" philosophy in default_config.
    """
    workers = max_workers or len(plan.specs)

    def parallel_analysts_node(state: AgentState) -> dict[str, Any]:
        seed = {k: state[k] for k in _SEED_KEYS if k in state}

        def run_one(spec: AnalystNodeSpec) -> tuple[str, str]:
            try:
                out = subgraphs[spec.key].invoke(dict(seed))
            except Exception as exc:  # pragma: no cover - passthrough wrapper
                raise RuntimeError(
                    f"{spec.agent_node} failed during parallel execution: {exc}"
                ) from exc
            return spec.report_key, out.get(spec.report_key, "") or ""

        results: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for report_key, report in pool.map(run_one, plan.specs):
                results[report_key] = report
        return results

    return parallel_analysts_node
