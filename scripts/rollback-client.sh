#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

CLIENT_ID="${1:-}"
[[ "$CLIENT_ID" =~ ^[a-z0-9][a-z0-9-]{1,48}$ ]] || { echo "Uso: $0 <client-id>" >&2; exit 2; }
: "${BACKUP_ENCRYPTION_PASSPHRASE:?Define BACKUP_ENCRYPTION_PASSPHRASE}"
state=".env.${CLIENT_ID}.update-state.json"
[[ -f "$state" ]] || { echo "No existe estado para $CLIENT_ID." >&2; exit 1; }
readarray -t values < <(python3 - "$state" <<'PY'
import json, sys
x=json.load(open(sys.argv[1], encoding="utf-8"))
print(x["previous_commit"]); print(x["backup"]); print(x.get("profile", "production"))
print(x.get("previous_bridge_image", "")); print(x.get("previous_portal_image", ""))
print(x.get("recovery_engine", ""))
PY
)
previous="${values[0]}"
backup="${values[1]}"
PROFILE="${values[2]}"
previous_bridge_image="${values[3]}"
previous_portal_image="${values[4]}"
recovery_engine="${values[5]}"
[[ -f "$backup" ]] || { echo "No existe $backup" >&2; exit 1; }
[[ "$PROFILE" =~ ^(core|full|production)$ ]] || { echo "Perfil inválido en state: $PROFILE" >&2; exit 1; }
[[ "$previous_bridge_image" =~ ^sha256:[0-9a-f]{64}$ && "$previous_portal_image" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo "El estado no contiene image IDs exactos; rollback automático no seguro." >&2; exit 1;
}
[[ "$recovery_engine" == "scripts/.env.${CLIENT_ID}.recovery.py" && -f "$recovery_engine" ]] || {
  echo "No existe el motor de recovery exacto que creó el backup." >&2; exit 1;
}
ENV_FILE=".env.${CLIENT_ID}"
PROJECT="agent-${CLIENT_ID}"
[[ -f "$ENV_FILE" ]] || { echo "No existe $ENV_FILE" >&2; exit 1; }
git status --porcelain --untracked-files=no | grep -q . && { echo "Hay cambios tracked sin confirmar." >&2; exit 1; }

compose=(docker compose --env-file "$ENV_FILE" -p "$PROJECT" -f docker-compose.yml)
if [[ "$PROFILE" == production ]]; then compose+=(-f infrastructure/compose/docker-compose.prod.example.yml); fi
compose+=(--profile "$PROFILE")
database_services=(bridge-db bridge-redis)
if [[ "$PROFILE" == full ]]; then
  database_services+=(chatwoot-db chatwoot-redis activepieces-db activepieces-redis)
fi

git checkout --detach "$previous"
export BRIDGE_API_IMAGE="$previous_bridge_image"
export PORTAL_IMAGE="$previous_portal_image"
docker image inspect "$previous_bridge_image" "$previous_portal_image" >/dev/null
"${compose[@]}" config --quiet
"${compose[@]}" up -d --no-build --pull never "${database_services[@]}"
python3 "$recovery_engine" restore "$CLIENT_ID" "$backup" --profile "$PROFILE"
./scripts/check-health.sh "$CLIENT_ID" "$PROFILE"
mv -- "$state" "${state}.rolled-back-$(date -u +%Y%m%dT%H%M%SZ)"
rm -f -- "$recovery_engine"
echo "Rollback completado al commit $previous usando restore verificado."
