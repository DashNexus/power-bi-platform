#!/usr/bin/env bash
#
# Bring the whole local stack up with one command.
#
#   ./scripts/dev.sh
#
# Idempotent: every step checks before it acts, so re-running after a crash or a
# Ctrl+C picks up where it left off rather than starting over. Ctrl+C stops both
# servers and leaves the database running — `--fresh` is how you throw it away.
#
# Works in Git Bash on Windows as well as natively on Linux and macOS. From
# PowerShell, use scripts\dev.ps1, which just calls this.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_PORT=8000
APP_PORT=3000

RUN_API=true
RUN_APP=true
FRESH=false
SKIP_INSTALL=false
FORCE=false
CHECK_ONLY=false

# ── Output ───────────────────────────────────────────────────────────────────

if [[ -t 1 ]]; then
  BOLD=$'\033[1m'
  DIM=$'\033[2m'
  RED=$'\033[31m'
  GREEN=$'\033[32m'
  YELLOW=$'\033[33m'
  BLUE=$'\033[34m'
  RESET=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; RESET=""
fi

step() { printf '\n%s==>%s %s%s%s\n' "$BLUE" "$RESET" "$BOLD" "$1" "$RESET"; }
ok()   { printf '    %s[ok]%s %s\n' "$GREEN" "$RESET" "$1"; }
info() { printf '    %s%s%s\n' "$DIM" "$1" "$RESET"; }
warn() { printf '    %s[!]%s %s\n' "$YELLOW" "$RESET" "$1"; }
die()  { printf '\n%serror:%s %s\n' "$RED" "$RESET" "$1" >&2; exit 1; }

usage() {
  cat <<'USAGE'
Usage: ./scripts/dev.sh [options]

Starts Azure SQL Edge, applies migrations, and runs the API and the frontend.

  --api-only        Run only the API (still starts the database)
  --app-only        Run only the frontend (assumes an API is already up)
  --fresh           Destroy the database volume and re-seed from scratch
  --skip-install    Skip the dependency check (faster when nothing changed)
  --force           Kill whatever is already listening on ports 8000 / 3000
  --check           Run the preflight checks and exit, changing nothing
  -h, --help        Show this message

First run creates .env with freshly generated secrets. It is never overwritten.

  App      http://localhost:3000   (admin@example.com / admin123)
  Swagger  http://localhost:8000/docs
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-only)     RUN_APP=false; shift ;;
    --app-only)     RUN_API=false; shift ;;
    --fresh)        FRESH=true; shift ;;
    --skip-install) SKIP_INSTALL=true; shift ;;
    --force)        FORCE=true; shift ;;
    --check)        CHECK_ONLY=true; shift ;;
    -h|--help)      usage; exit 0 ;;
    *) printf '%sunknown option:%s %s\n\n' "$RED" "$RESET" "$1" >&2; usage; exit 1 ;;
  esac
done

case "${OSTYPE:-}" in
  msys*|cygwin*|win32) IS_WINDOWS=true ;;
  *)                   IS_WINDOWS=false ;;
esac

# ── Config and connectivity helpers ──────────────────────────────────────────

env_value() {
  # Read a key from .env, falling back to $2. The last occurrence wins, matching
  # how pydantic-settings reads the same file.
  local key="$1" fallback="${2:-}" value
  value="$(grep -E "^${key}=" .env 2>/dev/null | tail -1 | cut -d= -f2-)"
  printf '%s' "${value:-$fallback}"
}

server_reachable() {
  # True when a SQL Server answers at host:port and accepts these credentials.
  # A login failure counts as unreachable: the right server with the wrong
  # password is no more usable than no server at all.
  local host="$1" port="$2" user="$3" password="$4"
  DB_HOST="$host" DB_PORT="$port" DB_USER="$user" DB_PASSWORD="$password"     python - <<'PYPROBE' >/dev/null 2>&1
import os
import sys

try:
    import pyodbc
except ImportError:
    sys.exit(1)

dsn = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={os.environ['DB_HOST']},{os.environ['DB_PORT']};"
    f"UID={os.environ['DB_USER']};PWD={os.environ['DB_PASSWORD']};"
    "TrustServerCertificate=yes;Encrypt=yes"
)
try:
    pyodbc.connect(dsn, timeout=5).close()
