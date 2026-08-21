#!/usr/bin/env bash
set -Eeuo pipefail

CLIENT_ID="${1:?Indica client-id}"
PROFILE="${2:-${DEPLOY_PROFILE:-production}}"
[[ "$CLIENT_ID" =~ ^[a-z0-9][a-z0-9-]{1,48}$ ]] || { echo "client-id inválido" >&2; exit 2; }
[[ "$PROFILE" =~ ^(core|full|production)$ ]] || { echo "perfil inválido: $PROFILE" >&2; exit 2; }
ENV_FILE=".env.${CLIENT_ID}"
PROJECT="agent-${CLIENT_ID}"
[[ -f "$ENV_FILE" ]] || { echo "No existe $ENV_FILE" >&2; exit 1; }

compose=(docker compose --env-file "$ENV_FILE" -p "$PROJECT" -f docker-compose.yml)
if [[ "$PROFILE" == production ]]; then
  compose+=(-f infrastructure/compose/docker-compose.prod.example.yml)
fi
compose+=(--profile "$PROFILE")

mapfile -t services < <("${compose[@]}" config --services)
(( ${#services[@]} > 0 )) || { echo "El perfil $PROFILE no contiene servicios." >&2; exit 1; }
failed=0
for service in "${services[@]}"; do
  cid="$("${compose[@]}" ps -q "$service")"
  if [[ -z "$cid" ]]; then printf '%-26s %s\n' "$service" "AUSENTE"; failed=1; continue; fi
  state="$(docker inspect -f '{{.State.Status}}' "$cid")"
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
  printf '%-26s estado=%-10s salud=%s\n' "$service" "$state" "$health"
  [[ "$state" == running && "$health" == healthy ]] || failed=1

  # Sólo el edge previsto puede publicar puertos al host.
  published="$(docker port "$cid" 2>/dev/null || true)"
  if [[ -n "$published" ]]; then
    if [[ "$PROFILE" == production && "$service" != tls-proxy ]]; then
      echo "ERROR: $service publica puertos en production" >&2; failed=1
    elif [[ "$PROFILE" == core && "$service" != reverse-proxy ]]; then
      echo "ERROR: $service publica puertos en core" >&2; failed=1
    fi
  fi
done

if (( failed != 0 )); then
  echo "Uno o más servicios no están listos." >&2
  exit 1
fi

bridge_id="$("${compose[@]}" ps -q bridge-api)"
docker exec "$bridge_id" alembic -c /app/alembic.ini current --check-heads >/dev/null
proxy_id="$("${compose[@]}" ps -q reverse-proxy)"
docker exec "$proxy_id" wget -q -O - http://127.0.0.1:8080/readyz >/dev/null
echo "health=PASS profile=$PROFILE services=${#services[@]} migrations=head readiness=pass"
