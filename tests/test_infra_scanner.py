"""Tests for multi-cloud infrastructure scanner.

Covers three improvements:
1. Resource-level parser (Terraform + CDK) for AWS, Azure, GCP.
2. ``provisions`` edges from infra stack to resources.
3. ``uses_infra_resource`` edges from app services via env-var tracing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from corbell.core.graph.infra_scanner import InfraScanner
from corbell.core.graph.schema import DataStoreNode, QueueNode
from corbell.core.graph.sqlite_store import SQLiteGraphStore
from corbell.core.graph.builder import ServiceGraphBuilder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_infra_repo(tmp_path: Path, name: str = "my-infra") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    return repo


def _nodes_by_kind(nodes, kind: str):
    return [n for n in nodes if n.kind == kind]


def _edges_by_kind(edges, kind: str):
    return [e for e in edges if e.kind == kind]


# ===========================================================================
# Improvement 1: Resource parser — AWS
# ===========================================================================

class TestAWSTerraform:
    def test_rds_creates_datastore_node(self, tmp_path):
        repo = _make_infra_repo(tmp_path)
        (repo / "main.tf").write_text(
            'resource "aws_db_instance" "prod_db" {\n  engine = "postgres"\n}\n'
        )
        scanner = InfraScanner()
        results = scanner.scan(repo, "cdk-infra")
        datastores = [r for r in results if isinstance(r, DataStoreNode)]
        assert any(d.kind == "rds" for d in datastores), "Expected RDS DataStoreNode"

    def test_sqs_creates_queue_node(self, tmp_path):
        repo = _make_infra_repo(tmp_path)
        (repo / "queues.tf").write_text(
            'resource "aws_sqs_queue" "order_queue" {\n  name = "orders"\n}\n'
        )
        scanner = InfraScanner()
        results = scanner.scan(repo, "cdk-infra")
        queues = [r for r in results if isinstance(r, QueueNode)]
        assert any(q.kind == "sqs" for q in queues), "Expected SQS QueueNode"

    def test_s3_creates_datastore_node(self, tmp_path):
        repo = _make_infra_repo(tmp_path)
        (repo / "storage.tf").write_text(
            'resource "aws_s3_bucket" "uploads_bucket" {\n  bucket = "my-uploads"\n}\n'
        )
        scanner = InfraScanner()
        results = scanner.scan(repo, "cdk-infra")
        datastores = [r for r in results if isinstance(r, DataStoreNode)]
        assert any(d.kind == "s3" for d in datastores), "Expected S3 DataStoreNode"

    def test_dynamodb_creates_datastore_node(self, tmp_path):
        repo = _make_infra_repo(tmp_path)
        (repo / "tables.tf").write_text(
            'resource "aws_dynamodb_table" "sessions" {\n  name = "sessions"\n}\n'
        )
        scanner = InfraScanner()
        results = scanner.scan(repo, "cdk-infra")
        datastores = [r for r in results if isinstance(r, DataStoreNode)]
        assert any(d.kind == "dynamodb" for d in datastores), "Expected DynamoDB DataStoreNode"

    def test_sns_creates_queue_node(self, tmp_path):
        repo = _make_infra_repo(tmp_path)
        (repo / "topics.tf").write_text(
            'resource "aws_sns_topic" "alerts" {\n  name = "alerts"\n}\n'
        )
        scanner = InfraScanner()
        results = scanner.scan(repo, "cdk-infra")
        queues = [r for r in results if isinstance(r, QueueNode)]
        assert any(q.kind == "sns" for q in queues), "Expected SNS QueueNode"


class TestAWSCDKTypeScript:
    def test_cdk_ts_rds_creates_datastore_node(self, tmp_path):
        repo = _make_infra_repo(tmp_path)
        (repo / "stack.ts").write_text(
            'const db = new rds.DatabaseInstance(this, "MyDB", {\n  engine: rds.DatabaseInstanceEngine.POSTGRES\n});\n'
        )
        scanner = InfraScanner()
        results = scanner.scan(repo, "cdk-infra")
        datastores = [r for r in results if isinstance(r, DataStoreNode)]
        assert any(d.kind == "rds" for d in datastores), "CDK TS RDS not detected"

    def test_cdk_ts_sqs_creates_queue_node(self, tmp_path):
        repo = _make_infra_repo(tmp_path)
        (repo / "stack.ts").write_text(
            'const queue = new sqs.Queue(this, "OrderQueue", { queueName: "order-queue" });\n'
        )
        scanner = InfraScanner()
        results = scanner.scan(repo, "cdk-infra")
        queues = [r for r in results if isinstance(r, QueueNode)]
        assert any(q.kind == "sqs" for q in queues), "CDK TS SQS not detected"


# ===========================================================================
# Improvement 1: Resource parser — Azure
# ===========================================================================

class TestAzureTerraform:
    def test_sql_database_creates_datastore_node(self, tmp_path):
        repo = _make_infra_repo(tmp_path)
        (repo / "main.tf").write_text(
            'resource "azurerm_sql_database" "app_db" {\n  name = "app-db"\n}\n'
        )
        scanner = InfraScanner()
        results = scanner.scan(repo, "az-infra")
        datastores = [r for r in results if isinstance(r, DataStoreNode)]
        assert any(d.kind == "azure_sql" for d in datastores), "Expected Azure SQL DataStoreNode"

    def test_cosmosdb_creates_datastore_node(self, tmp_path):
        repo = _make_infra_repo(tmp_path)
        (repo / "cosmos.tf").write_text(
            'resource "azurerm_cosmosdb_account" "main" {\n  name = "mycosmosdb"\n}\n'
        )
        scanner = InfraScanner()
        results = scanner.scan(repo, "az-infra")
        datastores = [r for r in results if isinstance(r, DataStoreNode)]
        assert any(d.kind == "cosmosdb" for d in datastores), "Expected CosmosDB DataStoreNode"

    def test_servicebus_creates_queue_node(self, tmp_path):
        repo = _make_infra_repo(tmp_path)
        (repo / "messaging.tf").write_text(
            'resource "azurerm_servicebus_namespace" "ns" {\n  name = "my-servicebus"\n}\n'
        )
        scanner = InfraScanner()
        results = scanner.scan(repo, "az-infra")
        queues = [r for r in results if isinstance(r, QueueNode)]
        assert any(q.kind == "servicebus" for q in queues), "Expected ServiceBus QueueNode"

    def test_eventhub_creates_queue_node(self, tmp_path):
        repo = _make_infra_repo(tmp_path)
        (repo / "events.tf").write_text(
            'resource "azurerm_eventhub_namespace" "events" {\n  name = "my-eventhub"\n}\n'
        )
        scanner = InfraScanner()
        results = scanner.scan(repo, "az-infra")
        queues = [r for r in results if isinstance(r, QueueNode)]
        assert any(q.kind == "eventhub" for q in queues), "Expected EventHub QueueNode"

    def test_storage_account_creates_datastore_node(self, tmp_path):
        repo = _make_infra_repo(tmp_path)
        (repo / "storage.tf").write_text(
            'resource "azurerm_storage_account" "blobs" {\n  name = "mystorageaccount"\n}\n'
        )
        scanner = InfraScanner()
        results = scanner.scan(repo, "az-infra")
        datastores = [r for r in results if isinstance(r, DataStoreNode)]
        assert any(d.kind == "azure_blob" for d in datastores), "Expected Azure Blob DataStoreNode"


# ===========================================================================
# Improvement 1: Resource parser — GCP
# ===========================================================================

class TestGCPTerraform:
    def test_cloud_sql_creates_datastore_node(self, tmp_path):
        repo = _make_infra_repo(tmp_path)
        (repo / "main.tf").write_text(
            'resource "google_sql_database_instance" "primary" {\n  database_version = "POSTGRES_14"\n}\n'
        )
        scanner = InfraScanner()
        results = scanner.scan(repo, "gcp-infra")
        datastores = [r for r in results if isinstance(r, DataStoreNode)]
        assert any(d.kind == "cloud_sql" for d in datastores), "Expected Cloud SQL DataStoreNode"

    def test_gcs_bucket_creates_datastore_node(self, tmp_path):
        repo = _make_infra_repo(tmp_path)
        (repo / "storage.tf").write_text(
            'resource "google_storage_bucket" "assets" {\n  name = "my-assets"\n}\n'
        )
        scanner = InfraScanner()
        results = scanner.scan(repo, "gcp-infra")
        datastores = [r for r in results if isinstance(r, DataStoreNode)]
        assert any(d.kind == "gcs" for d in datastores), "Expected GCS DataStoreNode"

    def test_pubsub_topic_creates_queue_node(self, tmp_path):
        repo = _make_infra_repo(tmp_path)
        (repo / "pubsub.tf").write_text(
            'resource "google_pubsub_topic" "events" {\n  name = "events"\n}\n'
        )
        scanner = InfraScanner()
        results = scanner.scan(repo, "gcp-infra")
        queues = [r for r in results if isinstance(r, QueueNode)]
        assert any(q.kind == "pubsub" for q in queues), "Expected Pub/Sub QueueNode"

    def test_bigtable_creates_datastore_node(self, tmp_path):
        repo = _make_infra_repo(tmp_path)
        (repo / "bigtable.tf").write_text(
            'resource "google_bigtable_instance" "timeline" {\n  name = "timeline"\n}\n'
        )
        scanner = InfraScanner()
        results = scanner.scan(repo, "gcp-infra")
        datastores = [r for r in results if isinstance(r, DataStoreNode)]
        assert any(d.kind == "bigtable" for d in datastores), "Expected Bigtable DataStoreNode"


# ===========================================================================
# Improvement 2: ``provisions`` edges
# ===========================================================================

class TestProvisionsEdges:
    def test_provisions_edges_created_aws(self, tmp_path):
        """Infra service with TF resources must have ``provisions`` edges."""
        db = tmp_path / "test.db"
        store = SQLiteGraphStore(str(db))
        builder = ServiceGraphBuilder(store)

        infra_repo = _make_infra_repo(tmp_path)
        (infra_repo / "main.tf").write_text(
            'resource "aws_db_instance" "prod_db" {}\n'
            'resource "aws_sqs_queue" "jobs" {}\n'
        )
        (infra_repo / "package.json").write_text(
            json.dumps({"dependencies": {"aws-cdk-lib": "^2.0.0"}})
        )

        builder.build_from_workspace([
            {"id": "cdk-infra", "repo": str(infra_repo), "language": "typescript"},
        ])

        edges = store.get_dependencies("cdk-infra")
        provisions_edges = _edges_by_kind(edges, "provisions")
        assert len(provisions_edges) >= 2, (
            f"Expected >=2 provisions edges, got {len(provisions_edges)}"
        )
        target_kinds = {e.target_id.split(":")[1] for e in provisions_edges}
        assert "rds" in target_kinds, "Missing provisions edge to RDS"
        assert "sqs" in target_kinds, "Missing provisions edge to SQS"

    def test_provisions_edges_created_azure(self, tmp_path):
        """Azure infra service must emit provisions edges."""
        db = tmp_path / "test.db"
        store = SQLiteGraphStore(str(db))
        builder = ServiceGraphBuilder(store)

        infra_repo = _make_infra_repo(tmp_path, "az-infra-repo")
        (infra_repo / "main.tf").write_text(
            'resource "azurerm_postgresql_flexible_server" "main" {}\n'
            'resource "azurerm_servicebus_namespace" "ns" {}\n'
        )
        (infra_repo / "package.json").write_text(
            json.dumps({"dependencies": {"@cdktf/provider-azurerm": "^5.0.0", "cdktf": "^0.15.0"}})
        )

        builder.build_from_workspace([
            {"id": "az-infra", "repo": str(infra_repo), "language": "typescript"},
        ])

        edges = store.get_dependencies("az-infra")
        provisions_edges = _edges_by_kind(edges, "provisions")
        assert len(provisions_edges) >= 2, (
            f"Expected >=2 provisions edges for Azure, got {len(provisions_edges)}"
        )

    def test_provisions_edges_created_gcp(self, tmp_path):
        """GCP infra service must emit provisions edges."""
        db = tmp_path / "test.db"
        store = SQLiteGraphStore(str(db))
        builder = ServiceGraphBuilder(store)

        infra_repo = _make_infra_repo(tmp_path, "gcp-infra-repo")
        (infra_repo / "main.tf").write_text(
            'resource "google_sql_database_instance" "primary" {}\n'
            'resource "google_pubsub_topic" "events" {}\n'
        )
        (infra_repo / "package.json").write_text(
            json.dumps({"dependencies": {"@cdktf/provider-google": "^5.0.0", "cdktf": "^0.15.0"}})
        )

        builder.build_from_workspace([
            {"id": "gcp-infra", "repo": str(infra_repo), "language": "typescript"},
        ])

        edges = store.get_dependencies("gcp-infra")
        provisions_edges = _edges_by_kind(edges, "provisions")
        assert len(provisions_edges) >= 2, (
            f"Expected >=2 provisions edges for GCP, got {len(provisions_edges)}"
        )

    def test_normal_service_no_provisions_edges(self, tmp_path):
        """A normal Python service must not produce any provisions edges."""
        db = tmp_path / "test.db"
        store = SQLiteGraphStore(str(db))
        builder = ServiceGraphBuilder(store)

        app_repo = tmp_path / "app-service"
        app_repo.mkdir()
        (app_repo / "main.py").write_text("import flask\napp = Flask(__name__)\n")

        builder.build_from_workspace([
            {"id": "app-svc", "repo": str(app_repo), "language": "python"},
        ])

        edges = store.get_dependencies("app-svc")
        provisions_edges = _edges_by_kind(edges, "provisions")
        assert len(provisions_edges) == 0, "Normal service should not have provisions edges"


# ===========================================================================
# Improvement 3: Env-var tracing
# ===========================================================================

class TestEnvVarTracing:
    def _build_graph_with_infra_and_app(self, tmp_path, app_code: str):
        """Helper: create an infra + app service and build graph."""
        db = tmp_path / "test.db"
        store = SQLiteGraphStore(str(db))
        builder = ServiceGraphBuilder(store)

        # Infra repo: defines prod_db via Terraform
        infra_repo = tmp_path / "infra"
        infra_repo.mkdir()
        (infra_repo / "main.tf").write_text(
            'resource "aws_db_instance" "prod_db" {}\n'
        )
        (infra_repo / "package.json").write_text(
            json.dumps({"dependencies": {"aws-cdk-lib": "^2.0.0"}})
        )

        # App service repo
        app_repo = tmp_path / "app"
        app_repo.mkdir()
        (app_repo / "db.py").write_text(app_code)

        builder.build_from_workspace([
            {"id": "cdk-infra", "repo": str(infra_repo), "language": "typescript"},
            {"id": "app-service", "repo": str(app_repo), "language": "python"},
        ])
        return store

    def test_env_var_tracing_links_app_to_rds(self, tmp_path):
        """App reading PROD_DB_URL must get a uses_infra_resource edge to the RDS node."""
        store = self._build_graph_with_infra_and_app(
            tmp_path,
            'import os\nDB_URL = os.getenv("PROD_DB_URL")\n',
        )
        edges = store.get_dependencies("app-service")
        infra_edges = _edges_by_kind(edges, "uses_infra_resource")
        assert len(infra_edges) >= 1, (
            f"Expected uses_infra_resource edge for PROD_DB_URL, got {len(infra_edges)}. "
            f"All edges: {[(e.kind, e.target_id) for e in edges]}"
        )
        assert any("rds" in e.target_id for e in infra_edges), (
            "uses_infra_resource edge should point to an RDS resource"
        )

    def test_env_var_tracing_metadata_contains_var_name(self, tmp_path):
        """The ``uses_infra_resource`` edge metadata must include the env var name."""
        store = self._build_graph_with_infra_and_app(
            tmp_path,
            'import os\nDATABASE_URL = os.getenv("PROD_DB_URL")\n',
        )
        edges = store.get_dependencies("app-service")
        infra_edges = _edges_by_kind(edges, "uses_infra_resource")
        assert infra_edges, "No uses_infra_resource edges found"
        env_vars = [e.metadata.get("env_var") for e in infra_edges]
        assert "PROD_DB_URL" in env_vars, f"Expected PROD_DB_URL in edge metadata, got {env_vars}"

    def test_env_var_no_false_positive(self, tmp_path):
        """An unrelated env var must NOT produce a uses_infra_resource edge."""
        store = self._build_graph_with_infra_and_app(
            tmp_path,
            'import os\nSOME_CONFIG = os.getenv("SOME_RANDOM_CONFIG")\n',
        )
        edges = store.get_dependencies("app-service")
        infra_edges = _edges_by_kind(edges, "uses_infra_resource")
        assert len(infra_edges) == 0, (
            f"Expected no uses_infra_resource edges for irrelevant env var, got {len(infra_edges)}"
        )

    def test_env_var_tracing_no_edge_without_infra(self, tmp_path):
        """If there is no infra service, no uses_infra_resource edges are emitted."""
        db = tmp_path / "test.db"
        store = SQLiteGraphStore(str(db))
        builder = ServiceGraphBuilder(store)

        app_repo = tmp_path / "app"
        app_repo.mkdir()
        (app_repo / "db.py").write_text('import os\nURL = os.getenv("MY_DB_URL")\n')

        builder.build_from_workspace([
            {"id": "app-service", "repo": str(app_repo), "language": "python"},
        ])
        edges = store.get_dependencies("app-service")
        infra_edges = _edges_by_kind(edges, "uses_infra_resource")
        assert len(infra_edges) == 0, "No infra, so no uses_infra_resource edges expected"

    def test_multi_cloud_env_var_tracing(self, tmp_path):
        """Azure infra resource can also be traced via env-var matching."""
        db = tmp_path / "test.db"
        store = SQLiteGraphStore(str(db))
        builder = ServiceGraphBuilder(store)

        # Azure infra
        infra_repo = tmp_path / "az-infra"
        infra_repo.mkdir()
        (infra_repo / "main.tf").write_text(
            'resource "azurerm_cosmosdb_account" "main_cosmos" {}\n'
        )
        (infra_repo / "package.json").write_text(
            json.dumps({"dependencies": {"cdktf": "^0.15.0", "@cdktf/provider-azurerm": "^5.0.0"}})
        )

        # App service using CosmosDB connection string env var
        app_repo = tmp_path / "app"
        app_repo.mkdir()
        (app_repo / "cosmos_client.py").write_text(
            'import os\nCOSMOS_URL = os.getenv("MAIN_COSMOS_URL")\n'
        )

        builder.build_from_workspace([
            {"id": "az-infra", "repo": str(infra_repo), "language": "typescript"},
            {"id": "app-service", "repo": str(app_repo), "language": "python"},
        ])

        edges = store.get_dependencies("app-service")
        infra_edges = _edges_by_kind(edges, "uses_infra_resource")
        assert len(infra_edges) >= 1, (
            f"Expected uses_infra_resource edge for Azure CosmosDB, got {len(infra_edges)}"
        )
        assert any("cosmosdb" in e.target_id for e in infra_edges), (
            "Expected cosmosdb in target_id"
        )


# ===========================================================================
# Deduplication
# ===========================================================================

class TestDeduplication:
    def test_same_tf_resource_not_duplicated(self, tmp_path):
        """Two .tf files with the same resource type+name should emit one node."""
        repo = _make_infra_repo(tmp_path)
        (repo / "a.tf").write_text('resource "aws_s3_bucket" "uploads" {}\n')
        (repo / "b.tf").write_text('resource "aws_s3_bucket" "uploads" {}\n')
        scanner = InfraScanner()
        results = scanner.scan(repo, "infra")
        s3_nodes = [r for r in results if isinstance(r, DataStoreNode) and r.kind == "s3"]
        assert len(s3_nodes) == 1, f"Expected 1 deduplicated S3 node, got {len(s3_nodes)}"
