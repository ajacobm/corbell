"""Corbell architecture graph UI — HTTP API server.

Serves the single-page app at / and JSON data at /api/*.
Zero runtime dependencies beyond Python stdlib + existing Corbell core.
"""

from __future__ import annotations

import json
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Workspace / store helpers
# ---------------------------------------------------------------------------


def _find_workspace(start: Optional[Path] = None) -> Optional[Path]:
    """Resolve workspace.yaml location.

    Priority:
    1. CORBELL_WORKSPACE env var (absolute path to workspace root)
    2. Walk up from start (or cwd) looking for corbell-data/workspace.yaml
    """
    import os
    env_root = os.environ.get("CORBELL_WORKSPACE")
    if env_root:
        p = Path(env_root)
        candidates = [
            p / "corbell-data" / "workspace.yaml",
            p / "workspace.yaml",
        ]
        for c in candidates:
            if c.exists():
                return c
    from corbell.core.workspace import find_workspace_root
    root = find_workspace_root(start or Path.cwd())
    if root:
        for sub in (root / "corbell-data" / "workspace.yaml", root / "workspace.yaml"):
            if sub.exists():
                return sub
    return None


def _load_cfg(ws_yaml: Path):
    from corbell.core.workspace import load_workspace
    config_dir = ws_yaml.parent
    return load_workspace(ws_yaml), config_dir


def _open_db(cfg, config_dir: Path) -> sqlite3.Connection:
    db_path = cfg.db_path(config_dir)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------