except Exception:
    sys.exit(1)
PYPROBE
}

# ── Ports ────────────────────────────────────────────────────────────────────

port_pid() {
  # Print the PID listening on $1, or nothing. Windows PIDs come from netstat
  # because lsof is absent under Git Bash, and they are *native* PIDs — usable
  # by taskkill but not by bash's kill.
  local port="$1"
  if [[ "$IS_WINDOWS" == true ]]; then
    netstat -ano 2>/dev/null |
      awk -v suffix=":$port" '
        $1 == "TCP" && $4 == "LISTENING" {
          n = length($2) - length(suffix)
          if (n > 0 && substr($2, n + 1) == suffix) { print $5; exit }
        }'
  elif command -v lsof >/dev/null 2>&1; then
    lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null | head -1
  else
    ss -lptnH "sport = :$port" 2>/dev/null | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2
  fi
}

free_port() {
  local port="$1" pid
  pid="$(port_pid "$port")"
  [[ -z "$pid" ]] && return 0
  if [[ "$IS_WINDOWS" == true ]]; then
    # //F //T is a tree kill: uvicorn --reload runs a worker child that holds
    # the socket, so killing only the parent leaves the port bound.
    taskkill //F //T //PID "$pid" >/dev/null 2>&1 || true
  else
    kill -9 "$pid" 2>/dev/null || true
  fi
  # Give the socket time to close before anything tries to rebind it.
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    [[ -z "$(port_pid "$port")" ]] && return 0
    sleep 0.3
  done
  return 0
}

require_free_port() {
  local port="$1" label="$2" pid
  pid="$(port_pid "$port")"
  [[ -z "$pid" ]] && return 0
  if [[ "$FORCE" == true ]]; then
    warn "port $port was busy (pid $pid) — freeing it"
    free_port "$port"
    [[ -n "$(port_pid "$port")" ]] && die "could not free port $port (pid $pid)"
    return 0
  fi
  die "port $port is already in use by pid $pid — that is where $label would run.
       Stop it, or re-run with --force to kill it."
}

# ── Preflight ────────────────────────────────────────────────────────────────

step "Checking prerequisites"

command -v python >/dev/null 2>&1 || die "python is not on PATH (3.12+ required)"
PY_VERSION="$(python -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [[ "$(printf '%s\n3.12\n' "$PY_VERSION" | sort -V | head -1)" != "3.12" ]]; then
  die "Python $PY_VERSION found, 3.12+ required"
fi
ok "python $PY_VERSION"

command -v node >/dev/null 2>&1 || die "node is not on PATH (22+ required)"
ok "node $(node --version)"

# Docker is optional: it is only needed when APP_DATABASE_URL names no server
# that is already running. Reporting it here is informational — the database
# step decides whether its absence actually matters.
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  ok "docker daemon responding"
else
  info "docker unavailable — fine unless the database URL needs the fallback container"
fi

# The ODBC driver is resolved by name at connect time, so a missing one surfaces
# as a confusing runtime error rather than an import failure. Check it early.
if python -c 'import pyodbc' >/dev/null 2>&1; then
  if python -c 'import pyodbc, sys; sys.exit(0 if any("ODBC Driver 18" in d for d in pyodbc.drivers()) else 1)' 2>/dev/null; then
    ok "ODBC Driver 18 for SQL Server"
  else
    die "ODBC Driver 18 for SQL Server is not installed.
       https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server"
  fi
else
  info "pyodbc not installed yet — checked again after dependencies install"
fi

if [[ "$CHECK_ONLY" == true ]]; then
  printf '\n%sPreflight passed.%s\n' "$GREEN" "$RESET"
  exit 0
fi

[[ "$RUN_API" == true ]] && require_free_port "$API_PORT" "the API"
[[ "$RUN_APP" == true ]] && require_free_port "$APP_PORT" "the frontend"

# ── Environment ──────────────────────────────────────────────────────────────

step "Environment"

if [[ -f .env ]]; then
  ok ".env already exists (left untouched)"
