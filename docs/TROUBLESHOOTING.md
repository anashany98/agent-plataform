# Troubleshooting Guide

## Common Issues & Resolutions

### 1. Container Unhealthy / Restart Loop
- **Symptom:** `bridge-api` or `bridge-db` status shows restarting.
- **Fix:** Inspect logs using `docker logs bridge-api`. Verify database credentials in `.env` match `POSTGRES_USER` and `POSTGRES_PASSWORD`.

### 2. Webhook Duplication
- **Symptom:** Webhook processed multiple times.
- **Fix:** Ensure Redis is running (`docker compose ps bridge-redis`). Redis caches idempotency keys for 24 hours.

### 3. Port Conflicts
- **Symptom:** Bind for `0.0.0.0:8005` failed: port already in use.
- **Fix:** Adjust exposed port variables in `.env` (e.g. `BRIDGE_PORT=8006`).
