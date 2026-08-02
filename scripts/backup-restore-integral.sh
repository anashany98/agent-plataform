#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ACTION="${1:-}"
CLIENT_ID="${2:-}"
ARCHIVE="${3:-}"
if [[ ! "$ACTION" =~ ^(backup|restore)$ || ! "$CLIENT_ID" =~ ^[a-z0-9][a-z0-9-]{1,48}$ ]]; then
  echo "Uso: $0 backup <client-id> | $0 restore <client-id> <archivo.tar.gz.enc>" >&2
  exit 2
fi
: "${BACKUP_ENCRYPTION_PASSPHRASE:?Define BACKUP_ENCRYPTION_PASSPHRASE en el entorno}"
for cmd in docker openssl sha256sum python3 tar; do command -v "$cmd" >/dev/null || { echo "$cmd no está instalado." >&2; exit 1; }; done

ENV_FILE=".env.${CLIENT_ID}"
PROJECT="agent-${CLIENT_ID}"
[[ -f "$ENV_FILE" ]] || { echo "No existe $ENV_FILE" >&2; exit 1; }
compose=(docker compose --env-file "$ENV_FILE" -p "$PROJECT" --profile full)

container_id() {
  local id
  id="$("${compose[@]}" ps -q "$1")"
  [[ -n "$id" ]] || { echo "El servicio $1 no está iniciado." >&2; exit 1; }
  printf '%s' "$id"
}

dump_database() {
  local service="$1" output="$2" cid
  cid="$(container_id "$service")"
  docker exec "$cid" sh -ec 'rm -f /tmp/agent-platform.dump; pg_dump -Fc --no-owner --no-acl -U "$POSTGRES_USER" "$POSTGRES_DB" -f /tmp/agent-platform.dump'
  docker cp "$cid:/tmp/agent-platform.dump" "$output"
  docker exec "$cid" rm -f /tmp/agent-platform.dump
  [[ -s "$output" ]] || { echo "Dump vacío para $service" >&2; exit 1; }
}

restore_database() {
  local service="$1" input="$2" cid
  cid="$(container_id "$service")"
  docker cp "$input" "$cid:/tmp/agent-platform.dump"
  docker exec "$cid" sh -ec 'pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error -U "$POSTGRES_USER" -d "$POSTGRES_DB" /tmp/agent-platform.dump; rm -f /tmp/agent-platform.dump'
}

volume_archive() {
  local volume="$1" output="$2" stage_abs
  stage_abs="$(cd "$(dirname "$output")" && pwd)"
  docker run --rm --read-only -v "${volume}:/data:ro" -v "${stage_abs}:/backup" alpine:3.20 \
    sh -ec "tar -C /data -cf /backup/$(basename "$output") ."
}

volume_restore() {
  local volume="$1" input="$2" stage_abs
  stage_abs="$(cd "$(dirname "$input")" && pwd)"
  docker run --rm -v "${volume}:/data" -v "${stage_abs}:/backup:ro" alpine:3.20 \
    sh -ec "find /data -mindepth 1 -delete; tar -C /data -xf /backup/$(basename "$input")"
}

wait_healthy() {
  local deadline=$((SECONDS + 600))
  while (( SECONDS < deadline )); do
    local ids unhealthy total
    mapfile -t ids < <("${compose[@]}" ps -q)
    total=${#ids[@]}
    unhealthy=0
    for id in "${ids[@]}"; do
      state="$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$id")"
      [[ "$state" == "running healthy" || "$state" == "running none" ]] || unhealthy=$((unhealthy+1))
    done
    [[ $total -ge 14 && $unhealthy -eq 0 ]] && return 0
    sleep 5
  done
  echo "Los servicios no recuperaron un estado saludable dentro de 10 minutos." >&2
  "${compose[@]}" ps >&2
  return 1
}

if [[ "$ACTION" == "backup" ]]; then
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  base="infrastructure/backups/${CLIENT_ID}"
  stage="${base}/.${timestamp}.stage"
  output="${base}/${CLIENT_ID}-${timestamp}.tar.gz.enc"
  mkdir -p "$stage"
  trap 'rm -rf "$stage"' EXIT

  echo "[1/7] Bridge PostgreSQL"; dump_database bridge-db "$stage/bridge-db.dump"
  echo "[2/7] Chatwoot PostgreSQL"; dump_database chatwoot-db "$stage/chatwoot-db.dump"
  echo "[3/7] Activepieces PostgreSQL"; dump_database activepieces-db "$stage/activepieces-db.dump"
  echo "[4/7] Documentos RAG"; volume_archive "${PROJECT}_bridge_uploads" "$stage/bridge-uploads.tar"
  echo "[5/7] Adjuntos de Chatwoot"; volume_archive "${PROJECT}_chatwoot_storage_data" "$stage/chatwoot-storage.tar"
  echo "[6/7] Manifiesto y checksums"
  commit="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
  python3 - "$stage/manifest.json" "$CLIENT_ID" "$PROJECT" "$timestamp" "$commit" <<'PY'
import json, sys
path, client, project, created, commit = sys.argv[1:]
with open(path, "w", encoding="utf-8") as f:
    json.dump({"client_id": client, "project": project, "created_at_utc": created,
               "git_commit": commit, "format_version": 3, "encrypted": True}, f, ensure_ascii=False)
PY
  (cd "$stage" && sha256sum bridge-db.dump chatwoot-db.dump activepieces-db.dump bridge-uploads.tar chatwoot-storage.tar manifest.json > SHA256SUMS)
  echo "[7/7] Cifrado"
  tar -C "$stage" -czf - . | openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 -pass env:BACKUP_ENCRYPTION_PASSPHRASE -out "$output"
  sha256sum "$output" > "${output}.sha256"
  chmod 600 "$output" "${output}.sha256"
  rm -rf "$stage"; trap - EXIT
  echo "$output"
  exit 0
fi

[[ -n "$ARCHIVE" && -f "$ARCHIVE" ]] || { echo "Archivo de backup no válido." >&2; exit 1; }
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_ENCRYPTION_PASSPHRASE -in "$ARCHIVE" | tar -C "$tmp" -xzf -
(cd "$tmp" && sha256sum -c SHA256SUMS)
manifest_client="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["client_id"])' "$tmp/manifest.json")"
[[ "$manifest_client" == "$CLIENT_ID" ]] || { echo "El backup pertenece a $manifest_client, no a $CLIENT_ID." >&2; exit 1; }

"${compose[@]}" stop bridge-api chatwoot-web chatwoot-worker activepieces-app activepieces-worker
restore_database bridge-db "$tmp/bridge-db.dump"
restore_database chatwoot-db "$tmp/chatwoot-db.dump"
restore_database activepieces-db "$tmp/activepieces-db.dump"
volume_restore "${PROJECT}_bridge_uploads" "$tmp/bridge-uploads.tar"
volume_restore "${PROJECT}_chatwoot_storage_data" "$tmp/chatwoot-storage.tar"
"${compose[@]}" up -d
wait_healthy
"${compose[@]}" ps

echo "Restauración integral finalizada y servicios saludables. Ejecuta las pruebas funcionales antes de reabrir el servicio."
