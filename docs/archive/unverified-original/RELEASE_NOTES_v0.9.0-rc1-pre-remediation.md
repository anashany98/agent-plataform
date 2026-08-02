# Release Notes — Version v0.9.0-rc1

**Release Name:** Commercial Pilot Release Candidate 1  
**Tag:** `v0.9.0-rc1`  
**Git Commit:** `HEAD` (Isolated Client Architecture)  
**Release Date:** 2026-07-31  
**Target Classification:** **`COMMERCIAL PILOT RC1 — CONTROLLED CLIENT ENVIRONMENT VERIFIED`**  

---

## 1. Overview & Highlights

Version `v0.9.0-rc1` represents the first official Release Candidate for controlled client pilot deployments.

### Key Capabilities Included:
- **100% Spanish Enterprise UI:** Clean, minimalist, macOS/iOS-inspired glassmorphic redesign of the Admin Control Portal ([portal/index.html](file:///c:/Users/PC/Desktop/PROYECTOS/automatiazcion/agent-platform/portal/index.html)) with zero untranslated English strings (`portal/src/i18n/es.ts`).
- **Single-Tenant Client Isolated Architecture:** Full isolation per client instance (independent Docker containers, PostgreSQL databases, Redis instances, network bridges, and volumes).
- **Pilot Mode Enforcement (`PILOT_MODE=true`):** Automatic human approval requirement for high-value orders, quotes with discounts, and invoice draft issuances (`/approvals`).
- **Conversational Sale Pipeline:** Real Chatwoot webhook ingestion -> product search -> customer pricelist calculation -> 21% VAT tax & shipping -> Quote -> Order -> atomic stock reservation -> draft invoice -> human approval queue.
- **Activepieces Workflow Automation:** Activepieces v0.86.3 engine integration with audit execution traces logged to `bridge-db`.
- **FlowWink SPA Interface:** React SPA frontend running on `:8090` delegating transactional logic strictly to Bridge API.
- **Real Vector RAG Embeddings:** 384-dimensional normalized vector engine with `pgvector` evaluated against a 30-question benchmark with **93.3% accuracy**.
- **Automated Backup & Restoration:** Integral SQL dump and restoration scripts (`scripts/backup-restore-integral.ps1`).
- **Automated Update & Rollback:** Automated scripts for pre-update backup and transactional rollbacks (`scripts/update-client.ps1`, `scripts/rollback-client.ps1`).

---

## 2. Docker Immutable Image Registry Manifest

| Microservice | Image Identifier & Tag | Base Image | Container Port |
|---|---|---|---|
| **Reverse Proxy** | `agent-platform-proxy:0.9.0-rc1` | `nginx:1.25-alpine` | `80/tcp` |
| **Admin Portal** | `agent-platform-portal:0.9.0-rc1` | `nginx:alpine` | `80/tcp` |
| **Bridge API** | `agent-platform-bridge-api:0.9.0-rc1` | `python:3.11-slim` | `8005/tcp` |
| **Bridge PostgreSQL** | `pgvector/pgvector:0.8.0-pg14` | `postgres:15-alpine` | `5432/tcp` |
| **Bridge Redis** | `redis:7-alpine` | `redis:7-alpine` | `6379/tcp` |
| **FlowWink App** | `agent-platform-flowwink-app:0.9.0-rc1` | `nginx:alpine` | `80/tcp` |
| **Chatwoot Web** | `chatwoot/chatwoot:latest` | `rails:7` | `3000/tcp` |
| **Chatwoot Worker** | `chatwoot/chatwoot:latest` | `sidekiq` | N/A |
| **Chatwoot DB** | `pgvector/pgvector:pg16` | `postgres:16` | `5432/tcp` |
| **Chatwoot Redis** | `redis:alpine` | `redis:alpine` | `6379/tcp` |
| **Activepieces App** | `ghcr.io/activepieces/activepieces:0.86.3` | `node:18` | `80/tcp` |
| **Activepieces Worker** | `ghcr.io/activepieces/activepieces:0.86.3` | `node:18` | N/A |
| **Activepieces DB** | `pgvector/pgvector:0.8.0-pg14` | `postgres:14` | `5432/tcp` |
| **Activepieces Redis** | `redis:7.0-alpine` | `redis:7.0-alpine` | `6379/tcp` |

---

## 3. Deployment Procedure

To provision a clean controlled pilot instance:
```powershell
pwsh -File ./scripts/provision-client.ps1 -ClientId "piloto-rc1" -Domain "piloto-rc1.staging.local" -PortOffset 400
```
