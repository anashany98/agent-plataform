#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

CLIENT_ID="${1:-}"
DOMAIN="${2:-}"
PROXY_PORT="${3:-9000}"

if [[ -z "$CLIENT_ID" || ! "$CLIENT_ID" =~ ^[a-z0-9][a-z0-9-]{1,48}$ ]]; then
  echo "Uso: $0 <client-id> [dominio] [puerto-proxy]" >&2
  echo "client-id solo puede contener minúsculas, números y guiones." >&2
  exit 2
fi
DOMAIN="${DOMAIN:-${CLIENT_ID}.local}"
PROJECT="agent-${CLIENT_ID}"
ENV_FILE=".env.${CLIENT_ID}"

command -v docker >/dev/null || { echo "Docker no está instalado." >&2; exit 1; }
docker compose version >/dev/null || { echo "Docker Compose v2 no está disponible." >&2; exit 1; }

# Devuelve 0 si el puerto TCP local está ocupado.
port_in_use() {
  local port="$1"
  if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
    exec 3>&- 3<&- || true
    return 0
  fi
  return 1
}

# Preflight atómico (D-009): valida ANTES de escribir .env / build / up para no
# alterar instalaciones existentes ni dejar artefactos parciales si falla.
docker info >/dev/null 2>&1 || { echo "El daemon de Docker no está accesible." >&2; exit 1; }
if [[ ! "$PROXY_PORT" =~ ^[0-9]+$ ]] || (( PROXY_PORT < 1 || PROXY_PORT > 65535 )); then
  echo "Puerto proxy inválido: ${PROXY_PORT}." >&2; exit 1
fi
if port_in_use "$PROXY_PORT"; then
  echo "El puerto ${PROXY_PORT} ya está en uso por otro proceso/proyecto." >&2
  echo "Elige otro puerto (3er argumento) para conservar la asignación por cliente." >&2
  exit 1
fi

secret_hex() { openssl rand -hex "${1:-32}"; }
secret_b64() { openssl rand -base64 "${1:-36}" | tr -d '\n'; }
command -v openssl >/dev/null || { echo "OpenSSL es obligatorio para generar secretos." >&2; exit 1; }

if [[ -e "$ENV_FILE" ]]; then
  echo "Ya existe $ENV_FILE. No se sobrescribe para evitar perder secretos." >&2
  exit 1
fi

