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

_JS_DB_PATTERNS = [
    {"pattern": "pg.Pool(", "db_type": "postgres"},
    {"pattern": "new Pool(", "db_type": "postgres"},
    {"pattern": "createPool(", "db_type": "mysql"},
    {"pattern": "mongoose.connect(", "db_type": "mongodb"},
    {"pattern": "new MongoClient(", "db_type": "mongodb"},
    {"pattern": "redis.createClient(", "db_type": "redis"},
    {"pattern": "new Redis(", "db_type": "redis"},
    {"pattern": "createClient({", "db_type": "redis"},
    {"pattern": "new Sequelize(", "db_type": "postgres"},
    {"pattern": "DynamoDBClient(", "db_type": "dynamodb"},
    {"pattern": "createClient({ url", "db_type": "supabase"},
    {"pattern": "PrismaClient", "db_type": "postgres"},
    {"pattern": "knex(", "db_type": "postgres"},
]

_GO_DB_PATTERNS = [
    {"pattern": "sql.Open(", "db_type": "postgres"},
    {"pattern": "pgx.Connect(", "db_type": "postgres"},
    {"pattern": "gorm.Open(", "db_type": "postgres"},
    {"pattern": "mongo.Connect(", "db_type": "mongodb"},
    {"pattern": "redis.NewClient(", "db_type": "redis"},
    {"pattern": "dynamodb.New(", "db_type": "dynamodb"},
    {"pattern": "bolt.Open(", "db_type": "sqlite"},
    {"pattern": "neo4j.NewDriver(", "db_type": "neo4j"},
]

_JAVA_DB_PATTERNS = [
    {"pattern": "DriverManager.getConnection(", "db_type": "postgres"},
    {"pattern": "@Repository", "db_type": "postgres"},
    {"pattern": "JdbcTemplate", "db_type": "postgres"},
    {"pattern": "new MongoClient(", "db_type": "mongodb"},
    {"pattern": "MongoClients.create(", "db_type": "mongodb"},
    {"pattern": "JedisPool(", "db_type": "redis"},
    {"pattern": "RedisConnectionFactory", "db_type": "redis"},
    {"pattern": "EntityManager", "db_type": "postgres"},
]

_LANG_DB_PATTERNS: Dict[str, List] = {
    "python":     _PYTHON_DB_PATTERNS,
    "javascript": _JS_DB_PATTERNS,
    "typescript": _JS_DB_PATTERNS,
    "java":       _JAVA_DB_PATTERNS,
    "go":         _GO_DB_PATTERNS,
    "ruby":       [],
}

_PYTHON_QUEUE_PATTERNS = [
    {"pattern": "boto3.client('sqs')", "queue_type": "sqs"},
    {"pattern": "pika.BlockingConnection", "queue_type": "rabbitmq"},
    {"pattern": "KafkaProducer(", "queue_type": "kafka"},
    {"pattern": "KafkaConsumer(", "queue_type": "kafka"},
]

_JS_QUEUE_PATTERNS = [
    {"pattern": "new Kafka(", "queue_type": "kafka"},
    {"pattern": "kafkajs", "queue_type": "kafka"},
    {"pattern": "amqplib.connect(", "queue_type": "rabbitmq"},
    {"pattern": "new SQSClient(", "queue_type": "sqs"},
    {"pattern": "new Bull(", "queue_type": "redis"},
    {"pattern": "new Queue(", "queue_type": "redis"},
    {"pattern": "PubSub(", "queue_type": "pubsub"},
]

_GO_QUEUE_PATTERNS = [
    {"pattern": "kafka.NewWriter(", "queue_type": "kafka"},
    {"pattern": "sarama.NewClient(", "queue_type": "kafka"},
    {"pattern": "amqp.Dial(", "queue_type": "rabbitmq"},
    {"pattern": "sqs.New(", "queue_type": "sqs"},
    {"pattern": "pubsub.NewClient(", "queue_type": "pubsub"},
]

_JAVA_QUEUE_PATTERNS = [
    {"pattern": "KafkaProducer(", "queue_type": "kafka"},
    {"pattern": "@KafkaListener", "queue_type": "kafka"},
    {"pattern": "RabbitTemplate", "queue_type": "rabbitmq"},
    {"pattern": "@RabbitListener", "queue_type": "rabbitmq"},
    {"pattern": "AmazonSQS", "queue_type": "sqs"},
    {"pattern": "@SqsListener", "queue_type": "sqs"},
]

_LANG_QUEUE_PATTERNS: Dict[str, List] = {
    "python":     _PYTHON_QUEUE_PATTERNS,
    "javascript": _JS_QUEUE_PATTERNS,
    "typescript": _JS_QUEUE_PATTERNS,
    "java":       _JAVA_QUEUE_PATTERNS,
    "go":         _GO_QUEUE_PATTERNS,
    "ruby":       [],
}

_PYTHON_HTTP_PATTERNS = [
    {"pattern": "requests.get(", "call_type": "http_call"},
    {"pattern": "requests.post(", "call_type": "http_call"},
    {"pattern": "httpx.AsyncClient", "call_type": "http_call"},
    {"pattern": "aiohttp.ClientSession", "call_type": "http_call"},
    {"pattern": "urllib.request", "call_type": "http_call"},
]

