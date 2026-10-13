# Databricks notebook source
# MAGIC %md
# MAGIC # Quetzal IQ · Managed Agent Memory
# MAGIC
# MAGIC Provisiona idempotentemente o Memory Store governado e concede somente ao
# MAGIC service principal do Databricks App permissão de leitura e escrita.

# COMMAND ----------

import json

from databricks.sdk import WorkspaceClient

dbutils.widgets.text("catalog", "classic_stable_douglas_s_catalog")
dbutils.widgets.text("schema", "quetzal_telecom")
dbutils.widgets.text("memory_store", "quetzal_iq_memory")
dbutils.widgets.text("app_name", "quetzal-command-center")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
store = dbutils.widgets.get("memory_store")
app_name = dbutils.widgets.get("app_name")
full_name = f"{catalog}.{schema}.{store}"
client = WorkspaceClient()
base_path = "/api/2.1/unity-catalog/memory-stores"

listed = client.api_client.do(
    "GET", base_path, query={"catalog_name": catalog, "schema_name": schema}
) or {}
stores = listed.get("memory_stores", listed.get("stores", [])) if isinstance(listed, dict) else listed
existing_names = {
    item.get("full_name") or ".".join(
        filter(None, [item.get("catalog_name"), item.get("schema_name"), item.get("name")])
    )
    for item in stores
}

if full_name in existing_names:
    action = "REUSED"
else:
    client.api_client.do(
        "POST",
        base_path,
        body={
            "name": store,
            "catalog_name": catalog,
            "schema_name": schema,
            "description": (
                "Quetzal IQ managed long-term memory. Per-user trusted scope; "
                "external research preferences and context; no secrets."
            ),
        },
    )
    action = "CREATED"

verified = client.api_client.do("GET", f"{base_path}/{full_name}")
assert isinstance(verified, dict), verified

# The Apps control plane is the trusted source of the service principal ID.
app = client.api_client.do("GET", f"/api/2.0/apps/{app_name}")
principal = app.get("service_principal_client_id") or app.get("service_principal_name")
if not principal:
    raise AssertionError(f"App service principal unavailable for {app_name}")

permission_path = f"/api/2.1/unity-catalog/permissions/memory_store/{full_name}"
client.api_client.do(
    "PATCH",
    permission_path,
    body={
        "changes": [{
            "principal": principal,
            "add": ["READ_MEMORY_STORE", "WRITE_MEMORY_STORE"],
        }]
    },
)
permissions = client.api_client.do("GET", permission_path) or {}

print(json.dumps({
    "status": "PASSED",
    "action": action,
    "memory_store": full_name,
    "scope_strategy": "trusted authenticated Databricks Apps user",
    "app_principal": principal,
    "permission_assignments": len(permissions.get("privilege_assignments", [])),
}, ensure_ascii=False))

