"""AWS infrastructure pattern definitions.

Covers:
- Terraform (``aws_*`` resource types)
- AWS CDK for TypeScript / Python (``new rds.DatabaseInstance``, etc.)
- CDKTF (``Rds.DatabaseInstance(``))
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Terraform resource type → (node_class_label, kind)
# node_class_label: "datastore" or "queue"
# ---------------------------------------------------------------------------
TF_RESOURCE_MAP: dict[str, tuple[str, str]] = {
    # RDS / relational databases
    "aws_db_instance":            ("datastore", "rds"),
    "aws_rds_cluster":            ("datastore", "rds"),
    "aws_rds_cluster_instance":   ("datastore", "rds"),
    # DynamoDB
    "aws_dynamodb_table":         ("datastore", "dynamodb"),
    # S3
    "aws_s3_bucket":              ("datastore", "s3"),
    # ElastiCache (Redis / Memcached)
    "aws_elasticache_cluster":    ("datastore", "redis"),
    "aws_elasticache_replication_group": ("datastore", "redis"),
    # SQS
    "aws_sqs_queue":              ("queue", "sqs"),
    # SNS
    "aws_sns_topic":              ("queue", "sns"),
    # MSK (managed Kafka)
    "aws_msk_cluster":            ("queue", "kafka"),
    "aws_msk_serverless_cluster": ("queue", "kafka"),
    # OpenSearch / Elasticsearch
    "aws_opensearch_domain":      ("datastore", "opensearch"),
    "aws_elasticsearch_domain":   ("datastore", "opensearch"),
}

# ---------------------------------------------------------------------------
# CDK / CDKTF patterns for TypeScript and Python source files.
# Each entry: (pattern_substring, node_class_label, kind)
# ---------------------------------------------------------------------------
CDK_PATTERNS: list[tuple[str, str, str]] = [
    # TypeScript CDK
    ("new rds.DatabaseInstance(",    "datastore", "rds"),
    ("new rds.CfnDBInstance(",       "datastore", "rds"),
    ("new rds.DatabaseCluster(",     "datastore", "rds"),
    ("new dynamodb.Table(",          "datastore", "dynamodb"),
    ("new s3.Bucket(",               "datastore", "s3"),
    ("new elasticache.CfnCacheCluster(", "datastore", "redis"),
    ("new sqs.Queue(",               "queue", "sqs"),
    ("new sns.Topic(",               "queue", "sns"),
    ("new msk.Cluster(",             "queue", "kafka"),
    # Python CDK / CDKTF
    ("rds.DatabaseInstance(",        "datastore", "rds"),
    ("rds.CfnDBInstance(",           "datastore", "rds"),
    ("dynamodb.Table(",              "datastore", "dynamodb"),
    ("s3.Bucket(",                   "datastore", "s3"),
    ("sqs.Queue(",                   "queue", "sqs"),
    ("sns.Topic(",                   "queue", "sns"),
    ("msk.Cluster(",                 "queue", "kafka"),
]