else
  cp .env.example .env
  # Appended rather than substituted in place: pydantic-settings takes the last
  # occurrence of a key, so this wins over the blank placeholder in the template
  # without needing a sed expression that matches its exact text.
  {
    echo ""
    echo "# ── Generated by scripts/dev.sh on first run ─────────────────────────────"
    echo "NEXTAUTH_SECRET=$(python -c 'import base64, os; print(base64.b64encode(os.urandom(32)).decode())')"
    echo "TOTP_ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>/dev/null || python -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
  } >> .env
  ok "created .env with generated secrets"
fi

# The frontend reads application/.env.local, not the root .env.
API_SECRET="$(grep -E '^NEXTAUTH_SECRET=' .env | tail -1 | cut -d= -f2-)"
[[ -n "$API_SECRET" ]] || die "NEXTAUTH_SECRET is empty in .env — delete the file and re-run to regenerate it"

write_app_env() {
  {
    echo "# Generated by scripts/dev.sh. NEXTAUTH_SECRET must match the root .env —"
    echo "# the API verifies the JWT that Auth.js signs here, so a mismatch reads as"
    echo "# 'login works, then every API call 401s'."
    echo "NEXTAUTH_URL=http://localhost:${APP_PORT}"
    echo "NEXTAUTH_SECRET=${API_SECRET}"
    echo "NEXT_PUBLIC_API_URL=http://localhost:${API_PORT}"
  } > application/.env.local
}

if [[ ! -f application/.env.local ]]; then
  write_app_env
  ok "created application/.env.local"
else
  # Existing files are normally left alone, but these two are a *pair*: the API
  # verifies the JWT Auth.js signs, so a drifted secret authenticates a login and
  # then 401s every call after it — a failure that looks like anything but a
  # config mismatch. Repairing beats preserving here.
  APP_SECRET="$(grep -E '^NEXTAUTH_SECRET=' application/.env.local | tail -1 | cut -d= -f2-)"
  if [[ "$APP_SECRET" == "$API_SECRET" ]]; then
    ok "application/.env.local already exists"
  else
    cp application/.env.local "application/.env.local.bak"
    write_app_env
    warn "application/.env.local had a different NEXTAUTH_SECRET than .env — rewrote it
        to match (the old file is at application/.env.local.bak). A mismatch signs
        users in and then 401s every request."
  fi
fi

# ── Dependencies ─────────────────────────────────────────────────────────────

if [[ "$SKIP_INSTALL" == true ]]; then
  step "Dependencies (skipped)"
else
  step "Dependencies"

  if python -c 'import aioodbc, fastapi, alembic' >/dev/null 2>&1; then
    ok "API dependencies present"
  else
    info "installing API dependencies (a minute or two the first time)"
    ( cd api && pip install -e ".[dev]" --quiet ) || die "pip install failed"
    python -c 'import pyodbc, sys; sys.exit(0 if any("ODBC Driver 18" in d for d in pyodbc.drivers()) else 1)' 2>/dev/null \
      || die "ODBC Driver 18 for SQL Server is not installed.
       https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server"
    ok "API dependencies installed"
  fi

  if [[ -d application/node_modules ]]; then
    ok "frontend dependencies present"
  else
    info "installing frontend dependencies"
    ( cd application && npm install --no-audit --no-fund --silent ) || die "npm install failed"
    ok "frontend dependencies installed"
  fi
fi

# ── Database ─────────────────────────────────────────────────────────────────

step "Database"

# Whatever server APP_DATABASE_URL names is the one used. If it is already
# reachable — the common case on a machine with SQL Server installed — Docker is
# never involved. The throwaway container is the fallback, not the default, so
# pointing the URL at an existing server is all it takes to switch.
DB_URL="$(grep -E '^APP_DATABASE_URL=' .env | tail -1 | cut -d= -f2-)"
[[ -n "$DB_URL" ]] || die "APP_DATABASE_URL is not set in .env"

DB_USER="$(env_value MSSQL_USER biplatformadmin)"
DB_PASSWORD="$(env_value MSSQL_PASSWORD biplatformadmin)"
DB_NAME="$(env_value MSSQL_DATABASE bi_platform_database)"
CONTAINER_PORT="$(env_value MSSQL_HOST_PORT 15433)"
SA_PASSWORD="$(env_value MSSQL_SA_PASSWORD 'LocalDev_Passw0rd!')"

