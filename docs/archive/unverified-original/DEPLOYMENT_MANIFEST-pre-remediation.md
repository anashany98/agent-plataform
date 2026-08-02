# Deployment Manifest — Version v0.9.0-rc1

**Target Environment:** Controlled Staging / Client Pilot Instance  
**Architecture:** Single-Tenant Client Isolated Stack  

---

## 1. Environment Variable Schema

Each client instance requires a dedicated `.env.<client_id>` file:

```env
COMPOSE_PROJECT_NAME=agent-piloto-rc1
CLIENT_ID=piloto-rc1
CLIENT_DOMAIN=piloto-rc1.staging.local

PORTAL_PORT=3405
BRIDGE_PORT=8405
BRIDGE_DB_PORT=5805
BRIDGE_REDIS_PORT=6705
FLOWWINK_PORT=8495
PROXY_PORT=9405
CHATWOOT_PORT=3455
ACTIVEPIECES_PORT=8485

PILOT_MODE=true
ENVIRONMENT=staging
DATABASE_URL=postgresql://bridge_user:bridge_dev_secret_password_123@bridge-db:5432/bridge_db
REDIS_URL=redis://bridge-redis:6379/0
CHATWOOT_BASE_URL=http://chatwoot-web:3000
FLOWWINK_BASE_URL=http://flowwink-app:80
ACTIVEPIECES_BASE_URL=http://activepieces-app:80
```

---

## 2. Service Port Matrix & Health Commands

| Container | Host Port (Offset +400) | Health Command |
|---|---|---|
| `reverse-proxy` | `9405` | `wget -q -O - http://127.0.0.1:80/health` |
| `portal` | `3405` | `wget -q -O - http://127.0.0.1:80/` |
| `bridge-api` | `8405` | `curl -f http://localhost:8005/health` |
| `flowwink-app` | `8495` | `wget -q -O - http://127.0.0.1:80/` |
| `chatwoot-web` | `3455` | `wget -q -O - http://127.0.0.1:3000/health` |
| `activepieces-app` | `8485` | `node -e "fetch('http://localhost:80/api/v1/flags')"` |
