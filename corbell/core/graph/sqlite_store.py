"""SQLite-backed implementation of the GraphStore interface."""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

from corbell.core.graph.schema import (
    DataStoreNode,
    DependencyEdge,
    FlowNode,
    GraphStore,
    MethodNode,
    QueueNode,
    ServiceNode,
)

_CREATE_NODES = """
CREATE TABLE IF NOT EXISTS graph_nodes (
    id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL,
    data TEXT NOT NULL
);
"""

_CREATE_EDGES = """
CREATE TABLE IF NOT EXISTS graph_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    UNIQUE(source_id, target_id, kind)
);
"""

_CREATE_IDX_SOURCE = "CREATE INDEX IF NOT EXISTS idx_edges_source ON graph_edges(source_id);"
_CREATE_IDX_TARGET = "CREATE INDEX IF NOT EXISTS idx_edges_target ON graph_edges(target_id);"


def _node_to_dict(node: ServiceNode | DataStoreNode | QueueNode | MethodNode) -> dict:
    """Serialize any node dataclass to a plain dict."""
    from dataclasses import asdict
    d = asdict(node)
    # Convert lists inside fields
    for k, v in d.items():
        if isinstance(v, Path):
            d[k] = str(v)
    return d


def _dict_to_node(node_type: str, data: dict) -> ServiceNode | DataStoreNode | QueueNode | MethodNode | FlowNode:
    """Deserialize a dict back to a typed node dataclass."""
    if node_type == "service":
        return ServiceNode(**{k: v for k, v in data.items() if k in ServiceNode.__dataclass_fields__})
    if node_type == "datastore":
        return DataStoreNode(**data)
    if node_type == "queue":
        return QueueNode(**data)
    if node_type == "method":
        return MethodNode(**{k: v for k, v in data.items() if k in MethodNode.__dataclass_fields__})
    if node_type == "flow":
        return FlowNode(**{k: v for k, v in data.items() if k in FlowNode.__dataclass_fields__})
    raise ValueError(f"Unknown node_type: {node_type}")


def _node_type_str(node) -> str:
    if isinstance(node, ServiceNode):
        return "service"
    if isinstance(node, DataStoreNode):
        return "datastore"
    if isinstance(node, QueueNode):
        return "queue"
    if isinstance(node, MethodNode):
        return "method"
    if isinstance(node, FlowNode):
        return "flow"
    raise TypeError(f"Unsupported node type: {type(node)}")


