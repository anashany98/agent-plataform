#!/usr/bin/env bash
set -Eeuo pipefail
CLIENT_ID="${1:-desarrollo-local}"
DOMAIN="${2:-${CLIENT_ID}.local}"
PROXY_PORT="${3:-9000}"
exec ./scripts/provision-client.sh "$CLIENT_ID" "$DOMAIN" "$PROXY_PORT"
