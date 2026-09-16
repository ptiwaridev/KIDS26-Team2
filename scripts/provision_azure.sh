#!/usr/bin/env bash
# Provisions the Azure resources for the clinical RAG stack: resource group,
# Azure SQL (server + DB + firewall), Azure AI Search, and an Azure AI
# Foundry resource for embeddings + generation.
#
# Idempotent-ish (uses --only-show-errors and 'az ... create' which mostly
# no-ops on existing resources with the same name), but read through before
# running against a shared subscription. Requires `az login` first.
#
# Usage: ./scripts/provision_azure.sh
# Override any var below via environment, e.g.:
#   LOCATION=westus2 SQL_ADMIN_PASSWORD='...' ./scripts/provision_azure.sh
# Or set SQL_ADMIN_PASSWORD (and any other override) in your local .env —
# gitignored, safe for this — and it's picked up automatically below.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

RESOURCE_GROUP="${RESOURCE_GROUP:-biohackathon-clinical-rag}"
LOCATION="${LOCATION:-eastus}"

SQL_SERVER_NAME="${SQL_SERVER_NAME:-biohack-sql-$RANDOM}"
SQL_DB_NAME="${SQL_DB_NAME:-mimic_subset}"
SQL_ADMIN_USER="${SQL_ADMIN_USER:-sqladmin}"
SQL_ADMIN_PASSWORD="${SQL_ADMIN_PASSWORD:?Set SQL_ADMIN_PASSWORD before running (min 8 chars, mixed case/digits/symbols)}"
SQL_SKU="${SQL_SKU:-GP_S_Gen5_1}"  # serverless General Purpose, cheapest for a hackathon

SEARCH_SERVICE_NAME="${SEARCH_SERVICE_NAME:-biohack-search-$RANDOM}"
SEARCH_SKU="${SEARCH_SKU:-basic}"

FOUNDRY_RESOURCE_NAME="${FOUNDRY_RESOURCE_NAME:-biohack-foundry}"

echo "== Resource group =="
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --only-show-errors -o table

echo "== Azure SQL server + database =="
az sql server create \
    --name "$SQL_SERVER_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --admin-user "$SQL_ADMIN_USER" \
    --admin-password "$SQL_ADMIN_PASSWORD" \
    --only-show-errors -o table

az sql server firewall-rule create \
    --resource-group "$RESOURCE_GROUP" \
    --server "$SQL_SERVER_NAME" \
    --name AllowAzureServices \
    --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0 \
    --only-show-errors -o table

# Hackathon convenience only — restricts nothing by IP so all 8 laptops can
# connect without individually whitelisting. Tighten before this ever holds
# real MIMIC data.
az sql server firewall-rule create \
    --resource-group "$RESOURCE_GROUP" \
    --server "$SQL_SERVER_NAME" \
    --name AllowAllDev \
    --start-ip-address 0.0.0.0 --end-ip-address 255.255.255.255 \
    --only-show-errors -o table

az sql db create \
    --resource-group "$RESOURCE_GROUP" \
    --server "$SQL_SERVER_NAME" \
    --name "$SQL_DB_NAME" \
    --edition GeneralPurpose \
    --family Gen5 --capacity 1 \
    --compute-model Serverless \
    --auto-pause-delay 60 \
    --only-show-errors -o table

echo "== Azure AI Search =="
az search service create \
    --name "$SEARCH_SERVICE_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --sku "$SEARCH_SKU" \
    --only-show-errors -o table

echo "== Azure AI Foundry resource (embeddings) =="
# Creates the underlying Cognitive Services / AI Services account that backs
# an Azure AI Foundry project. text-embedding-3-small deploys fine via CLI.
az cognitiveservices account create \
    --name "$FOUNDRY_RESOURCE_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --kind AIServices \
    --sku S0 \
    --custom-domain "$FOUNDRY_RESOURCE_NAME" \
    --only-show-errors -o table

az cognitiveservices account deployment create \
    --name "$FOUNDRY_RESOURCE_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --deployment-name text-embedding-3-small \
    --model-name text-embedding-3-small \
    --model-version "1" \
    --model-format OpenAI \
    --sku-capacity 30 \
    --sku-name Standard \
    --only-show-errors -o table

cat <<'EOF'

== Manual step: Claude Sonnet 5 model deployment ==
Anthropic models on Azure AI Foundry are distributed via Azure Marketplace
and (as of this writing) require accepting marketplace terms interactively —
this isn't reliably scriptable via `az cli`. In the Azure AI Foundry portal:
  1. Open the Foundry project backed by the resource created above.
  2. Model catalog -> search "Claude Sonnet 5" -> Deploy.
  3. Accept the marketplace terms, choose the "Version 2 / Azure-hosted"
     deployment option (keeps data in-tenant), name the deployment
     "claude-sonnet-5" to match AZURE_CHAT_DEPLOYMENT in .env.example.

EOF

echo "== Fetching connection info =="
SQL_CONN_STRING="Driver={ODBC Driver 18 for SQL Server};Server=tcp:${SQL_SERVER_NAME}.database.windows.net,1433;Database=${SQL_DB_NAME};Uid=${SQL_ADMIN_USER};Pwd=${SQL_ADMIN_PASSWORD};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
SEARCH_ENDPOINT="https://${SEARCH_SERVICE_NAME}.search.windows.net"
SEARCH_KEY=$(az search admin-key show --resource-group "$RESOURCE_GROUP" --service-name "$SEARCH_SERVICE_NAME" --query primaryKey -o tsv)
FOUNDRY_ENDPOINT=$(az cognitiveservices account show --name "$FOUNDRY_RESOURCE_NAME" --resource-group "$RESOURCE_GROUP" --query properties.endpoint -o tsv)
FOUNDRY_KEY=$(az cognitiveservices account keys list --name "$FOUNDRY_RESOURCE_NAME" --resource-group "$RESOURCE_GROUP" --query key1 -o tsv)

cat <<EOF

== Copy these into your .env ==
AZURE_SQL_SERVER=${SQL_SERVER_NAME}.database.windows.net
AZURE_SQL_DATABASE=${SQL_DB_NAME}
AZURE_SQL_USERNAME=${SQL_ADMIN_USER}
AZURE_SQL_PASSWORD=${SQL_ADMIN_PASSWORD}
AZURE_SQL_CONNECTION_STRING=${SQL_CONN_STRING}

AZURE_SEARCH_ENDPOINT=${SEARCH_ENDPOINT}
AZURE_SEARCH_API_KEY=${SEARCH_KEY}
AZURE_SEARCH_INDEX_NAME=clinical-notes

AZURE_AI_FOUNDRY_ENDPOINT=${FOUNDRY_ENDPOINT}
AZURE_AI_FOUNDRY_API_KEY=${FOUNDRY_KEY}
AZURE_EMBEDDING_DEPLOYMENT=text-embedding-3-small
AZURE_CHAT_DEPLOYMENT=claude-sonnet-5
EOF

echo
echo "Next: run sql/schema.sql against the new database, then sql/create_readonly_role.sql."
echo "Note: SQL_ADMIN_PASSWORD above is the DB admin login, not app-facing — set up the"
echo "read-only login (sql/create_readonly_role.sql) for AZURE_SQL_USERNAME/PASSWORD instead."
