#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_ID="${1:-desarrollo-local}"
DOMAIN="${2:-${CLIENT_ID}.local}"
PROXY_PORT="${3:-9000}"
PROFILE="${4:-core}"
TLS_CERTIFICATE="${5:-}"
TLS_PRIVATE_KEY="${6:-}"
cd "$ROOT"
exec ./scripts/provision-client.sh "$CLIENT_ID" "$DOMAIN" "$PROXY_PORT" "$PROFILE" "$TLS_CERTIFICATE" "$TLS_PRIVATE_KEY"
