#!/usr/bin/env bash
#
# Build, push, provision, and migrate — the whole first deploy in one command.
#
#   ./deploy/scripts/deploy.sh -g my-rg -r myregistry -e dev
#
# Re-running is safe: the Bicep deployment is incremental and the migration is
# idempotent. What it does NOT do is roll back — if the migration fails after
# the images are live, the previous revision is still serving and you fix
# forward.
set -euo pipefail

RESOURCE_GROUP=""
REGISTRY=""
ENVIRONMENT="dev"
LOCATION="eastus"
TAG="$(git rev-parse --short HEAD 2>/dev/null || echo latest)"
SKIP_BUILD=false
SKIP_MIGRATE=false

usage() {
  cat <<'EOF'
Usage: deploy.sh -g <resource-group> -r <acr-name> [options]

  -g, --resource-group   Azure resource group (required)
  -r, --registry         Azure Container Registry name, without .azurecr.io (required)
  -e, --environment      Environment suffix for resource names (default: dev)
  -l, --location         Azure region (default: eastus)
  -t, --tag              Image tag (default: current git short SHA)
      --skip-build       Reuse images already in the registry
      --skip-migrate     Provision without running database migrations
  -h, --help             Show this message

Secrets are read from the parameters file for the environment
(deploy/azure/parameters.<env>.json). Replace the REPLACE_ME placeholders, or
override them with `az deployment group create -p key=value`.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -g|--resource-group) RESOURCE_GROUP="$2"; shift 2 ;;
    -r|--registry)       REGISTRY="$2"; shift 2 ;;
    -e|--environment)    ENVIRONMENT="$2"; shift 2 ;;
    -l|--location)       LOCATION="$2"; shift 2 ;;
    -t|--tag)            TAG="$2"; shift 2 ;;
    --skip-build)        SKIP_BUILD=true; shift ;;
    --skip-migrate)      SKIP_MIGRATE=true; shift ;;
    -h|--help)           usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$RESOURCE_GROUP" || -z "$REGISTRY" ]]; then
  echo "Error: --resource-group and --registry are required." >&2
  usage
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PARAMS="$ROOT/deploy/azure/parameters.${ENVIRONMENT}.json"
LOGIN_SERVER="${REGISTRY}.azurecr.io"
API_IMAGE="${LOGIN_SERVER}/power-bi-platform-api:${TAG}"
APP_IMAGE="${LOGIN_SERVER}/power-bi-platform-app:${TAG}"

[[ -f "$PARAMS" ]] || { echo "Error: no parameters file at $PARAMS" >&2; exit 1; }

if grep -q REPLACE_ME "$PARAMS"; then
  echo "Error: $PARAMS still contains REPLACE_ME placeholders." >&2
  exit 1
fi

echo "==> Resource group"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none

# The frontend's API URL is inlined into the browser bundle at build time, so it
# has to be known before the image is built — which means resolving it from a
# prior deployment, or predicting it. Provision first, then build, then update.
echo "==> Provisioning infrastructure"
az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "$ROOT/deploy/azure/main.bicep" \
  --parameters "@$PARAMS" \
  --parameters \
      environmentName="$ENVIRONMENT" \
      location="$LOCATION" \
      containerRegistry="$LOGIN_SERVER" \
      apiImage="$API_IMAGE" \
      applicationImage="$APP_IMAGE" \
  --output none

API_URL="$(az deployment group show -g "$RESOURCE_GROUP" \
  -n main --query properties.outputs.apiUrl.value -o tsv)"
APP_URL="$(az deployment group show -g "$RESOURCE_GROUP" \
  -n main --query properties.outputs.applicationUrl.value -o tsv)"

if [[ "$SKIP_BUILD" == false ]]; then
  echo "==> Building images in ACR (tag: $TAG)"
  az acr build --registry "$REGISTRY" \
    --image "power-bi-platform-api:${TAG}" \
    --file "$ROOT/api/Dockerfile" "$ROOT/api"

  # NEXT_PUBLIC_API_URL is a build arg, not a runtime variable: the value is
  # compiled into the client bundle, so the image is bound to this environment.
  az acr build --registry "$REGISTRY" \
    --image "power-bi-platform-app:${TAG}" \
    --build-arg "NEXT_PUBLIC_API_URL=${API_URL}" \
    --file "$ROOT/application/Dockerfile" "$ROOT/application"

  echo "==> Rolling out the new images"
  az containerapp update -g "$RESOURCE_GROUP" -n "pbip-${ENVIRONMENT}-api" \
    --image "$API_IMAGE" --output none
  az containerapp update -g "$RESOURCE_GROUP" -n "pbip-${ENVIRONMENT}-app" \
    --image "$APP_IMAGE" --output none
fi

if [[ "$SKIP_MIGRATE" == false ]]; then
  echo "==> Running database migrations"
  "$ROOT/deploy/scripts/migrate.sh" -g "$RESOURCE_GROUP" -e "$ENVIRONMENT"
fi

cat <<EOF

Deployed.
  API          $API_URL
  Application  $APP_URL

First sign-in is admin@example.com / admin123 — change it immediately.
EOF