def _fetch_graph(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Return nodes and edges for the D3 graph."""
    nodes = []
    edges = []

    # Nodes
    rows = conn.execute("SELECT id, node_type, data FROM graph_nodes").fetchall()
    for row in rows:
        ntype = row["node_type"]
        data = json.loads(row["data"])
        node = {"id": row["id"], "type": ntype}
        if ntype == "service":
            node.update({
                "label": data.get("name", row["id"]),
                "language": data.get("language", ""),
                "service_type": data.get("service_type", "api"),
                "tags": data.get("tags", []),
            })
        elif ntype == "datastore":
            node.update({"label": data.get("name", row["id"]), "kind": data.get("kind", "")})
        elif ntype == "queue":
            node.update({"label": data.get("name", row["id"]), "kind": data.get("kind", "")})
        elif ntype == "flow":
            svc_id = data.get("service_id", "")
            node.update({
                "label": data.get("name", row["id"]),
                "service_id": svc_id,
                "step_count": data.get("step_count", 0),
            })
            if svc_id:
                edges.append({
                    "source": svc_id,
                    "target": row["id"],
                    "kind": "flow_link",
                    "meta": {}
                })
        elif ntype == "method":
            continue  # don't clutter service-level graph with method nodes
        nodes.append(node)

    # Count methods per service for node sizing
    method_counts: Dict[str, int] = {}
    mcounts = conn.execute(
        "SELECT data FROM graph_nodes WHERE node_type='method'"
    ).fetchall()
    for row in mcounts:
        d = json.loads(row["data"])
        sid = d.get("service_id", "")
        if sid:
            method_counts[sid] = method_counts.get(sid, 0) + 1
    for n in nodes:
        if n["type"] == "service":
            n["method_count"] = method_counts.get(n["id"], 0)

    # Edges — skip method_call edges (too many, clutter service graph) + flow_step
    skip_kinds = {"method_call", "flow_step"}
    erows = conn.execute(
        "SELECT source_id, target_id, kind, metadata FROM graph_edges"
    ).fetchall()
    seen = set()
    for row in erows:
        if row["kind"] in skip_kinds:
            continue
        key = (row["source_id"], row["target_id"], row["kind"])
        if key in seen:
            continue
        seen.add(key)
        meta = json.loads(row["metadata"] or "{}")
        edges.append({
            "source": row["source_id"],
            "target": row["target_id"],
            "kind": row["kind"],
            "meta": meta,
        })

    return {"nodes": nodes, "edges": edges}


def _fetch_service_detail(conn: sqlite3.Connection, service_id: str) -> Dict[str, Any]:
    """Return full detail for one service (methods, deps, callers, flows, coupling)."""
    # Service node
    row = conn.execute(
        "SELECT data FROM graph_nodes WHERE id=? AND node_type='service'",
        (service_id,)
    ).fetchone()
    if not row:
        return {"error": f"Service '{service_id}' not found"}
    svc = json.loads(row["data"])

    # Methods (top 60)
    mrows = conn.execute(
        "SELECT id, data FROM graph_nodes WHERE node_type='method'",
    ).fetchall()
    methods = []
    svc_method_ids = set()
    for mr in mrows:
        d = json.loads(mr["data"])
        if d.get("service_id") == service_id:
            svc_method_ids.add(mr["id"])
            methods.append({
                "id": mr["id"],
                "name": d.get("method_name", ""),
                "class_name": d.get("class_name"),
                "signature": d.get("typed_signature") or d.get("signature", ""),
                "file": Path(d.get("file_path", "")).name,
                "line": d.get("line_start", 0),
                "docstring": d.get("docstring"),
            })
    methods.sort(key=lambda m: (m["file"], m["line"]))

    # Internal method calls
    method_edges = []
    if svc_method_ids:
        placeholders = ",".join("?" * len(svc_method_ids))
        query = f"SELECT source_id, target_id FROM graph_edges WHERE kind='method_call' AND source_id IN ({placeholders}) AND target_id IN ({placeholders})"
        try:
            call_rows = conn.execute(query, list(svc_method_ids) * 2).fetchall()
            for cr in call_rows:
                method_edges.append({"source": cr["source_id"], "target": cr["target_id"]})
        except Exception:
            pass

    # Outbound deps
    dep_rows = conn.execute(
        "SELECT target_id, kind, metadata FROM graph_edges WHERE source_id=?",
        (service_id,)
    ).fetchall()
    deps_out = []
    for dr in dep_rows:
        if dr["kind"] in ("method_call", "flow_step"):
            continue
        meta = json.loads(dr["metadata"] or "{}")
        deps_out.append({"target": dr["target_id"], "kind": dr["kind"], "meta": meta})

    # Inbound callers (services that have http_call edge pointing here)
    caller_rows = conn.execute(
        "SELECT source_id, kind FROM graph_edges WHERE target_id=? AND kind='http_call'",
        (service_id,)
    ).fetchall()
    callers = [{"source": r["source_id"], "kind": r["kind"]} for r in caller_rows]

    # Flows for this service
    flow_rows = conn.execute(
        "SELECT id, data FROM graph_nodes WHERE node_type='flow'",
    ).fetchall()
    flows = []
    for fr in flow_rows:
        d = json.loads(fr["data"])
        if d.get("service_id") == service_id:
            flows.append({
                "id": fr["id"],
                "name": d.get("name", ""),
                "step_count": d.get("step_count", 0),
            })

    # Git coupling pairs
    coupling_rows = conn.execute(
        "SELECT metadata FROM graph_edges WHERE source_id=? AND kind='git_coupling'",
        (service_id,)
    ).fetchall()
    coupling = []
    for cr in coupling_rows:
        meta = json.loads(cr["metadata"] or "{}")
        if "file_a" in meta:
            coupling.append({
                "file_a": meta["file_a"],
                "file_b": meta["file_b"],
                "strength": meta.get("strength", 0),
            })

    return {
        "id": service_id,
        "name": svc.get("name", service_id),
        "language": svc.get("language", ""),
        "service_type": svc.get("service_type", "api"),
        "tags": svc.get("tags", []),
        "repo": svc.get("repo", ""),
        "methods": methods[:60],
        "method_count": len(methods),
        "deps_out": deps_out,
        "callers": callers,
        "flows": flows,
        "coupling": coupling[:20],
        "method_edges": method_edges,
    }


def _fetch_constraints(ws_yaml: Path) -> List[Dict[str, Any]]:
    """Scan all specs/*.md for constraints blocks and YAML frontmatter."""
    constraints = []
    specs_dir = ws_yaml.parent.parent / "specs"
    if not specs_dir.exists():
        # Try one level up
        specs_dir = ws_yaml.parent.parent.parent / "specs"
    if not specs_dir.exists():
        return constraints

    # Regex for markdown constraint bullets inside comment block
    BLOCK_RE = re.compile(
        r"<!--\s*CORBELL_CONSTRAINTS_START\s*-->(.*?)<!--\s*CORBELL_CONSTRAINTS_END\s*-->",
        re.DOTALL,
    )
    BULLET_RE = re.compile(r"^\s*[-*]\s+\*\*([^*]+)\*\*[:\s]*(.*)", re.MULTILINE)

    for md_file in sorted(specs_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8", errors="ignore")
        spec_name = md_file.name

        # 1. Parse YAML frontmatter constraints
        try:
            import yaml
            fm_match = re.match(r"^---\n(.*?)\n---\n?", content, re.DOTALL)
            if fm_match:
                fm_data = yaml.safe_load(fm_match.group(1)) or {}
                for c in fm_data.get("constraints", {}).get("manual", []):
                    text = c.get("text", "")
                    if text:
                        constraints.append({"text": text, "source": spec_name, "origin": "frontmatter"})
        except Exception:
            pass

        # 2. Parse markdown constraint block
        for block_match in BLOCK_RE.finditer(content):
            block_text = block_match.group(1)
            for m in BULLET_RE.finditer(block_text):
                label = m.group(1).strip()
                detail = m.group(2).strip()
                text = f"{label}: {detail}" if detail else label
                constraints.append({"text": text, "source": spec_name, "origin": "markdown"})

    # Deduplicate by text
    seen_texts = set()
    unique = []
    for c in constraints:
        if c["text"] not in seen_texts:
            seen_texts.add(c["text"])
            unique.append(c)

    return unique


def _fetch_flows(conn: sqlite3.Connection) -> List[Dict]:
    rows = conn.execute(
        "SELECT id, data FROM graph_nodes WHERE node_type='flow'"
    ).fetchall()
    result = []
    for r in rows:
        d = json.loads(r["data"])
        result.append({
            "id": r["id"],
            "name": d.get("name", ""),
            "service_id": d.get("service_id", ""),
            "step_count": d.get("step_count", 0),
        })
    return result


def _workspace_name(cfg) -> str:
    try:
        return cfg.workspace.name
    except Exception:
        return "my-platform"


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------


class CorbelUIHandler(BaseHTTPRequestHandler):
    """Handles all HTTP requests for the Corbell UI."""

    ws_yaml: Path  # set by factory

    def log_message(self, fmt, *args):  # silence access log
        pass

    def _json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, content: str):
        body = content.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/":
            from corbell.core.ui.html import build_page
            try:
                cfg, config_dir = _load_cfg(self.ws_yaml)
                ws_name = _workspace_name(cfg)
            except Exception:
                ws_name = "workspace"
            self._html(build_page(ws_name))
            return

        if path == "/api/graph":
            try:
                cfg, config_dir = _load_cfg(self.ws_yaml)
                conn = _open_db(cfg, config_dir)
                data = _fetch_graph(conn)
                conn.close()
                self._json(data)
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return

        if path.startswith("/api/service/"):
            svc_id = path[len("/api/service/"):]
            try:
                cfg, config_dir = _load_cfg(self.ws_yaml)
                conn = _open_db(cfg, config_dir)
                data = _fetch_service_detail(conn, svc_id)
                conn.close()
                self._json(data)
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return

        if path == "/api/constraints":
            try:
                data = _fetch_constraints(self.ws_yaml)
                self._json(data)
            except Exception as e:
                self._json({"error": str(e), "items": []}, 500)
            return

        if path == "/api/flows":
            try:
                cfg, config_dir = _load_cfg(self.ws_yaml)
                conn = _open_db(cfg, config_dir)
                data = _fetch_flows(conn)
                conn.close()
                self._json(data)
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return

        self.send_response(404)
        self.end_headers()


def make_handler(ws_yaml: Path):
    """Create a handler class bound to a specific workspace."""
    class BoundHandler(CorbelUIHandler):
        pass
    BoundHandler.ws_yaml = ws_yaml
    return BoundHandler


def run_server(port: int, ws_yaml: Path) -> HTTPServer:
    """Create and return the HTTPServer (caller starts it)."""
    handler = make_handler(ws_yaml)
    server = HTTPServer(("127.0.0.1", port), handler)
    return server
