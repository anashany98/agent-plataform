#!/usr/bin/env bash
set -Eeuo pipefail
CLIENT_ID="${1:-}"
[[ "$CLIENT_ID" =~ ^[a-z0-9][a-z0-9-]{1,48}$ ]] || { echo "Uso: $0 <client-id>" >&2; exit 2; }
: "${BACKUP_ENCRYPTION_PASSPHRASE:?Define BACKUP_ENCRYPTION_PASSPHRASE}"
state="infrastructure/update-state/${CLIENT_ID}.json"
[[ -f "$state" ]] || { echo "No existe estado de actualización para $CLIENT_ID." >&2; exit 1; }
readarray -t values < <(python3 - "$state" <<'PY'
import json,sys
x=json.load(open(sys.argv[1])); print(x["previous_commit"]); print(x["backup"])
PY
)
previous="${values[0]}"; backup="${values[1]}"
[[ -f "$backup" ]] || { echo "No existe el backup $backup" >&2; exit 1; }
ENV_FILE=".env.${CLIENT_ID}"; PROJECT="agent-${CLIENT_ID}"
compose=(docker compose --env-file "$ENV_FILE" -p "$PROJECT" --profile full)
git diff --quiet && git diff --cached --quiet || { echo "Hay cambios sin confirmar." >&2; exit 1; }
git checkout --detach "$previous"
"${compose[@]}" build
"${compose[@]}" up -d
./scripts/backup-restore-integral.sh restore "$CLIENT_ID" "$backup"
./scripts/check-health.sh "$CLIENT_ID"
mv "$state" "${state}.rolled-back-$(date -u +%Y%m%dT%H%M%SZ)"
echo "Rollback completado al commit $previous."
