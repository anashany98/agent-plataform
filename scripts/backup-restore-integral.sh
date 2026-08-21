#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null || { echo "python3 es obligatorio" >&2; exit 1; }
cd "$ROOT"
exec "$PYTHON" "$ROOT/scripts/backup-restore-integral.py" "$@"
