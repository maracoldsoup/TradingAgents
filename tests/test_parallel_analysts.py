"""Tests for parallel analyst execution (graph/parallel_analysts.py)."""

from __future__ import annotations

import time

from langchain_core.messages import AIMessage

from tradingagents.graph.analyst_execution import (
    ANALYST_NODE_SPECS,
    build_analyst_execution_plan,
)
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.parallel_analysts import (
    build_analyst_subgraph,
    create_parallel_analysts_node,
)
from tradingagents.graph.setup import GraphSetup


def _fake_agent(report_key: str, delay: float):
    """Analyst stub: sleeps like an LLM call, emits a report, no tool calls."""

    def node(state):
        time.sleep(delay)
        return {
            "messages": [AIMessage(content=f"{report_key} done")],
            report_key: f"{report_key} for {state['company_of_interest']}",
        }

    return node


def _fake_clear(state):
    return {}


def _noop_tools(state):  # never reached: fake agent emits no tool_calls
    raise AssertionError("tool node should not run")


def _build_subgraphs(plan, delay: float):
    logic = ConditionalLogic()
    return {
        spec.key: build_analyst_subgraph(
            spec,
            _fake_agent(spec.report_key, delay),
            _noop_tools,
            _fake_clear,
            getattr(logic, f"should_continue_{spec.key}"),
        )
        for spec in plan.specs
    }


def _seed_state():
    return {
        "company_of_interest": "000660.KS",
        "trade_date": "2026-07-07",
        "instrument_context": "SK hynix / KSC",
        "messages": [],
    }


def test_parallel_node_merges_all_reports():
    plan = build_analyst_execution_plan(("market", "social", "news", "fundamentals"))
    node = create_parallel_analysts_node(plan, _build_subgraphs(plan, delay=0.01))

    out = node(_seed_state())

    assert set(out) == {spec.report_key for spec in plan.specs}
    for spec in plan.specs:
        assert out[spec.report_key] == f"{spec.report_key} for 000660.KS"
    # messages must stay isolated inside subgraphs — never merged back.
    assert "messages" not in out


def test_parallel_node_overlaps_execution():
    delay = 0.4
    plan = build_analyst_execution_plan(("market", "social", "news", "fundamentals"))
    node = create_parallel_analysts_node(plan, _build_subgraphs(plan, delay=delay))

    started = time.monotonic()
    node(_seed_state())
    elapsed = time.monotonic() - started

    sequential_floor = delay * len(plan.specs)  # 1.6s if serial
    assert elapsed < sequential_floor * 0.6, (
        f"expected concurrent execution, took {elapsed:.2f}s"
    )


def test_parallel_node_fails_loud_with_analyst_name():
    plan = build_analyst_execution_plan(("market", "news"))
    subgraphs = _build_subgraphs(plan, delay=0.01)

    class Boom:
        def invoke(self, _state):
            raise ValueError("vendor exploded")

    subgraphs["news"] = Boom()
    node = create_parallel_analysts_node(plan, subgraphs)

    try:
        node(_seed_state())
    except RuntimeError as exc:
        assert "News Analyst" in str(exc)
    else:
        raise AssertionError("expected RuntimeError from failing analyst")


def test_partial_analyst_selection_parallel():
    plan = build_analyst_execution_plan(("market", "fundamentals"))
    node = create_parallel_analysts_node(plan, _build_subgraphs(plan, delay=0.01))

    out = node(_seed_state())

    assert set(out) == {"market_report", "fundamentals_report"}


def test_setup_graph_compiles_in_both_modes():
    logic = ConditionalLogic()
    tool_nodes = {key: _noop_tools for key in ANALYST_NODE_SPECS}

    for flag in (False, True):
        setup = GraphSetup(
            quick_thinking_llm=None,
            deep_thinking_llm=None,
            tool_nodes=tool_nodes,
            conditional_logic=logic,
            parallel_analysts=flag,
        )
        workflow = setup.setup_graph(("market", "social", "news", "fundamentals"))
        graph = workflow.compile()
        node_names = set(graph.get_graph().nodes)
        if flag:
            assert "Analyst Team" in node_names
            assert "Market Analyst" not in node_names
        else:
            assert "Market Analyst" in node_names
            assert "Analyst Team" not in node_names
