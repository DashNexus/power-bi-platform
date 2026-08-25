#!/usr/bin/env bash
#
# Run `alembic upgrade head` against a deployed environment.
#
# Executes inside the already-deployed API container rather than from a laptop:
# the container has the ODBC driver, the connection string, and — importantly —
# an egress IP the SQL firewall already allows. Running it locally means opening
# the firewall to a developer address, which then has to be closed again.
#
#   ./deploy/scripts/migrate.sh -g my-rg -e dev
set -euo pipefail

RESOURCE_GROUP=""
ENVIRONMENT="dev"
COMMAND="upgrade head"

usage() {
  cat <<'EOF'
Usage: migrate.sh -g <resource-group> [options]

  -g, --resource-group   Azure resource group (required)
  -e, --environment      Environment suffix (default: dev)
  -c, --command          Alembic command (default: "upgrade head")
  -h, --help             Show this message

Examples:
  migrate.sh -g my-rg -e prod
  migrate.sh -g my-rg -c "current"      # what revision is deployed?
  migrate.sh -g my-rg -c "downgrade -1" # step back one revision
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -g|--resource-group) RESOURCE_GROUP="$2"; shift 2 ;;
    -e|--environment)    ENVIRONMENT="$2"; shift 2 ;;
    -c|--command)        COMMAND="$2"; shift 2 ;;
    -h|--help)           usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

[[ -n "$RESOURCE_GROUP" ]] || { echo "Error: --resource-group is required." >&2; usage; exit 1; }

APP_NAME="pbip-${ENVIRONMENT}-api"

echo "==> alembic ${COMMAND} in ${APP_NAME}"
az containerapp exec \
  --resource-group "$RESOURCE_GROUP" \
  --name "$APP_NAME" \
  --command "alembic ${COMMAND}"