cat > "$ENV_FILE" <<EOF
COMPOSE_PROJECT_NAME=${PROJECT}
ENVIRONMENT=staging
INSTALLATION_ID=${CLIENT_ID}
PILOT_MODE=true
AUTO_SEED_DEMO_DATA=false
PROXY_PORT=${PROXY_PORT}
PORTAL_HOST=${DOMAIN}
API_HOST=api.${DOMAIN}
CHATWOOT_HOST=chat.${DOMAIN}
FLOWWINK_HOST=agents.${DOMAIN}
ACTIVEPIECES_HOST=automation.${DOMAIN}
ALLOWED_ORIGINS=https://${DOMAIN},https://chat.${DOMAIN},http://${DOMAIN},http://localhost:${PROXY_PORT}
ALLOWED_HOSTS=${DOMAIN},api.${DOMAIN},localhost,127.0.0.1,bridge-api
POSTGRES_DB=bridge_db
POSTGRES_USER=bridge_user
POSTGRES_PASSWORD=$(secret_b64 36)
REDIS_PASSWORD=$(secret_b64 36)
AUTH_SECRET=$(secret_b64 48)
AUTH_TOKEN_TTL_SEC=3600
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=$(secret_b64 24)Aa1!
CHATWOOT_WEBHOOK_SECRET=$(secret_b64 48)
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS_PER_MINUTE=120
LOGIN_RATE_LIMIT_REQUESTS=8
LOGIN_RATE_LIMIT_WINDOW_SEC=900
CHATWOOT_SECRET_KEY_BASE=$(secret_hex 64)
CHATWOOT_POSTGRES_DB=chatwoot_db
CHATWOOT_POSTGRES_USER=chatwoot
CHATWOOT_POSTGRES_PASSWORD=$(secret_b64 36)
CHATWOOT_REDIS_PASSWORD=$(secret_b64 36)
CHATWOOT_API_TOKEN=
CHATWOOT_ACCOUNT_ID=
BRIDGE_WEBHOOK_URL=
CHATWOOT_PUBLIC_URL=https://chat.${DOMAIN}
ACTIVEPIECES_POSTGRES_DB=activepieces
ACTIVEPIECES_POSTGRES_USER=activepieces
ACTIVEPIECES_POSTGRES_PASSWORD=$(secret_b64 36)
ACTIVEPIECES_REDIS_PASSWORD=$(secret_b64 36)
ACTIVEPIECES_ENCRYPTION_KEY=$(secret_hex 16)
ACTIVEPIECES_JWT_SECRET=$(secret_b64 48)
ACTIVEPIECES_API_KEY=
ACTIVEPIECES_PUBLIC_URL=https://automation.${DOMAIN}
PRESTASHOP_BASE_URL=
PRESTASHOP_API_KEY=
PRESTASHOP_SHOP_ID=
GHL_BASE_URL=https://services.leadconnectorhq.com
GHL_API_TOKEN=
GHL_LOCATION_ID=
GHL_PIPELINE_ID=
GHL_PIPELINE_STAGE_ID=
ALLOW_MOCK_LLM=false
ALLOW_INTEGRATION_STUBS=false
OLLAMA_BASE_URL=http://host.docker.internal:11434
CHEAP_LLM_PROVIDER=ollama
CHEAP_LLM_MODEL=qwen2.5:3b
STANDARD_LLM_PROVIDER=ollama
STANDARD_LLM_MODEL=qwen2.5:7b
ADVANCED_LLM_PROVIDER=openai
ADVANCED_LLM_MODEL=
CRITICAL_LLM_PROVIDER=anthropic
CRITICAL_LLM_MODEL=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=
ANTHROPIC_BASE_URL=https://api.anthropic.com/v1
ANTHROPIC_API_KEY=
LLM_MAX_DAILY_COST_USD=25
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSION=768
EMBEDDING_BASE_URL=http://host.docker.internal:11434
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
FLOWWINK_SUPABASE_URL=
FLOWWINK_SUPABASE_ANON_KEY=
FLOWWINK_SUPABASE_PROJECT_ID=
EOF
chmod 600 "$ENV_FILE"

compose=(docker compose --env-file "$ENV_FILE" -p "$PROJECT" --profile full)
"${compose[@]}" config >/dev/null
"${compose[@]}" build --pull
"${compose[@]}" up -d

services=(reverse-proxy portal bridge-api bridge-db bridge-redis flowwink-app chatwoot-web chatwoot-worker chatwoot-db chatwoot-redis activepieces-app activepieces-worker activepieces-db activepieces-redis)
deadline=$((SECONDS + 600))
while (( SECONDS < deadline )); do
  all_ready=1
  for service in "${services[@]}"; do
    cid="$("${compose[@]}" ps -q "$service")"
    [[ -n "$cid" ]] || { all_ready=0; continue; }
    state="$(docker inspect -f '{{.State.Status}}' "$cid")"
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
    if [[ "$state" != "running" || ( "$health" != "healthy" && "$health" != "none" ) ]]; then
      all_ready=0
    fi
  done
  (( all_ready == 1 )) && break
  sleep 5
done

"${compose[@]}" ps
if (( SECONDS >= deadline )); then
  echo "El stack no alcanzó estado saludable. Revisa: ${compose[*]} logs" >&2
  exit 1
fi

admin_password="$(grep '^INITIAL_ADMIN_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"
cat > "provision-${CLIENT_ID}.txt" <<EOF
Instalación: ${CLIENT_ID}
Proyecto Compose: ${PROJECT}
Portal/Proxy: http://localhost:${PROXY_PORT}
Usuario inicial: admin
Contraseña inicial: ${admin_password}
Cambiar la contraseña en el primer acceso.
Archivo de entorno: ${ENV_FILE} (proteger y no enviar por correo sin cifrar)
EOF
chmod 600 "provision-${CLIENT_ID}.txt"
echo "Instalación creada. Credenciales iniciales guardadas en provision-${CLIENT_ID}.txt con permisos restringidos."
