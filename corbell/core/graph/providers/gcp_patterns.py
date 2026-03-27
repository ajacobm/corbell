"""GCP infrastructure pattern definitions.

Covers:
- Terraform Google provider (``google_*`` resource types)
- GCP CDK for TypeScript / Python (``@cdktf/provider-google``, Pulumi GCP)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Terraform resource type → (node_class_label, kind)
# ---------------------------------------------------------------------------
TF_RESOURCE_MAP: dict[str, tuple[str, str]] = {
    # Cloud SQL
    "google_sql_database_instance": ("datastore", "cloud_sql"),
    "google_sql_database":          ("datastore", "cloud_sql"),
    # Bigtable
    "google_bigtable_instance":     ("datastore", "bigtable"),
    "google_bigtable_table":        ("datastore", "bigtable"),
    # Firestore / Datastore
    "google_firestore_document":    ("datastore", "firestore"),
    "google_datastore_index":       ("datastore", "firestore"),
    # Spanner
    "google_spanner_instance":      ("datastore", "spanner"),
    "google_spanner_database":      ("datastore", "spanner"),
    # Memorystore (Redis)
    "google_redis_instance":        ("datastore", "redis"),
    # GCS (Cloud Storage)
    "google_storage_bucket":        ("datastore", "gcs"),
    # Pub/Sub
    "google_pubsub_topic":          ("queue", "pubsub"),
    "google_pubsub_subscription":   ("queue", "pubsub"),
    # BiqQuery (analytical)
    "google_bigquery_dataset":      ("datastore", "bigquery"),
    "google_bigquery_table":        ("datastore", "bigquery"),
}

# ---------------------------------------------------------------------------
# CDK / Pulumi GCP patterns for TypeScript and Python.
# ---------------------------------------------------------------------------
CDK_PATTERNS: list[tuple[str, str, str]] = [
    # TypeScript (Pulumi GCP / CDKTF google)
    ("new sql.DatabaseInstance(",   "datastore", "cloud_sql"),
    ("new bigtable.Instance(",      "datastore", "bigtable"),
    ("new firestore.Document(",     "datastore", "firestore"),
    ("new spanner.Instance(",       "datastore", "spanner"),
    ("new redis.Instance(",         "datastore", "redis"),
    ("new storage.Bucket(",         "datastore", "gcs"),
    ("new pubsub.Topic(",           "queue", "pubsub"),
    ("new pubsub.Subscription(",    "queue", "pubsub"),
    ("new bigquery.Dataset(",       "datastore", "bigquery"),
    # Python
    ("sql.DatabaseInstance(",       "datastore", "cloud_sql"),
    ("bigtable.Instance(",          "datastore", "bigtable"),
    ("storage.Bucket(",             "datastore", "gcs"),
    ("pubsub.Topic(",               "queue", "pubsub"),
    ("pubsub.Subscription(",        "queue", "pubsub"),
    ("bigquery.Dataset(",           "datastore", "bigquery"),
]
