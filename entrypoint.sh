#!/bin/bash
set -e

# Fetch secrets from Infisical at container startup.
# Never store secrets in .env files — Infisical is the source of truth.

# Use the external Infisical URL
INFISICAL_API_URL="${INFISICAL_HOST_URL:-https://localhost:8080}"

# Skip Infisical if no credentials provided
if [[ -z "${INFISICAL_CLIENT_ID:-}" || -z "${INFISICAL_CLIENT_SECRET:-}" ]]; then
  echo "[entrypoint] No Infisical credentials — skipping secret injection"
  exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-3088}"
fi

# Step 1: Get access token
RESPONSE=$(curl -s -X POST \
  "${INFISICAL_API_URL}/api/v1/auth/universal-auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"clientId\": \"$INFISICAL_CLIENT_ID\", \"clientSecret\": \"$INFISICAL_CLIENT_SECRET\"}")

TOKEN=$(echo "$RESPONSE" | grep -o '"accessToken":"[^"]*' | cut -d'"' -f4)

if [[ -z "$TOKEN" ]]; then
  echo "[entrypoint] WARNING: Failed to get access token — running without auth"
  exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-3088}"
fi

# Step 2: Fetch entire project secrets at once via /api/v3/secrets/raw
echo "[entrypoint] Fetching secrets from project $INFISICAL_PROJECT_ID..."
SECRETS_JSON=$(curl -s \
  "${INFISICAL_API_URL}/api/v3/secrets/raw?workspaceId=${INFISICAL_PROJECT_ID}&environment=dev" \
  -H "Authorization: Bearer $TOKEN")

# Export all secrets as env vars
export_vars=$(echo "$SECRETS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for sec in data.get('secrets', []):
    key = sec.get('secretKey', '')
    val = sec.get('secretValue', '')
    if key and val:
        print(f'{key}={val}')
")

if [[ -n "$export_vars" ]]; then
  echo "[entrypoint] Loaded secrets from Infisical project $INFISICAL_PROJECT_ID"
  while IFS= read -r line; do
    export "$line" 2>/dev/null || true
  done <<< "$export_vars"
  echo "[entrypoint] Starting bridge..."
  exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-3088}"
fi

echo "[entrypoint] No secrets loaded — running with env vars only"
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-3088}"