class SQLiteGraphStore(GraphStore):
    """Graph store backed by a local SQLite database.

    Creates two tables: ``graph_nodes`` and ``graph_edges``. All node data is
    stored as JSON blobs for schema flexibility.
    """

    def __init__(self, db_path: Path | str):
        """Initialize the store, creating the database file if needed.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(_CREATE_NODES)
            conn.execute(_CREATE_EDGES)
            conn.execute(_CREATE_IDX_SOURCE)
            conn.execute(_CREATE_IDX_TARGET)
            conn.commit()

    def upsert_node(self, node) -> None:
        """Insert or update a node."""
        node_type = _node_type_str(node)
        data = _node_to_dict(node)
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO graph_nodes (id, node_type, data) VALUES (?, ?, ?)",
                (node.id, node_type, json.dumps(data)),
            )
            conn.commit()

    def upsert_edge(self, edge: DependencyEdge) -> None:
        """Insert or update an edge (unique on source+target+kind)."""
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO graph_edges (source_id, target_id, kind, metadata)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(source_id, target_id, kind)
                   DO UPDATE SET metadata = excluded.metadata""",
                (edge.source_id, edge.target_id, edge.kind, json.dumps(edge.metadata)),
            )
            conn.commit()

    def _load_node(self, row) -> ServiceNode | DataStoreNode | QueueNode | MethodNode:
        return _dict_to_node(row["node_type"], json.loads(row["data"]))

    def get_service(self, service_id: str) -> Optional[ServiceNode]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM graph_nodes WHERE id = ? AND node_type = 'service'",
                (service_id,),
            ).fetchone()
            if row:
                return self._load_node(row)
        return None

    def get_all_services(self) -> List[ServiceNode]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM graph_nodes WHERE node_type = 'service'"
            ).fetchall()
            return [self._load_node(r) for r in rows]

    def get_dependencies(self, service_id: str) -> List[DependencyEdge]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM graph_edges WHERE source_id = ?", (service_id,)
            ).fetchall()
            return [
                DependencyEdge(
                    source_id=r["source_id"],
                    target_id=r["target_id"],
                    kind=r["kind"],
                    metadata=json.loads(r["metadata"]),
                )
                for r in rows
            ]

    def get_dependents(self, service_id: str) -> List[DependencyEdge]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM graph_edges WHERE target_id = ?", (service_id,)
            ).fetchall()
            return [
                DependencyEdge(
                    source_id=r["source_id"],
                    target_id=r["target_id"],
                    kind=r["kind"],
                    metadata=json.loads(r["metadata"]),
                )
                for r in rows
            ]

    def get_method(self, method_id: str) -> Optional[MethodNode]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM graph_nodes WHERE id = ? AND node_type = 'method'",
                (method_id,),
            ).fetchone()
            if row:
                return self._load_node(row)
        return None

    def get_call_path(
        self, from_method_id: str, to_method_id: str, max_depth: int = 5
    ) -> List[List[str]]:
        """BFS to find all call paths between two method nodes."""
        paths: List[List[str]] = []
        queue: deque[List[str]] = deque([[from_method_id]])

        with self._conn() as conn:
            while queue:
                path = queue.popleft()
                if len(path) > max_depth:
                    continue
                current = path[-1]
                if current == to_method_id:
                    paths.append(path)
                    continue
                rows = conn.execute(
                    "SELECT target_id FROM graph_edges WHERE source_id = ? AND kind = 'method_call'",
                    (current,),
                ).fetchall()
                for row in rows:
                    neighbor = row["target_id"]
                    if neighbor not in path:  # avoid cycles
                        queue.append(path + [neighbor])
        return paths

    def get_methods_for_service(self, service_id: str) -> List[MethodNode]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM graph_nodes WHERE node_type = 'method'"
            ).fetchall()
            results = []
            for row in rows:
                data = json.loads(row["data"])
                if data.get("service_id") == service_id:
                    results.append(_dict_to_node("method", data))
            return results

    def get_callers_of_method(self, method_id: str) -> List[MethodNode]:
        """Return all MethodNodes that have a method_call edge targeting method_id."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT source_id FROM graph_edges WHERE target_id = ? AND kind = 'method_call'",
                (method_id,),
            ).fetchall()
            caller_ids = [r["source_id"] for r in rows]

        result: List[MethodNode] = []
        with self._conn() as conn:
            for cid in caller_ids:
                row = conn.execute(
                    "SELECT * FROM graph_nodes WHERE id = ? AND node_type = 'method'",
                    (cid,),
                ).fetchone()
                if row:
                    result.append(self._load_node(row))  # type: ignore[arg-type]
        return result

    def get_flows_for_method(self, method_id: str) -> List[dict]:
        """Return flows that include method_id as a step.

        Each returned dict has keys: ``flow_id``, ``flow_name``, ``step``,
        ``entry_method_id``.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT source_id, metadata FROM graph_edges "
                "WHERE target_id = ? AND kind = 'flow_step'",
                (method_id,),
            ).fetchall()

        result = []
        with self._conn() as conn:
            for row in rows:
                flow_id = row["source_id"]
                meta = json.loads(row["metadata"] or "{}")
                flow_row = conn.execute(
                    "SELECT data FROM graph_nodes WHERE id = ? AND node_type = 'flow'",
                    (flow_id,),
                ).fetchone()
                if flow_row:
                    flow_data = json.loads(flow_row["data"])
                    result.append({
                        "flow_id": flow_id,
                        "flow_name": flow_data.get("name", ""),
                        "step": meta.get("step", 0),
                        "entry_method_id": flow_data.get("entry_method_id", ""),
                    })
        return result

    def get_all_nodes_summary(self) -> Dict[str, Any]:
        with self._conn() as conn:
            node_counts = conn.execute(
                "SELECT node_type, COUNT(*) as cnt FROM graph_nodes GROUP BY node_type"
            ).fetchall()
            edge_count = conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
        return {
            "nodes": {r["node_type"]: r["cnt"] for r in node_counts},
            "edges": edge_count,
        }

    def clear(self) -> None:
        """Delete all graph data."""
        with self._conn() as conn:
            conn.execute("DELETE FROM graph_nodes")
            conn.execute("DELETE FROM graph_edges")
            conn.commit()
