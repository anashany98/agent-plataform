#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

CLIENT_ID="${1:-}"
TARGET_REF="${2:-}"
[[ "$CLIENT_ID" =~ ^[a-z0-9][a-z0-9-]{1,48}$ && -n "$TARGET_REF" ]] || {
  echo "Uso: $0 <client-id> <tag-o-commit>" >&2; exit 2;
}
: "${BACKUP_ENCRYPTION_PASSPHRASE:?Define BACKUP_ENCRYPTION_PASSPHRASE}"
ENV_FILE=".env.${CLIENT_ID}"
PROJECT="agent-${CLIENT_ID}"
[[ -f "$ENV_FILE" ]] || { echo "No existe $ENV_FILE" >&2; exit 1; }
PROFILE="${DEPLOY_PROFILE:-$(sed -n 's/^DEPLOY_PROFILE=//p' "$ENV_FILE" | tail -n1)}"
PROFILE="${PROFILE:-production}"
[[ "$PROFILE" =~ ^(core|full|production)$ ]] || { echo "Perfil inválido: $PROFILE" >&2; exit 1; }

git status --porcelain --untracked-files=no | grep -q . && {
  echo "El repositorio tiene cambios tracked sin confirmar." >&2; exit 1;
}
git rev-parse --verify "${TARGET_REF}^{commit}" >/dev/null || { echo "No existe $TARGET_REF" >&2; exit 1; }
previous="$(git rev-parse HEAD)"
target="$(git rev-parse "${TARGET_REF}^{commit}")"
[[ "$previous" != "$target" ]] || { echo "La instalación ya usa $target."; exit 0; }

compose=(docker compose --env-file "$ENV_FILE" -p "$PROJECT" -f docker-compose.yml)
if [[ "$PROFILE" == production ]]; then compose+=(-f infrastructure/compose/docker-compose.prod.example.yml); fi
compose+=(--profile "$PROFILE")
database_services=(bridge-db bridge-redis)
if [[ "$PROFILE" == full ]]; then
  database_services+=(chatwoot-db chatwoot-redis activepieces-db activepieces-redis)
fi
recovery_engine="scripts/.env.${CLIENT_ID}.recovery.py"
cp -- scripts/backup-restore-integral.py "$recovery_engine"
chmod 600 "$recovery_engine"

service_image_id() {
  local service="$1" container image_id
  container="$("${compose[@]}" ps -q "$service")"
  [[ -n "$container" ]] || { echo "$service no está iniciado; rollback no fijable." >&2; return 1; }
  image_id="$(docker inspect --format '{{.Image}}' "$container")"
  [[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "Image ID inválido para $service." >&2; return 1; }
  printf '%s' "$image_id"
}
previous_bridge_image="$(service_image_id bridge-api)"
previous_portal_image="$(service_image_id portal)"

backup="$(python3 "$recovery_engine" backup "$CLIENT_ID" --profile "$PROFILE")"
[[ -f "$backup" ]] || { echo "No se creó el backup previo." >&2; exit 1; }

rollback_on_error() {
  rc=$?
  trap - ERR
  echo "Actualización fallida; restaurando commit y backup previos..." >&2
  git checkout --detach "$previous" || true
  export BRIDGE_API_IMAGE="$previous_bridge_image"
  export PORTAL_IMAGE="$previous_portal_image"
  docker image inspect "$previous_bridge_image" "$previous_portal_image" >/dev/null || true
  "${compose[@]}" config --quiet || true
  "${compose[@]}" up -d --no-build --pull never "${database_services[@]}" || true
  python3 "$recovery_engine" restore "$CLIENT_ID" "$backup" --profile "$PROFILE" || true
  ./scripts/check-health.sh "$CLIENT_ID" "$PROFILE" || true
  exit "$rc"
}
trap rollback_on_error ERR

git checkout --detach "$target"
python3 scripts/production-preflight.py --env-file "$ENV_FILE" --profile "$PROFILE" --mode release
"${compose[@]}" config --quiet
"${compose[@]}" run --rm --no-deps --no-build --pull never --entrypoint alembic bridge-api -c /app/alembic.ini upgrade head
"${compose[@]}" up -d --no-build --pull never --wait --wait-timeout 600
./scripts/check-health.sh "$CLIENT_ID" "$PROFILE"

state=".env.${CLIENT_ID}.update-state.json"
python3 - "$state" "$CLIENT_ID" "$PROFILE" "$previous" "$target" "$backup" "$previous_bridge_image" "$previous_portal_image" "$recovery_engine" <<'PY'
import datetime, json, os, sys, tempfile
path, client, profile, previous, target, backup, bridge_image, portal_image, recovery_engine = sys.argv[1:]
with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=".", prefix=f".{path}.", suffix=".tmp", delete=False) as f:
    temporary = f.name
    json.dump({"client_id": client, "profile": profile, "previous_commit": previous,
               "target_commit": target, "backup": backup,
               "previous_bridge_image": bridge_image, "previous_portal_image": portal_image,
               "recovery_engine": recovery_engine,
               "updated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}, f, indent=2)
    f.write("\n")
os.chmod(temporary, 0o600)
os.replace(temporary, path)
PY
trap - ERR
echo "Actualización completada: $previous -> $target. Backup: $backup"
