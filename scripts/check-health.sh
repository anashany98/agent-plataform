#!/usr/bin/env bash
set -Eeuo pipefail
CLIENT_ID="${1:?Indica client-id}"
ENV_FILE=".env.${CLIENT_ID}"
PROJECT="agent-${CLIENT_ID}"
[[ -f "$ENV_FILE" ]] || { echo "No existe $ENV_FILE" >&2; exit 1; }
compose=(docker compose --env-file "$ENV_FILE" -p "$PROJECT" --profile full)
services=(reverse-proxy portal bridge-api bridge-db bridge-redis flowwink-app chatwoot-web chatwoot-worker chatwoot-db chatwoot-redis activepieces-app activepieces-worker activepieces-db activepieces-redis)
failed=0
for service in "${services[@]}"; do
  cid="$("${compose[@]}" ps -q "$service")"
  if [[ -z "$cid" ]]; then printf '%-26s %s\n' "$service" "AUSENTE"; failed=1; continue; fi
  state="$(docker inspect -f '{{.State.Status}}' "$cid")"
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
  printf '%-26s estado=%-10s salud=%s\n' "$service" "$state" "$health"
  [[ "$state" == running && ( "$health" == healthy || "$health" == none ) ]] || failed=1
done
exit "$failed"