_JS_HTTP_PATTERNS = [
    {"pattern": "fetch(", "call_type": "http_call"},
    {"pattern": "axios.get(", "call_type": "http_call"},
    {"pattern": "axios.post(", "call_type": "http_call"},
    {"pattern": "axios.request(", "call_type": "http_call"},
    {"pattern": "axios.create(", "call_type": "http_call"},
    {"pattern": "http.get(", "call_type": "http_call"},
    {"pattern": "got.get(", "call_type": "http_call"},
    {"pattern": "superagent.get(", "call_type": "http_call"},
]

_GO_HTTP_PATTERNS = [
    {"pattern": "http.Get(", "call_type": "http_call"},
    {"pattern": "http.Post(", "call_type": "http_call"},
    {"pattern": "http.NewRequest(", "call_type": "http_call"},
    {"pattern": "client.Do(", "call_type": "http_call"},
]

_JAVA_HTTP_PATTERNS = [
    {"pattern": "HttpClient", "call_type": "http_call"},
    {"pattern": "RestTemplate", "call_type": "http_call"},
    {"pattern": "WebClient", "call_type": "http_call"},
    {"pattern": "HttpURLConnection", "call_type": "http_call"},
    {"pattern": "OkHttpClient", "call_type": "http_call"},
]

_LANG_HTTP_PATTERNS: Dict[str, List] = {
    "python":     _PYTHON_HTTP_PATTERNS,
    "javascript": _JS_HTTP_PATTERNS,
    "typescript": _JS_HTTP_PATTERNS,
    "java":       _JAVA_HTTP_PATTERNS,
    "go":         _GO_HTTP_PATTERNS,
    "ruby":       [],
}

# Env-var patterns that indicate a URL is looked up from config (any language)
_ENV_URL_PATTERNS = [
    "process.env.", "os.getenv(", "os.environ[",
    "System.getenv(", "os.Getenv(",
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

        # Phase 4: method-level graph + git coupling + flow tracing
        service_diagnostics: Dict[str, Any] = {}
        if method_level:
            from corbell.core.graph.flow_tracer import FlowTracer
            from corbell.core.graph.git_coupling import GitCouplingAnalyzer
            from corbell.core.graph.method_graph import MethodGraphBuilder

            mgb = MethodGraphBuilder(self.store)
            coupling_analyzer = GitCouplingAnalyzer()
            flow_tracer = FlowTracer()

            for svc in discovered:
                svc_id = svc["id"]
                lang = svc.get("language", "python")

                # 4a. Build method-level call graph
                result = mgb.build_for_service(svc_id, svc["repo_path"])
                service_diagnostics[svc_id] = result

                # 4b. Git coupling edges (best-effort)
                try:
                    coupling_count = coupling_analyzer.build_coupling_edges(
                        svc_id, svc["repo_path"], self.store
                    )
                    service_diagnostics[svc_id]["git_coupling_edges"] = coupling_count
                except Exception:
                    pass

                # 4c. Execution flow tracing (best-effort)
                try:
                    flows = flow_tracer.trace_flows(
                        svc_id, self.store,
                        repo_path=svc["repo_path"],
                        language=lang,
                    )
                    service_diagnostics[svc_id]["flows"] = len(flows)
                    service_diagnostics[svc_id]["flow_names"] = [
                        f["flow_name"] for f in flows
                    ]
                except Exception:
                    pass

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
        patterns = _LANG_DB_PATTERNS.get(lang, [])

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
        lang = svc.get("language", "python")
        patterns = _LANG_QUEUE_PATTERNS.get(lang, [])

        for fp in svc["files"]:
            content = self._read(fp)
            for pdef in patterns:
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
        lang = svc.get("language", "python")
        patterns = _LANG_HTTP_PATTERNS.get(lang, [])

        for fp in svc["files"]:
            content = self._read(fp)
            has_http_client = any(p["pattern"] in content for p in patterns)
            if not has_http_client:
                continue

            # 1. Hard-coded URL matching — service name in URL
            urls = re.findall(r'["\']https?://([^"\'/:]+)', content)
            for url_host in urls:
                for other_id in all_service_ids:
                    if other_id == svc_id:
                        continue
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

            # 2. Env-var URL references — log as unresolved external call
            for env_pat in _ENV_URL_PATTERNS:
                if env_pat in content:
                    # Extract env var name that likely contains a URL
                    env_vars = re.findall(
                        r'(?:process\.env\.|os\.getenv\(|os\.environ\[|System\.getenv\(|os\.Getenv\()'
                        r'["\']?([A-Z_][A-Z0-9_]*)["\']?',
                        content,
                    )
                    for var in env_vars:
                        if any(kw in var for kw in ("URL", "HOST", "ENDPOINT", "BASE", "API")):
                            self.store.upsert_edge(
                                DependencyEdge(
                                    source_id=svc_id,
                                    target_id="external:env_url",
                                    kind="http_call",
                                    metadata={
                                        "env_var": var,
                                        "file": str(fp.name),
                                        "note": "env-var URL; target unresolved at build time",
                                    },
                                )
                            )
                    break  # one env-var pattern match per file is enough
