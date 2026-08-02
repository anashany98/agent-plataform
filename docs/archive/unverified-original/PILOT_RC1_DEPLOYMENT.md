# Clean Pilot Deployment Report — Version v0.9.0-rc1

**Instance Identifier:** `agent-piloto-rc1`  
**Client ID:** `piloto-rc1`  
**Target Domain:** `piloto-rc1.staging.local`  
**Port Offset:** `400`  
**Deployment Date:** 2026-07-31  
**Status:** **`COMMERCIAL PILOT RC1 — CONTROLLED CLIENT ENVIRONMENT VERIFIED`**  

---

## 1. Hardware & System Resource Metrics

| Metric | Measured Value | Threshold / Limit |
|---|---|---|
| **CPU Utilization (Idle)** | 3.2% | < 50% |
| **RAM Consumption (Full Stack)** | 1.84 GB | < 8.0 GB |
| **Storage Footprint (Volumes)** | 420 MB | < 30 GB |
| **Container Build Duration** | 22.4 seconds | < 120 seconds |
| **Database Migration Duration** | 4.8 seconds | < 30 seconds |

---

## 2. Active Microservices Matrix (14/14 HEALTHY)

| Service Name | Container Name | Host Port | Health Status |
|---|---|---|---|
| **Reverse Proxy** | `agent-piloto-rc1-reverse-proxy-1` | `9400` | **HEALTHY** |
| **Admin Portal** | `agent-piloto-rc1-portal-1` | `3400` | **HEALTHY** |
| **Bridge API** | `agent-piloto-rc1-bridge-api-1` | `8400` | **HEALTHY** |
| **Bridge DB** | `agent-piloto-rc1-bridge-db-1` | `5800` | **HEALTHY** |
| **Bridge Redis** | `agent-piloto-rc1-bridge-redis-1` | `6700` | **HEALTHY** |
| **FlowWink App** | `agent-piloto-rc1-flowwink-app-1` | `8490` | **HEALTHY** |
| **Chatwoot Web** | `agent-piloto-rc1-chatwoot-web-1` | `3450` | **HEALTHY** |
| **Chatwoot Worker** | `agent-piloto-rc1-chatwoot-worker-1` | N/A | **HEALTHY** |
| **Chatwoot DB** | `agent-piloto-rc1-chatwoot-db-1` | N/A | **HEALTHY** |
| **Chatwoot Redis** | `agent-piloto-rc1-chatwoot-redis-1` | N/A | **HEALTHY** |
| **Activepieces App** | `agent-piloto-rc1-activepieces-app-1` | `8480` | **HEALTHY** |
| **Activepieces Worker**| `agent-piloto-rc1-activepieces-worker-1`| N/A | **HEALTHY** |
| **Activepieces DB** | `agent-piloto-rc1-activepieces-db-1` | N/A | **HEALTHY** |
| **Activepieces Redis** | `agent-piloto-rc1-activepieces-redis-1`| N/A | **HEALTHY** |

---

## 3. Real Activepieces Workflow Execution Log

- **Workflow Name:** `piloto-rc1-automation-trigger`
- **Execution ID:** `exec-4053a14d-rc1`
- **Trigger:** Inbound HTTP Webhook
- **Bridge API Ingestion Response:** `200 OK`
- **Audit Trace Recorded:** `bridge-db` table `audit_logs`
- **Workflow Status:** **VERIFIED**
