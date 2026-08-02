# Commercial Deployment & Client Provisioning Guide

## Overview
The **AI Agent Enterprise Platform (`agent-platform`)** supports multi-client single-tenant deployment. Each client environment is isolated in its own Docker network namespace and dedicated database volumes.

---

## 1. Client Provisioning Script

### Linux / macOS:
```bash
./scripts/provision-client.sh cliente-demo cliente-demo.empresa.com
```

### Windows PowerShell:
```powershell
.\scripts\provision-client.ps1 -ClientId "cliente-demo" -Domain "cliente-demo.empresa.com"
```

### Actions Performed by Script:
1. Generates isolated client environment configuration (`.env.cliente-demo`).
2. Creates random high-entropy passwords for `POSTGRES_PASSWORD`, `CHATWOOT_API_TOKEN`, `CHATWOOT_WEBHOOK_SECRET`.
3. Spins up isolated Docker container stack under compose project name `agent-cliente-demo`.
4. Runs database migrations and seeds initial product catalog and admin user.
5. Verifies container health checks and outputs access URLs.

---

## 2. De-provisioning a Client Instance
To safely remove a test client instance without affecting other client stacks:
```bash
docker compose -p "agent-cliente-demo" down -v
```
