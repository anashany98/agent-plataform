#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
CLIENT_ID="${1:-}"
TARGET_REF="${2:-}"
[[ "$CLIENT_ID" =~ ^[a-z0-9][a-z0-9-]{1,48}$ && -n "$TARGET_REF" ]] || { echo "Uso: $0 <client-id> <tag-o-commit>" >&2; exit 2; }
: "${BACKUP_ENCRYPTION_PASSPHRASE:?Define BACKUP_ENCRYPTION_PASSPHRASE}"
ENV_FILE=".env.${CLIENT_ID}"; PROJECT="agent-${CLIENT_ID}"
[[ -f "$ENV_FILE" ]] || { echo "No existe $ENV_FILE" >&2; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "El repositorio tiene cambios sin confirmar. Cancela o confirma los cambios." >&2; exit 1; }
git rev-parse --verify "${TARGET_REF}^{commit}" >/dev/null || { echo "No existe la referencia $TARGET_REF" >&2; exit 1; }
previous="$(git rev-parse HEAD)"; target="$(git rev-parse "${TARGET_REF}^{commit}")"
[[ "$previous" != "$target" ]] || { echo "La instalación ya usa $TARGET_REF ($target)."; exit 0; }
state_dir="infrastructure/update-state"; mkdir -p "$state_dir"
backup="$(./scripts/backup-restore-integral.sh backup "$CLIENT_ID" | tail -n1)"
[[ -f "$backup" ]] || { echo "No se creó el backup previo." >&2; exit 1; }
compose=(docker compose --env-file "$ENV_FILE" -p "$PROJECT" --profile full)
rollback_on_error() {
  rc=$?
  echo "Actualización fallida. Restaurando código y datos anteriores..." >&2
  git checkout --detach "$previous" || true
  "${compose[@]}" build || true
  "${compose[@]}" up -d || true
  ./scripts/backup-restore-integral.sh restore "$CLIENT_ID" "$backup" || true
  exit "$rc"
}
trap rollback_on_error ERR

git checkout --detach "$target"
"${compose[@]}" config >/dev/null
"${compose[@]}" build --pull
"${compose[@]}" up -d
./scripts/check-health.sh "$CLIENT_ID"
python3 - "$state_dir/${CLIENT_ID}.json" "$CLIENT_ID" "$previous" "$target" "$backup" <<'PY'
import datetime, json, sys
path, client, previous, target, backup = sys.argv[1:]
with open(path, "w", encoding="utf-8") as f:
    json.dump({"client_id": client, "previous_commit": previous, "target_commit": target,
               "backup": backup, "updated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}, f, indent=2)
PY
chmod 600 "$state_dir/${CLIENT_ID}.json"
trap - ERR
echo "Actualización completada: $previous -> $target. Backup: $backup"
