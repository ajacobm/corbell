"""Execution flow tracer.

Detects entry points (HTTP handlers, CLI commands, workers, event handlers)
in a service and BFS-traverses the call graph to produce named execution
flows like "LoginFlow", "ProcessPaymentFlow".

This enables Linear task context like:
    "validate_token is step 2 of LoginFlow (entry: POST /login)"

Usage::

    from corbell.core.graph.flow_tracer import FlowTracer
    from corbell.core.graph.sqlite_store import SQLiteGraphStore

    store = SQLiteGraphStore("path/to/db")
    tracer = FlowTracer()
    flows = tracer.trace_flows("my-service", store, repo_path=Path("/path/to/repo"))
    # flows: [{"flow_id": ..., "flow_name": "LoginFlow", "steps": [...], ...}]
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from corbell.core.graph.schema import DependencyEdge, FlowNode, GraphStore, MethodNode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Entry point detection patterns
# ---------------------------------------------------------------------------

# Line-level patterns that indicate a method is an HTTP/CLI/Worker entry point
# Each entry: (regex or plain string, label)
_PYTHON_ENTRY_PATTERNS = [
    (re.compile(r'@(?:app|router|bp|blueprint)\.(get|post|put|delete|patch|route)\b'), "http"),
    (re.compile(r'@(?:app|celery)\.task\b'), "worker"),
    (re.compile(r'@click\.command\b'), "cli"),
    (re.compile(r'@typer\.command\b'), "cli"),
    (re.compile(r'if __name__\s*==\s*["\']__main__["\']'), "main"),
    (re.compile(r'@pytest\.mark\b'), None),           # skip test decorators
    (re.compile(r'def test_'), None),                  # skip test functions
]

_JS_ENTRY_PATTERNS = [
    (re.compile(r'(?:app|router)\.(get|post|put|delete|patch)\s*\('), "http"),
    (re.compile(r'exports\.handler\s*='), "lambda"),
    (re.compile(r'module\.exports\s*='), "export"),
    (re.compile(r'addEventListener\s*\('), "event"),
]

_GO_ENTRY_PATTERNS = [
    (re.compile(r'func main\s*\('), "main"),
    (re.compile(r'http\.HandleFunc\s*\('), "http"),
    (re.compile(r'(?:gin|mux|chi)\..*\.(?:GET|POST|PUT|DELETE|PATCH)\s*\('), "http"),
]

_JAVA_ENTRY_PATTERNS = [
    (re.compile(r'@(?:GetMapping|PostMapping|PutMapping|DeleteMapping|RequestMapping)\b'), "http"),
    (re.compile(r'public\s+static\s+void\s+main\s*\('), "main"),
    (re.compile(r'@(?:Scheduled|EventListener)\b'), "worker"),
]

_LANG_ENTRY_PATTERNS: Dict[str, list] = {
    "python":     _PYTHON_ENTRY_PATTERNS,
    "javascript": _JS_ENTRY_PATTERNS,
    "typescript": _JS_ENTRY_PATTERNS,
    "tsx":        _JS_ENTRY_PATTERNS,
    "go":         _GO_ENTRY_PATTERNS,
    "java":       _JAVA_ENTRY_PATTERNS,
}

# ---------------------------------------------------------------------------
# Name normalization helpers
# ---------------------------------------------------------------------------

_SKIP_PREFIXES = {"test", "Test", "mock", "Mock", "stub", "Stub"}


def _method_to_flow_name(method_name: str) -> str:
    """Convert a method name to a PascalCase flow name.

    Examples:
        ``login_handler``      → ``LoginHandlerFlow``
        ``processPayment``     → ``ProcessPaymentFlow``
        ``POST /users``        → ``PostUsersFlow``
    """
    # Strip common action prefixes that don't add meaning
    name = method_name.strip().lstrip("/")
    # CamelCase split
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    # Non-alphanumeric to underscores
    name = re.sub(r"[^a-zA-Z0-9]+", "_", name)
    parts = [p.capitalize() for p in name.split("_") if p]
    return "".join(parts) + "Flow"


# ---------------------------------------------------------------------------
# FlowTracer
# ---------------------------------------------------------------------------


class FlowTracer:
    """Detect entry points and trace execution flows through the call graph.

    Produces :class:`~corbell.core.graph.schema.FlowNode` nodes and
    ``flow_step`` edges that let Linear tasks say:
    "this method is step N of XFlow".
    """

    def __init__(self, max_depth: int = 10):
        """
        Args:
            max_depth: Maximum BFS depth from any entry point.
        """
        self.max_depth = max_depth

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def trace_flows(
        self,
        service_id: str,
        store: GraphStore,
        repo_path: Optional[Path] = None,
        language: str = "python",
    ) -> List[Dict[str, Any]]:
        """Detect entry points and trace BFS execution flows.

        Args:
            service_id: ID of the service to trace.
            store: Graph store containing method nodes and call edges.
            repo_path: Repository root (used to read source for entry point detection).
            language: Primary language of the service.

        Returns:
            List of flow dicts with keys ``flow_id``, ``flow_name``,
            ``entry_method_id``, ``entry_label``, ``steps`` (list of method IDs
            in BFS order).
        """
        methods = store.get_methods_for_service(service_id)
        if not methods:
            return []

        # Build adjacency index: caller_id -> set of callee_ids
        adjacency = self._build_adjacency(store, methods)

        # Detect entry points
        entry_points = self._detect_entry_points(methods, repo_path, language)
        if not entry_points:
            logger.debug("No entry points found for service %s", service_id)
            return []

        flows = []
        for ep_method, ep_label in entry_points:
            flow_steps = self._bfs_flow(ep_method.id, adjacency)
            if not flow_steps:
                continue

            flow_name = _method_to_flow_name(ep_method.method_name)
            flow_id = f"flow::{service_id}::{flow_name}"

            # Persist FlowNode
            flow_node = FlowNode(
                id=flow_id,
                name=flow_name,
                service_id=service_id,
                entry_method_id=ep_method.id,
                step_count=len(flow_steps),
            )
            store.upsert_node(flow_node)

            # Persist flow_step edges
            for step_num, method_id in enumerate(flow_steps, start=1):
                store.upsert_edge(
                    DependencyEdge(
                        source_id=flow_id,
                        target_id=method_id,
                        kind="flow_step",
                        metadata={
                            "step": step_num,
                            "flow_name": flow_name,
                            "entry_label": ep_label,
                        },
                    )
                )

            flows.append({
                "flow_id": flow_id,
                "flow_name": flow_name,
                "entry_method_id": ep_method.id,
                "entry_method_name": ep_method.method_name,
                "entry_label": ep_label,
                "steps": flow_steps,
                "step_count": len(flow_steps),
            })

        logger.debug(
            "FlowTracer: service=%s, entry_points=%d, flows=%d",
            service_id, len(entry_points), len(flows),
        )
        return flows

    def detect_entry_points(
        self,
        methods: List[MethodNode],
        repo_path: Optional[Path] = None,
        language: str = "python",
    ) -> List[MethodNode]:
        """Return methods that are likely entry points (public API)."""
        return [m for m, _ in self._detect_entry_points(methods, repo_path, language)]

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _build_adjacency(
        self,
        store: GraphStore,
        methods: List[MethodNode],
    ) -> Dict[str, Set[str]]:
        """Build caller→callee adjacency from store call edges."""
        adjacency: Dict[str, Set[str]] = defaultdict(set)
        method_ids = {m.id for m in methods}

        for method in methods:
            dep_edges = store.get_dependencies(method.id)
            for edge in dep_edges:
                if edge.kind == "method_call" and edge.target_id in method_ids:
                    adjacency[method.id].add(edge.target_id)

        return adjacency

    def _detect_entry_points(
        self,
        methods: List[MethodNode],
        repo_path: Optional[Path],
        language: str,
    ) -> List[tuple[MethodNode, str]]:
        """Return (MethodNode, label) pairs for detected entry points."""
        patterns = _LANG_ENTRY_PATTERNS.get(language, _PYTHON_ENTRY_PATTERNS)
        entry_points: List[tuple[MethodNode, str]] = []
        seen_ids: Set[str] = set()

        for method in methods:
            # Skip test/mock functions
            if any(method.method_name.startswith(p) for p in _SKIP_PREFIXES):
                continue
            if method.id in seen_ids:
                continue

            label = self._check_entry_point(method, repo_path, patterns)
            if label is not None:
                entry_points.append((method, label))
                seen_ids.add(method.id)

        return entry_points

    def _check_entry_point(
        self,
        method: MethodNode,
        repo_path: Optional[Path],
        patterns: list,
    ) -> Optional[str]:
        """Return entry point label if this method is an entry point, else None."""
        # Try to read the source file to check decorators / preceding lines
        source_lines: List[str] = []
        if repo_path and method.file_path:
            try:
                fp = Path(method.file_path)
                if not fp.is_absolute() and repo_path:
                    fp = repo_path / method.file_path
                if fp.exists():
                    all_lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
                    # Check a window of lines around the method definition
                    start = max(0, method.line_start - 6)
                    end = min(len(all_lines), method.line_start + 1)
                    source_lines = all_lines[start:end]
            except Exception:
                pass

        # Check method name heuristics (fast path)
        name_lower = method.method_name.lower()
        if any(kw in name_lower for kw in ("handler", "controller", "endpoint", "route", "main", "run", "start")):
            return "heuristic"

        # Check source patterns
        for pattern, label in patterns:
            if label is None:
                continue  # skip-patterns (tests, etc.)
            for line in source_lines:
                if isinstance(pattern, re.Pattern):
                    if pattern.search(line):
                        return label
                elif pattern in line:
                    return label

        return None

    def _bfs_flow(
        self, entry_id: str, adjacency: Dict[str, Set[str]]
    ) -> List[str]:
        """BFS from entry_id through call graph. Returns ordered list of method IDs."""
        visited: Set[str] = set()
        queue: deque[tuple[str, int]] = deque([(entry_id, 0)])
        result: List[str] = []

        while queue:
            current_id, depth = queue.popleft()
            if current_id in visited or depth > self.max_depth:
                continue
            visited.add(current_id)
            result.append(current_id)

            for callee_id in sorted(adjacency.get(current_id, set())):
                if callee_id not in visited:
                    queue.append((callee_id, depth + 1))

        return result
