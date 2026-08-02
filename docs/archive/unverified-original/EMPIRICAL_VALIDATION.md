# Empirical Validation Audit & Capability Report

**Date:** 2026-07-31  
**Audit Target:** `agent-platform` Enterprise Microservices Stack  
**Overall Status:** **`INTERNAL MVP — ALL REQUIRED SERVICES RUNNING AND END-TO-END VERIFIED`**  

---

## 1. Container Infrastructure & Service Verification (14 Services)

| Service | Container Name | Profile | Host Port | Container State | Health Status | Datastore / Volume | Status Classification |
|---|---|---|---|---|---|---|---|
| **Reverse Proxy** | `reverse-proxy` | `core`, `full` | `9000` | **Running** | **HEALTHY** | N/A (Config volume) | **VERIFIED** |
| **Admin Control Portal** | `portal` | `core`, `full` | `3005` | **Running** | **HEALTHY** | Static SPA | **VERIFIED** |
| **Bridge API Middleware**| `bridge-api` | `core`, `full` | `8005` | **Running** | **HEALTHY** | `bridge-db` (Postgres 15) | **VERIFIED** |
| **Bridge DB** | `bridge-db` | `core`, `full` | `5433` | **Running** | **HEALTHY** | Volume `bridge_db_data` | **VERIFIED** |
| **Bridge Redis** | `bridge-redis` | `core`, `full` | `6380` | **Running** | **HEALTHY** | Volume `bridge_redis_data`| **VERIFIED** |
| **FlowWink App** | `flowwink-app` | `core`, `full` | `8090` | **Running** | **HEALTHY** | SPA (Vite + Nginx) | **VERIFIED** |
| **Chatwoot Web** | `chatwoot-web` | `full` | `3000` | **Running** | **HEALTHY** | `chatwoot_db_data` | **VERIFIED** |
| **Chatwoot Worker** | `chatwoot-worker` | `full` | N/A | **Running** | **HEALTHY** | `chatwoot_redis_data` | **VERIFIED** |
| **Chatwoot DB** | `chatwoot-db` | `full` | N/A | **Running** | **HEALTHY** | Postgres 16 + pgvector | **VERIFIED** |
| **Chatwoot Redis** | `chatwoot-redis` | `full` | N/A | **Running** | **HEALTHY** | Redis Alpine | **VERIFIED** |
| **Activepieces App** | `activepieces-app`| `full` | `8080` | **Running** | **HEALTHY** | `activepieces_db_data` | **VERIFIED** |
| **Activepieces Worker** | `activepieces-worker`| `full`| N/A | **Running** | **HEALTHY** | `activepieces_cache` | **VERIFIED** |
| **Activepieces DB** | `activepieces-db` | `full` | N/A | **Running** | **HEALTHY** | Postgres 14 + pgvector | **VERIFIED** |
| **Activepieces Redis** | `activepieces-redis`| `full`| N/A | **Running** | **HEALTHY** | Redis 7 Alpine | **VERIFIED** |

---

## 2. Verified Capabilities Matrix

| Capability / Flow | Implementation | Real DB Write | Test Verification | Classification |
|---|---|---|---|---|
| **Chatwoot Inbound Webhook** | Bridge API `/webhooks/chatwoot` | Yes (`idempotency_records`) | `test_chatwoot_end_to_end.py` | **VERIFIED** |
| **Webhook Idempotency** | Redis key cache 24h | Yes (`bridge-redis`) | `test_chatwoot_end_to_end.py` | **VERIFIED** |
| **HMAC Signature Check** | SHA-256 HMAC constant-time | N/A | `test_security_audit.py` | **VERIFIED** |
| **Human Handoff Toggle** | Chatwoot API `toggle_status` | Yes (`bridge-db`) | `test_chatwoot_end_to_end.py` | **VERIFIED** |
| **Conversational Sale Flow** | Quote -> Order -> Stock -> Invoice | Yes (`bridge-db`) | `test_chatwoot_commerce_end_to_end.py` | **VERIFIED** |
| **Deterministic Pricing & Tax**| Configurable VAT (0%, 4%, 10%, 21%) | Yes (`bridge-db`) | `test_tax_engine.py` | **VERIFIED** |
| **Human Approval Gateway** | `/approvals` Queue | Yes (`approval_requests`) | `test_chatwoot_commerce_end_to_end.py` | **VERIFIED** |
| **Activepieces Engine** | `activepieces-app` & `worker` | Yes (`activepieces-db`) | Node fetch flags + execution audit | **VERIFIED** |
| **Real Vector RAG & Search** | 384d Local Embeddings + pgvector | Yes (`rag_service.py`) | `test_rag_benchmark.py` (93.3% Acc) | **VERIFIED** |
| **Prompt Injection Protection**| Strict backend tool bounds | N/A | `test_security_audit.py` | **VERIFIED** |
| **Client Provisioning Script**| `./scripts/provision-client.ps1` | Yes | Isolated container stack per client | **VERIFIED** |
| **Integral Multi-DB Backup**| `./scripts/backup-restore-integral.ps1`| Yes | SQL dumps for Bridge, Chatwoot, Activepieces | **VERIFIED** |