# Parsed from the URL rather than assumed, so the two can never disagree.
DB_HOST="$(printf '%s' "$DB_URL" | sed -nE 's#.*@([^:/]+):[0-9]+/.*#\1#p')"
DB_PORT="$(printf '%s' "$DB_URL" | sed -nE 's#.*@[^:/]+:([0-9]+)/.*#\1#p')"
URL_DB="$(printf '%s' "$DB_URL" | sed -nE 's#.*@[^:/]+:[0-9]+/([^?]+).*#\1#p')"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-1433}"
DB_NAME="${URL_DB:-$DB_NAME}"

if [[ "$DB_URL" != mssql* ]]; then
  # PostgreSQL is supported by the app, but this script only knows how to stand
  # up SQL Server. Assume the server is already running and let alembic report
  # anything that is wrong with it.
  info "non-SQL-Server URL detected — assuming the database is already running"
  USING_CONTAINER=false
else
  if server_reachable "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_PASSWORD"; then
    ok "using the SQL Server already running at $DB_HOST:$DB_PORT (login $DB_USER)"
    USING_CONTAINER=false
  elif [[ "$DB_HOST" == "localhost" || "$DB_HOST" == "127.0.0.1" ]] \
       && [[ "$DB_PORT" == "$CONTAINER_PORT" ]]; then
    USING_CONTAINER=true
  else
    die "cannot reach $DB_HOST:$DB_PORT as $DB_USER, and that is not the
       container's port ($CONTAINER_PORT), so there is nothing to start.
       Check the server is running and the credentials in APP_DATABASE_URL are
       right, or point the URL at localhost:$CONTAINER_PORT to use the container."
  fi
fi

if [[ "$USING_CONTAINER" == true ]]; then
  command -v docker >/dev/null 2>&1 \
    || die "$DB_HOST:$DB_PORT is unreachable and docker is not installed, so the
       fallback container cannot be started either."
  docker info >/dev/null 2>&1 \
    || die "$DB_HOST:$DB_PORT is unreachable and the Docker daemon is not
       responding, so the fallback container cannot be started. Start Docker
       Desktop, or point APP_DATABASE_URL at a server that is already running."

  if [[ "$FRESH" == true ]]; then
    warn "--fresh: destroying the database volume"
    docker compose --profile full --profile cache down -v >/dev/null 2>&1 || true
  fi

  # --wait blocks on the compose health check — a real sa login, not a port
  # probe, because SQL Server accepts connections well before sa works.
  info "starting Azure SQL Edge (first run pulls the image — a few minutes)"
  docker compose up -d --wait mssql \
    || die "could not start the mssql container — see: docker compose logs mssql"
  ok "Azure SQL Edge healthy"

  # Give the container the same login the URL uses, so switching between it and
  # a real server needs no credential change.
  if ! MSSQL_SA_PASSWORD="$SA_PASSWORD" DB_PORT="$DB_PORT" DB_USER="$DB_USER" \
       DB_PASSWORD="$DB_PASSWORD" python - <<'PYLOGIN'
import os
import sys

import pyodbc

dsn = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER=localhost,{os.environ['DB_PORT']};UID=sa;PWD={os.environ['MSSQL_SA_PASSWORD']};"
    "TrustServerCertificate=yes;Encrypt=yes"
)
user = os.environ["DB_USER"]
password = os.environ["DB_PASSWORD"].replace("'", "''")
try:
    conn = pyodbc.connect(dsn, timeout=15, autocommit=True)
except pyodbc.Error as exc:
    print(f"could not connect as sa — {exc}", file=sys.stderr)
    sys.exit(1)

with conn:
    cur = conn.cursor()
    # CHECK_POLICY=OFF because the dev password is deliberately memorable and
    # the Linux image enforces the Windows complexity rules otherwise.
    cur.execute(
        f"IF SUSER_ID('{user}') IS NULL "
        f"CREATE LOGIN [{user}] WITH PASSWORD = '{password}', CHECK_POLICY = OFF;"
    )
    cur.execute(f"ALTER SERVER ROLE [sysadmin] ADD MEMBER [{user}];")
