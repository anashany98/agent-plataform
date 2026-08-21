#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

CLIENT_ID="${1:-}"
DOMAIN="${2:-}"
PROXY_PORT="${3:-9000}"
PROFILE="${4:-core}"
TLS_CERTIFICATE="${5:-}"
TLS_PRIVATE_KEY="${6:-}"
ALLOW_SELF_SIGNED_TLS_BOOTSTRAP="${ALLOW_SELF_SIGNED_TLS_BOOTSTRAP:-false}"

if [[ ! "$CLIENT_ID" =~ ^[a-z0-9][a-z0-9-]{1,48}$ ]]; then
  echo "Uso: $0 <client-id> [dominio] [puerto] [core|full|production] [cert.pem] [key.pem]" >&2
  exit 2
fi
[[ "$PROFILE" =~ ^(core|full|production)$ ]] || { echo "Perfil inválido: $PROFILE" >&2; exit 2; }
[[ "$PROXY_PORT" =~ ^[0-9]+$ ]] && (( PROXY_PORT >= 1024 && PROXY_PORT <= 65535 )) || {
  echo "Puerto proxy inválido: $PROXY_PORT" >&2; exit 2;
}
DOMAIN="${DOMAIN:-${CLIENT_ID}.local}"
PROJECT="agent-${CLIENT_ID}"
ENV_FILE=".env.${CLIENT_ID}"
[[ ! -e "$ENV_FILE" ]] || { echo "$ENV_FILE ya existe; no se sobrescribe." >&2; exit 1; }
for command in docker git openssl python3; do
  command -v "$command" >/dev/null || { echo "$command no está instalado." >&2; exit 1; }
done
docker compose version >/dev/null
docker info >/dev/null 2>&1 || { echo "El daemon de Docker no está accesible." >&2; exit 1; }

if [[ "$PROFILE" == production ]]; then
  [[ "$DOMAIN" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ && "$DOMAIN" == *.* && ! "$DOMAIN" =~ \.(local|localhost|invalid)$ ]] || {
    echo "production exige un dominio DNS público válido." >&2; exit 1;
  }
  [[ -f "$TLS_CERTIFICATE" ]] || { echo "No existe el certificado TLS." >&2; exit 1; }
  [[ -f "$TLS_PRIVATE_KEY" ]] || { echo "No existe la clave TLS." >&2; exit 1; }
  TLS_CERTIFICATE="$(cd "$(dirname "$TLS_CERTIFICATE")" && pwd)/$(basename "$TLS_CERTIFICATE")"
  TLS_PRIVATE_KEY="$(cd "$(dirname "$TLS_PRIVATE_KEY")" && pwd)/$(basename "$TLS_PRIVATE_KEY")"
fi

port_in_use() {
  local port="$1"
  if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
    exec 3>&- 3<&- || true
    return 0
  fi
  return 1
}
port_in_use "$PROXY_PORT" && { echo "El puerto $PROXY_PORT ya está en uso." >&2; exit 1; }

secret_hex() { openssl rand -hex "${1:-32}"; }
admin_password="$(openssl rand -base64 24 | tr -d '\n')Aa1!"
environment=staging
allowed_origins="http://localhost:${PROXY_PORT}"
allowed_hosts="localhost,127.0.0.1,${DOMAIN},api.${DOMAIN},bridge-api"
public_scheme=http
public_suffix=":${PROXY_PORT}"
trusted_proxy_count=1
if [[ "$PROFILE" == production ]]; then
  environment=production
  allowed_origins="https://${DOMAIN}"
  allowed_hosts="${DOMAIN},api.${DOMAIN},bridge-api"
  public_scheme=https
  public_suffix=""
  trusted_proxy_count=2
