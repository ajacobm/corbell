"""Service-level graph builder.

Scans local repos and builds a service dependency graph.
Scans local repos, detects service boundaries, DB/queue deps, and HTTP calls.
No Neo4j dependency — uses the pluggable GraphStore interface.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from corbell.core.graph.schema import (
    DataStoreNode,
    DependencyEdge,
    GraphStore,
    QueueNode,
    ServiceNode,
)

# ---------------------------------------------------------------------------
# Service pattern detection rules
# ---------------------------------------------------------------------------

_PYTHON_SERVICE_PATTERNS = [
    {"pattern": "FastAPI(", "type": "api", "framework": "fastapi"},
    {"pattern": "Flask(__name__)", "type": "api", "framework": "flask"},
    {"pattern": "@app.route", "type": "api", "framework": "flask"},
    {"pattern": "@celery.task", "type": "worker", "framework": "celery"},
    {"pattern": "@app.task", "type": "worker", "framework": "celery"},
    {"pattern": "@click.command", "type": "cli", "framework": "click"},
    {"pattern": "argparse.ArgumentParser", "type": "cli", "framework": "argparse"},
    {"pattern": "typer.Typer(", "type": "cli", "framework": "typer"},
    {"pattern": "if __name__ == '__main__':", "type": "service", "framework": "stdlib"},
]

_JS_SERVICE_PATTERNS = [
    {"pattern": "express()", "type": "api", "framework": "express"},
    {"pattern": "app.listen(", "type": "api", "framework": "express"},
    {"pattern": "@Controller(", "type": "api", "framework": "nestjs"},
]

_JAVA_SERVICE_PATTERNS = [
    {"pattern": "@RestController", "type": "api", "framework": "spring"},
    {"pattern": "@Controller", "type": "api", "framework": "spring"},
    {"pattern": "public static void main(", "type": "service", "framework": "stdlib"},
]

_GO_SERVICE_PATTERNS = [
    {"pattern": "http.ListenAndServe", "type": "api", "framework": "net/http"},
    {"pattern": "gin.Default()", "type": "api", "framework": "gin"},
    {"pattern": "func main()", "type": "service", "framework": "stdlib"},
]

_LANG_SERVICE_PATTERNS = {
    "python": _PYTHON_SERVICE_PATTERNS,
    "javascript": _JS_SERVICE_PATTERNS,
    "typescript": _JS_SERVICE_PATTERNS,
    "java": _JAVA_SERVICE_PATTERNS,
    "go": _GO_SERVICE_PATTERNS,
}

_PYTHON_DB_PATTERNS = [
    {"pattern": "psycopg2.connect", "db_type": "postgres"},
    {"pattern": "create_engine(", "db_type": "postgres"},
    {"pattern": "asyncpg.create_pool", "db_type": "postgres"},
    {"pattern": "MongoClient(", "db_type": "mongodb"},
    {"pattern": "redis.Redis(", "db_type": "redis"},
    {"pattern": "redis.StrictRedis(", "db_type": "redis"},
    {"pattern": "boto3.resource('dynamodb')", "db_type": "dynamodb"},
    {"pattern": "sqlite3.connect", "db_type": "sqlite"},
    {"pattern": "chromadb.PersistentClient", "db_type": "chromadb"},
    {"pattern": "GraphDatabase.driver", "db_type": "neo4j"},
]

_PYTHON_QUEUE_PATTERNS = [
    {"pattern": "boto3.client('sqs')", "queue_type": "sqs"},
    {"pattern": "pika.BlockingConnection", "queue_type": "rabbitmq"},
    {"pattern": "KafkaProducer(", "queue_type": "kafka"},
    {"pattern": "KafkaConsumer(", "queue_type": "kafka"},
]

_PYTHON_HTTP_PATTERNS = [
    {"pattern": "requests.get(", "call_type": "http_call"},
    {"pattern": "requests.post(", "call_type": "http_call"},
    {"pattern": "httpx.AsyncClient", "call_type": "http_call"},
    {"pattern": "aiohttp.ClientSession", "call_type": "http_call"},
    {"pattern": "urllib.request", "call_type": "http_call"},
]

_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", "env", ".venv",
    ".pytest_cache", "dist", "build", ".next", ".nuxt", "target", "bin",
    "obj", "coverage", ".tox",
}

_EXTENSION_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rb": "ruby",
}


class ServiceGraphBuilder:
    """Build a service-level dependency graph by scanning local repositories."""

    def __init__(self, graph_store: GraphStore):
        """Initialize with any GraphStore backend.

        Args:
            graph_store: Instance of :class:`~corbell.core.graph.schema.GraphStore`.
        """
        self.store = graph_store

    def build_from_workspace(
        self,
        services: List[Dict[str, Any]],
        clear_existing: bool = True,
        method_level: bool = False,
    ) -> Dict[str, Any]:
        """Scan all service repos and populate the graph.

        Args:
            services: List of dicts with keys ``id``, ``repo`` (resolved path),
                ``language``, ``tags``.
            clear_existing: Clear the store before building.
            method_level: If True, also build method-call edges.

        Returns:
            Summary dict with counts of services, datastores, queues, methods.
        """
        if clear_existing:
            self.store.clear()

        discovered: List[Dict] = []

        for svc in services:
            svc_id = svc["id"]
            repo_path = Path(svc.get("resolved_path") or svc["repo"])
            language = svc.get("language", "python")
            tags = svc.get("tags", [])

            if not repo_path.exists():
                continue

            node = ServiceNode(
                id=svc_id,
                name=svc_id,
                repo=str(repo_path),
                language=language,
                tags=tags,
            )
            self.store.upsert_node(node)
            discovered.append(
                {
                    "id": svc_id,
                    "repo_path": repo_path,
                    "language": language,
                    "files": list(self._iter_files(repo_path, language)),
                }
            )

        # Phase 2: deps and HTTP calls
        datastore_ids: set = set()
        queue_ids: set = set()

        for svc in discovered:
            self._detect_db_deps(svc, datastore_ids)
            self._detect_queue_deps(svc, queue_ids)

        # Phase 3: inter-service HTTP calls (best-effort heuristic)
        all_service_ids = {s["id"] for s in discovered}
        for svc in discovered:
            self._detect_http_calls(svc, all_service_ids)

        # Phase 4: method-level graph
        service_diagnostics: Dict[str, Any] = {}
        if method_level:
            from corbell.core.graph.method_graph import MethodGraphBuilder
            mgb = MethodGraphBuilder(self.store)
            for svc in discovered:
                result = mgb.build_for_service(svc["id"], svc["repo_path"])
                service_diagnostics[svc["id"]] = result

        summary = self.store.get_all_nodes_summary()
        if service_diagnostics:
            summary["service_diagnostics"] = service_diagnostics
        return summary

    # ------------------------------------------------------------------ #
    # Internal scanning helpers                                            #
    # ------------------------------------------------------------------ #

    def _iter_files(self, repo_path: Path, language: str):
        """Yield all scannable files in a repo."""
        for fp in repo_path.rglob("*"):
            if not fp.is_file():
                continue
            if self._should_skip(fp):
                continue
            if _EXTENSION_LANG.get(fp.suffix) == language or fp.suffix in _EXTENSION_LANG:
                yield fp

    def _should_skip(self, fp: Path) -> bool:
        if any(part in _SKIP_DIRS for part in fp.parts):
            return True
        name = fp.name
        if name.startswith("test_") or name.endswith("_test.py"):
            return True
        return False

    def _read(self, fp: Path) -> str:
        try:
            return fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    def _detect_db_deps(self, svc: Dict, datastore_ids: set) -> None:
        svc_id = svc["id"]
        lang = svc.get("language", "python")
        patterns = _PYTHON_DB_PATTERNS if lang == "python" else []

        for fp in svc["files"]:
            content = self._read(fp)
            for pdef in patterns:
                if pdef["pattern"] in content:
                    db_type = pdef["db_type"]
                    ds_id = f"datastore:{svc_id}:{db_type}"
                    if ds_id not in datastore_ids:
                        datastore_ids.add(ds_id)
                        self.store.upsert_node(DataStoreNode(id=ds_id, kind=db_type, name=f"{db_type}-db"))
                    self.store.upsert_edge(
                        DependencyEdge(
                            source_id=svc_id,
                            target_id=ds_id,
                            kind="db_read",
                            metadata={"file": str(fp.name)},
                        )
                    )

    def _detect_queue_deps(self, svc: Dict, queue_ids: set) -> None:
        svc_id = svc["id"]
        for fp in svc["files"]:
            content = self._read(fp)
            for pdef in _PYTHON_QUEUE_PATTERNS:
                if pdef["pattern"] in content:
                    q_type = pdef["queue_type"]
                    q_id = f"queue:{svc_id}:{q_type}"
                    if q_id not in queue_ids:
                        queue_ids.add(q_id)
                        self.store.upsert_node(QueueNode(id=q_id, kind=q_type, name=f"{q_type}-queue"))
                    self.store.upsert_edge(
                        DependencyEdge(
                            source_id=svc_id,
                            target_id=q_id,
                            kind="queue_publish",
                            metadata={"file": str(fp.name)},
                        )
                    )

    def _detect_http_calls(self, svc: Dict, all_service_ids: set) -> None:
        svc_id = svc["id"]
        for fp in svc["files"]:
            content = self._read(fp)
            for pdef in _PYTHON_HTTP_PATTERNS:
                if pdef["pattern"] not in content:
                    continue
                # Try to find URLs and match to known services
                urls = re.findall(r'["\']https?://([^"\']+)["\']', content)
                for url_host in urls:
                    for other_id in all_service_ids:
                        if other_id == svc_id:
                            continue
                        # Simple heuristic: service name appears in URL
                        svc_slug = other_id.replace("-", "").replace("_", "").lower()
                        url_clean = url_host.replace("-", "").replace("_", "").lower()
                        if svc_slug in url_clean:
                            self.store.upsert_edge(
                                DependencyEdge(
                                    source_id=svc_id,
                                    target_id=other_id,
                                    kind="http_call",
                                    metadata={"url": url_host, "file": str(fp.name)},
                                )
                            )