PYLOGIN
  then
    die "could not create the $DB_USER login in the container — see: docker compose logs mssql"
  fi
  ok "login $DB_USER present on the container"
fi

# The database itself, on whichever server won above. Creating it needs a
# connection to master, so this is separate from the URL's own database.
if [[ "$DB_URL" == mssql* ]]; then
  if ! DB_HOST="$DB_HOST" DB_PORT="$DB_PORT" DB_USER="$DB_USER" \
       DB_PASSWORD="$DB_PASSWORD" DB_NAME="$DB_NAME" python - <<'PYCREATE' >/dev/null
import os
import sys

import pyodbc

name = os.environ["DB_NAME"]
if not name.replace("_", "").isalnum():
    # The name is interpolated into DDL; a parameter cannot stand in for an
    # identifier, so anything unusual is refused rather than escaped.
    print(f"refusing to create a database with the name {name!r}", file=sys.stderr)
    sys.exit(2)

dsn = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={os.environ['DB_HOST']},{os.environ['DB_PORT']};"
    f"UID={os.environ['DB_USER']};PWD={os.environ['DB_PASSWORD']};"
    "TrustServerCertificate=yes;Encrypt=yes"
)
try:
    # autocommit: CREATE DATABASE cannot run inside a transaction.
    conn = pyodbc.connect(dsn, timeout=20, autocommit=True)
except pyodbc.Error as exc:
    print(f"could not connect — {exc}", file=sys.stderr)
    sys.exit(1)

with conn:
    cur = conn.cursor()
    existed = cur.execute("SELECT DB_ID(?)", name).fetchone()[0] is not None
    if not existed:
        cur.execute(f"CREATE DATABASE [{name}];")
    print("already existed" if existed else "created")
PYCREATE
  then
    die "could not create or reach the database '$DB_NAME' on $DB_HOST:$DB_PORT."
  fi
  ok "database $DB_NAME ready on $DB_HOST:$DB_PORT"
fi

info "applying migrations"
( cd api && alembic upgrade head ) || die "alembic upgrade failed"
ok "schema up to date"

# ── Servers ──────────────────────────────────────────────────────────────────

PIDS=()
SHUTTING_DOWN=false

shutdown_servers() {
  [[ "$SHUTTING_DOWN" == true ]] && return
  SHUTTING_DOWN=true
  printf '\n%s==>%s %sStopping%s\n' "$BLUE" "$RESET" "$BOLD" "$RESET"
  local pid
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do
    kill "$pid" 2>/dev/null || true
  done
  # Killing a bash job does not reliably take the native process with it under
  # MSYS, and uvicorn --reload owns a worker child. Sweeping the ports is what
  # makes an immediate re-run work instead of failing on a bound socket.
  [[ "$RUN_API" == true ]] && free_port "$API_PORT"
  [[ "$RUN_APP" == true ]] && free_port "$APP_PORT"
  ok "servers stopped — the database is still up ('docker compose stop' to stop it)"
  exit 0
}
trap shutdown_servers INT TERM

# -u flushes each line as it is produced; without it the prefixed output arrives
# in 4KB blocks and the logs look frozen for minutes at a time.
SED_CMD=(sed)
if printf '' | sed -u '' >/dev/null 2>&1; then
  SED_CMD=(sed -u)
fi

start_server() {
  local label="$1" colour="$2" dir="$3"
  shift 3
  ( cd "$dir" && "$@" 2>&1 | "${SED_CMD[@]}" "s/^/${colour}[${label}]${RESET} /" ) &
  PIDS+=("$!")
}

step "Starting"

if [[ "$RUN_API" == true ]]; then
  start_server api "$GREEN" api uvicorn app.main:app --reload --port "$API_PORT"
  ok "API      http://localhost:${API_PORT}/docs"
fi

if [[ "$RUN_APP" == true ]]; then
  start_server app "$BLUE" application npm run dev
  ok "App      http://localhost:${APP_PORT}"
fi

printf '\n    %sSign in as admin@example.com / admin123 — change it after first login.%s\n' "$DIM" "$RESET"
printf '    %sCtrl+C stops both servers.%s\n\n' "$DIM" "$RESET"

wait
