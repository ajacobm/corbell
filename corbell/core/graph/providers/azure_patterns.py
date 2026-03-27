"""Azure infrastructure pattern definitions.

Covers:
- Terraform AzureRM provider (``azurerm_*`` resource types)
- Azure CDK for TypeScript / Python (``@cdktf/provider-azurerm``, ``azure-native``)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Terraform resource type → (node_class_label, kind)
# ---------------------------------------------------------------------------
TF_RESOURCE_MAP: dict[str, tuple[str, str]] = {
    # SQL / Relational
    "azurerm_sql_database":                    ("datastore", "azure_sql"),
    "azurerm_sql_server":                      ("datastore", "azure_sql"),
    "azurerm_mssql_database":                  ("datastore", "azure_sql"),
    "azurerm_postgresql_server":               ("datastore", "azure_sql"),
    "azurerm_postgresql_flexible_server":       ("datastore", "azure_sql"),
    "azurerm_mysql_server":                    ("datastore", "azure_sql"),
    "azurerm_mysql_flexible_server":           ("datastore", "azure_sql"),
    # CosmosDB (NoSQL / multi-model)
    "azurerm_cosmosdb_account":                ("datastore", "cosmosdb"),
    "azurerm_cosmosdb_sql_database":           ("datastore", "cosmosdb"),
    # Blob / data lake storage
    "azurerm_storage_account":                 ("datastore", "azure_blob"),
    "azurerm_storage_container":               ("datastore", "azure_blob"),
    # Redis Cache
    "azurerm_redis_cache":                     ("datastore", "redis"),
    # Service Bus (queues and topics)
    "azurerm_servicebus_namespace":            ("queue", "servicebus"),
    "azurerm_servicebus_queue":                ("queue", "servicebus"),
    "azurerm_servicebus_topic":                ("queue", "servicebus"),
    # Event Hub (streaming / Kafka-compatible)
    "azurerm_eventhub_namespace":              ("queue", "eventhub"),
    "azurerm_eventhub":                        ("queue", "eventhub"),
    # Event Grid
    "azurerm_eventgrid_topic":                 ("queue", "eventgrid"),
    "azurerm_eventgrid_domain":                ("queue", "eventgrid"),
    # Azure Data Explorer (Kusto)
    "azurerm_kusto_cluster":                   ("datastore", "kusto"),
}

# ---------------------------------------------------------------------------
# CDK / pulumi-azure / azure-native patterns for TypeScript and Python.
# ---------------------------------------------------------------------------
CDK_PATTERNS: list[tuple[str, str, str]] = [
    # TypeScript (azure-native SDK / Pulumi Azure)
    ("new sql.Database(",            "datastore", "azure_sql"),
    ("new postgres.Server(",         "datastore", "azure_sql"),
    ("new cosmos.DatabaseAccount(",  "datastore", "cosmosdb"),
    ("new storage.StorageAccount(",  "datastore", "azure_blob"),
    ("new redis.Redis(",             "datastore", "redis"),
    ("new servicebus.Queue(",        "queue", "servicebus"),
    ("new servicebus.Topic(",        "queue", "servicebus"),
    ("new eventhub.EventHub(",       "queue", "eventhub"),
    ("new eventgrid.Topic(",         "queue", "eventgrid"),
    # Python (pulumi-azure or azure-native)
    ("sql.Database(",                "datastore", "azure_sql"),
    ("cosmos.DatabaseAccount(",      "datastore", "cosmosdb"),
    ("storage.StorageAccount(",      "datastore", "azure_blob"),
    ("servicebus.Queue(",            "queue", "servicebus"),
    ("eventhub.EventHub(",           "queue", "eventhub"),
]