fi
source_commit="$(git rev-parse HEAD)"
application_version="$(awk -F'"' '/^version[[:space:]]*=[[:space:]]*"[0-9]+\.[0-9]+\.[0-9]+"$/ { print $2; exit }' bridge-api/pyproject.toml)"
[[ "$application_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "No se pudo obtener la versión SemVer de bridge-api/pyproject.toml." >&2
  exit 1
}
release_version="${application_version}-${source_commit:0:12}"

temporary_env="$(mktemp ".${ENV_FILE}.XXXXXX.tmp")"
trap '[[ -n "${temporary_env:-}" && -f "$temporary_env" ]] && rm -f -- "$temporary_env"' EXIT
cat > "$temporary_env" <<EOF
COMPOSE_PROJECT_NAME=${PROJECT}
DEPLOY_PROFILE=${PROFILE}
RELEASE_VERSION=${release_version}
SOURCE_COMMIT=${source_commit}
BRIDGE_API_IMAGE=agent-platform-bridge-api:${release_version}
PORTAL_IMAGE=agent-platform-portal:${release_version}
RELEASE_MANIFEST_FILE=.env.${CLIENT_ID}.release.json
ENVIRONMENT=${environment}
INSTALLATION_ID=${CLIENT_ID}
PILOT_MODE=false
RUN_MIGRATIONS=true
ALLOW_DEMO_DATA=false
AUTO_SEED_DEMO_DATA=false
ALLOW_MOCK_LLM=false
ALLOW_INTEGRATION_STUBS=false
DEBUG=false
PROXY_BIND_ADDRESS=127.0.0.1
PROXY_PORT=${PROXY_PORT}
TLS_BIND_ADDRESS=0.0.0.0
HTTP_PORT=80
HTTPS_PORT=443
TLS_CERT_FILE=${TLS_CERTIFICATE}
TLS_PRIVATE_KEY_FILE=${TLS_PRIVATE_KEY}
ALLOW_SELF_SIGNED_TLS_BOOTSTRAP=${ALLOW_SELF_SIGNED_TLS_BOOTSTRAP}
PUBLIC_BASE_URL=${public_scheme}://${DOMAIN}${public_suffix}
PORTAL_HOST=${DOMAIN}
API_HOST=api.${DOMAIN}
ALLOWED_ORIGINS=${allowed_origins}
ALLOWED_HOSTS=${allowed_hosts}
POSTGRES_DB=bridge_db
POSTGRES_USER=bridge_user
POSTGRES_PASSWORD=$(secret_hex 32)
REDIS_PASSWORD=$(secret_hex 32)
AUTH_SECRET=$(secret_hex 48)
AUTH_TOKEN_TTL_SEC=3600
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=${admin_password}
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS_PER_MINUTE=120
LOGIN_RATE_LIMIT_REQUESTS=8
LOGIN_RATE_LIMIT_WINDOW_SEC=900
TRUSTED_PROXY_COUNT=${trusted_proxy_count}
TRUSTED_PROXY_CIDRS=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
REDIS_ENABLED=true
RATE_LIMIT_BACKEND=redis
REDIS_RATE_LIMIT_FAIL_OPEN=false
REDIS_SOCKET_TIMEOUT_SEC=0.5
REDIS_CONNECT_TIMEOUT_SEC=0.5
OUTBOX_WORKER_ENABLED=true
OUTBOX_WORKER_POLL_SEC=1.0
OUTBOX_WORKER_LEASE_SEC=60
OUTBOX_WORKER_DISPATCH_LOCK_SEC=30
OUTBOX_MAX_ATTEMPTS=8
OUTBOX_RETRY_BASE_DELAY_SEC=1.0
OUTBOX_RETRY_MAX_DELAY_SEC=300.0
OUTBOX_BATCH_SIZE=16
SCHEDULED_TASK_WORKER_ENABLED=true
SCHEDULED_TASK_WORKER_POLL_SEC=30.0
EMAIL_PROVIDER=local
CHATWOOT_ENABLED=false
CHATWOOT_WEBHOOK_SECRET=
CHATWOOT_SAFE_FETCH_ALLOW_PRIVATE_NETWORK=false
PRESTASHOP_BASE_URL=
PRESTASHOP_API_KEY=
PRESTASHOP_SHOP_ID=
PRESTASHOP_SHOP_GROUP_ID=
PRESTASHOP_COUNTRY_ID=
PRESTASHOP_CURRENCY_ID=
GHL_BASE_URL=https://services.leadconnectorhq.com
GHL_API_TOKEN=
GHL_LOCATION_ID=
GHL_PIPELINE_ID=
GHL_PIPELINE_STAGE_ID=
INTEGRATION_RETRY_ATTEMPTS=3
INTEGRATION_RETRY_BASE_DELAY_SEC=0.25
INTEGRATION_RETRY_MAX_DELAY_SEC=2.0
IDEMPOTENCY_LEASE_SEC=300
IDEMPOTENCY_MAX_ATTEMPTS=8
CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
CIRCUIT_BREAKER_RECOVERY_SEC=30
OLLAMA_BASE_URL=
CHEAP_LLM_PROVIDER=none
CHEAP_LLM_MODEL=
STANDARD_LLM_PROVIDER=none
STANDARD_LLM_MODEL=
ADVANCED_LLM_PROVIDER=none
ADVANCED_LLM_MODEL=
CRITICAL_LLM_PROVIDER=none
CRITICAL_LLM_MODEL=
OPENAI_BASE_URL=
OPENAI_API_KEY=
ANTHROPIC_BASE_URL=
ANTHROPIC_API_KEY=
LLM_PRICING_CATALOG_JSON=
LLM_MAX_DAILY_COST_USD=25
LLM_MAX_INPUT_BYTES=131072
LLM_MAX_OUTPUT_TOKENS=1024
EMBEDDING_PROVIDER=local_tfidf
EMBEDDING_MODEL=local-tfidf
EMBEDDING_DIMENSION=768
EMBEDDING_BASE_URL=
EMBEDDING_API_KEY=
RAG_MIN_SCORE=0.55
RAG_MAX_FILE_MB=25
OCR_ENABLED=true
COUNTRY=ES
CURRENCY=EUR
DEFAULT_VAT_RATE=0.21
INVOICE_SERIES=INV-2026-
SHIPPING_FLAT_RATE=15.00
FREE_SHIPPING_THRESHOLD=300.00
QUOTE_CONFIRMATION_TTL_SEC=1800
STOCK_RESERVATION_TTL_SEC=900
ENABLE_QUOTES=true
ENABLE_ORDERS=false
ENABLE_INVOICES=false
ENABLE_AUTOMATIC_ORDER_CONFIRMATION=false
ENABLE_AUTOMATIC_INVOICE_ISSUANCE=false
ENABLE_AUTOMATIC_PUBLISHING=false
NGINX_IMAGE=nginx:1.30.4-alpine3.24@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46
REDIS_IMAGE=redis:7.2.14-alpine3.21@sha256:dfa18828cbc07b3ae6a95ec7343f6c214fdee2d836197b4be8e9904420762cd8
BRIDGE_POSTGRES_IMAGE=pgvector/pgvector:pg15@sha256:a20a57d7aa5217a6af0a391ccf69f4a8512406d6c14be08132f801468cc3cc62
BACKUP_QUIESCE=true
BACKUP_HELPER_IMAGE=nginx:1.30.4-alpine3.24@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46
EOF

if [[ "$PROFILE" == full ]]; then
  cat >> "$temporary_env" <<EOF
CHATWOOT_HOST=chat.${DOMAIN}
FLOWWINK_HOST=agents.${DOMAIN}
ACTIVEPIECES_HOST=automation.${DOMAIN}
CHATWOOT_SECRET_KEY_BASE=$(secret_hex 64)
CHATWOOT_POSTGRES_DB=chatwoot_db
CHATWOOT_POSTGRES_USER=chatwoot
CHATWOOT_POSTGRES_PASSWORD=$(secret_hex 32)
CHATWOOT_REDIS_PASSWORD=$(secret_hex 32)
CHATWOOT_API_TOKEN=
CHATWOOT_ACCOUNT_ID=
CHATWOOT_HANDOFF_TEAM_ID=0
CHATWOOT_HANDOFF_ASSIGNEE_ID=0
CHATWOOT_WEBHOOK_SECRET=$(secret_hex 48)
BRIDGE_WEBHOOK_URL=${public_scheme}://api.${DOMAIN}${public_suffix}/webhooks/chatwoot
CHATWOOT_PUBLIC_URL=${public_scheme}://chat.${DOMAIN}${public_suffix}
ACTIVEPIECES_POSTGRES_DB=activepieces
ACTIVEPIECES_POSTGRES_USER=activepieces
ACTIVEPIECES_POSTGRES_PASSWORD=$(secret_hex 32)
ACTIVEPIECES_REDIS_PASSWORD=$(secret_hex 32)
ACTIVEPIECES_ENCRYPTION_KEY=$(secret_hex 16)
ACTIVEPIECES_JWT_SECRET=$(secret_hex 48)
ACTIVEPIECES_API_KEY=
ACTIVEPIECES_PUBLIC_URL=${public_scheme}://automation.${DOMAIN}${public_suffix}
FLOWWINK_SUPABASE_URL=
FLOWWINK_SUPABASE_ANON_KEY=
FLOWWINK_SUPABASE_PROJECT_ID=
CHATWOOT_POSTGRES_IMAGE=pgvector/pgvector:pg16@sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc
ACTIVEPIECES_POSTGRES_IMAGE=pgvector/pgvector:0.8.0-pg14@sha256:c55d7e7deac05dde62139e0ded4fcf4f58363656cbc382dbea82fbed995aa767
ACTIVEPIECES_IMAGE=ghcr.io/activepieces/activepieces:0.86.3@sha256:208517c4f0d798a477a0c594bf432dd0f4918433f4b6f5b5f188a6e10e638c6c
EOF
fi
chmod 600 "$temporary_env"
mv -- "$temporary_env" "$ENV_FILE"
temporary_env=""
trap - EXIT

./scripts/preflight-production.sh --env-file "$ENV_FILE" --profile "$PROFILE" --mode bootstrap --allow-dirty
if [[ "${NO_START:-false}" == true ]]; then
  echo "Configuración validada en $ENV_FILE; arranque omitido."
  exit 0
fi

compose=(docker compose --env-file "$ENV_FILE" -p "$PROJECT" -f docker-compose.yml)
if [[ "$PROFILE" == production ]]; then compose+=(-f infrastructure/compose/docker-compose.prod.example.yml); fi
compose+=(--profile "$PROFILE")
if [[ "$PROFILE" == production ]]; then
  "${compose[@]}" pull --policy always --ignore-buildable
fi
"${compose[@]}" build --pull
if [[ "$PROFILE" == production ]]; then
  python3 scripts/create-release-manifest.py --env-file "$ENV_FILE"
fi
"${compose[@]}" up -d --no-build --pull never --wait --wait-timeout 600
./scripts/check-health.sh "$CLIENT_ID" "$PROFILE"

receipt="provision-${CLIENT_ID}.txt"
cat > "$receipt" <<EOF
Instalación: ${CLIENT_ID}
Perfil: ${PROFILE}
Proyecto Compose: ${PROJECT}
Portal/Proxy: ${public_scheme}://${DOMAIN}${public_suffix}
Usuario inicial: admin
Contraseña inicial: ${admin_password}
Cambiar la contraseña en el primer acceso.
Archivo de entorno: ${ENV_FILE}
EOF
chmod 600 "$receipt"
echo "Instalación creada. Credenciales guardadas localmente en $receipt."
