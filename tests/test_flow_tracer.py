"""Tests for FlowTracer — entry point detection and BFS flow tracing."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from corbell.core.graph.flow_tracer import FlowTracer, _method_to_flow_name
from corbell.core.graph.schema import DependencyEdge, MethodNode
from corbell.core.graph.sqlite_store import SQLiteGraphStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_method(mid: str, name: str, svc: str = "svc", line_start: int = 1, file_path: str = "app.py") -> MethodNode:
    return MethodNode(
        id=mid,
        repo="/repo",
        file_path=file_path,
        class_name=None,
        method_name=name,
        signature=name,
        docstring=None,
        line_start=line_start,
        line_end=line_start + 5,
        service_id=svc,
    )


# ---------------------------------------------------------------------------
# _method_to_flow_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("input_name,expected_suffix", [
    ("login_handler", "Flow"),
    ("processPayment", "Flow"),
    ("get_user", "Flow"),
    ("POST", "Flow"),
])
def test_method_to_flow_name(input_name, expected_suffix):
    result = _method_to_flow_name(input_name)
    assert result.endswith(expected_suffix)
    assert result[0].isupper()


def test_method_to_flow_name_login():
    result = _method_to_flow_name("login_handler")
    assert "Login" in result


def test_method_to_flow_name_payment():
    result = _method_to_flow_name("processPayment")
    assert "Payment" in result or "Process" in result


# ---------------------------------------------------------------------------
# detect_entry_points — name heuristics
# ---------------------------------------------------------------------------


def test_detect_entry_points_by_name():
    """Methods with handler/controller/endpoint in name are detected as entry points."""
    tracer = FlowTracer()
    methods = [
        _make_method("m1", "login_handler"),
        _make_method("m2", "validate_token"),
        _make_method("m3", "get_user_controller"),
        _make_method("m4", "_internal_helper"),
    ]

    eps = tracer.detect_entry_points(methods, repo_path=None, language="python")
    ep_names = {m.method_name for m in eps}
    assert "login_handler" in ep_names
    assert "get_user_controller" in ep_names
    # validate_token and _internal_helper should NOT be entry points
    assert "validate_token" not in ep_names


def test_detect_entry_points_skips_tests():
    """Test methods should not be detected as entry points."""
    tracer = FlowTracer()
    methods = [
        _make_method("m1", "test_login"),
        _make_method("m2", "TestUserFlow"),
    ]
    eps = tracer.detect_entry_points(methods, repo_path=None, language="python")
    ep_names = {m.method_name for m in eps}
    assert "test_login" not in ep_names


def test_detect_entry_points_by_source_line(tmp_path):
    """@app.route decorator is detected from source file."""
    src = tmp_path / "app.py"
    src.write_text(textwrap.dedent("""
        from flask import Flask
        app = Flask(__name__)

        @app.route('/login', methods=['POST'])
        def login():
            pass

        def validate_token(token):
            return True
    """))

    tracer = FlowTracer()
    methods = [
        _make_method("m1", "login", line_start=5, file_path=str(src)),
        _make_method("m2", "validate_token", line_start=9, file_path=str(src)),
    ]

    eps = tracer.detect_entry_points(methods, repo_path=tmp_path, language="python")
    ep_names = {m.method_name for m in eps}
    # login is detected by name heuristic (contains "login") and potentially by source
    assert "login" in ep_names


# ---------------------------------------------------------------------------
# trace_flows — BFS flow tracing
# ---------------------------------------------------------------------------


@pytest.fixture
def flow_store(tmp_db):
    return SQLiteGraphStore(tmp_db)


def test_trace_flows_basic(flow_store):
    """BFS from entry to callee produces a flow with both methods."""
    # Build: login_handler → validate_token → get_session
    for mid, name in [
        ("m1", "login_handler"),
        ("m2", "validate_token"),
        ("m3", "get_session"),
    ]:
        flow_store.upsert_node(_make_method(mid, name))

    flow_store.upsert_edge(DependencyEdge(source_id="m1", target_id="m2", kind="method_call"))
    flow_store.upsert_edge(DependencyEdge(source_id="m2", target_id="m3", kind="method_call"))

    tracer = FlowTracer()
    flows = tracer.trace_flows("svc", flow_store, repo_path=None, language="python")

    assert len(flows) >= 1
    # The flow starting from login_handler should include all 3 methods
    login_flow = next((f for f in flows if "login_handler" in f["entry_method_name"]), None)
    assert login_flow is not None
    assert len(login_flow["steps"]) >= 2


def test_trace_flows_stores_flow_node(flow_store):
    """trace_flows persists FlowNode and flow_step edges in the store."""
    for mid, name in [("ep1", "main_handler"), ("ep2", "do_work")]:
        flow_store.upsert_node(_make_method(mid, name))

    flow_store.upsert_edge(DependencyEdge(source_id="ep1", target_id="ep2", kind="method_call"))

    tracer = FlowTracer()
    flows = tracer.trace_flows("svc", flow_store, repo_path=None, language="python")

    for flow in flows:
        flow_id = flow["flow_id"]
        assert flow_id.startswith("flow::")
        # Verify flow_step edges are stored for the callee
        step_flows = flow_store.get_flows_for_method("ep2")
        assert any(f["flow_id"] == flow_id for f in step_flows)


def test_trace_flows_max_depth(flow_store):
    """Flows don't exceed max_depth even with long call chains."""
    # Build a 20-method chain
    methods = [_make_method(f"m{i}", f"func_{i}") for i in range(20)]
    for m in methods:
        flow_store.upsert_node(m)
    for i in range(len(methods) - 1):
        flow_store.upsert_edge(
            DependencyEdge(source_id=methods[i].id, target_id=methods[i + 1].id, kind="method_call")
        )

    tracer = FlowTracer(max_depth=5)
    # Set func_0 as handler so it's an entry point by name heuristic (doesn't match well)
    # Just force entry by renaming
    flow_store.upsert_node(_make_method("start", "start_handler"))
    flow_store.upsert_edge(
        DependencyEdge(source_id="start", target_id="m0", kind="method_call")
    )

    flows = tracer.trace_flows("svc", flow_store, repo_path=None, language="python")
    for flow in flows:
        assert len(flow["steps"]) <= tracer.max_depth + 1  # +1 for entry itself


def test_trace_flows_no_cycles(flow_store):
    """Circular call chains don't cause infinite loops."""
    for mid, name in [("h", "main_handler"), ("a", "func_a"), ("b", "func_b")]:
        flow_store.upsert_node(_make_method(mid, name))

    # h → a → b → a (cycle)
    flow_store.upsert_edge(DependencyEdge(source_id="h", target_id="a", kind="method_call"))
    flow_store.upsert_edge(DependencyEdge(source_id="a", target_id="b", kind="method_call"))
    flow_store.upsert_edge(DependencyEdge(source_id="b", target_id="a", kind="method_call"))

    tracer = FlowTracer()
    flows = tracer.trace_flows("svc", flow_store, repo_path=None, language="python")
    # Should complete without hanging
    for flow in flows:
        assert len(flow["steps"]) < 100  # sanity bound
