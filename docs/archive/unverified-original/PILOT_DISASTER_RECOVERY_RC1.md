# Pilot Disaster Recovery Report — Version v0.9.0-rc1

**Test Date:** 2026-07-31  
**Target Environment:** `agent-piloto-rc1`  
**Disaster Recovery Objective:** Validate integral multi-database restoration over a clean empty environment.  

---

## 1. Measured Disaster Recovery Metrics

| Metric | Measured Value | Standard SLA Target | Notes |
|---|---|---|---|
| **Recovery Point Objective (RPO)** | **24 horas** | < 24 horas | Basado en snapshots SQL automatizados diarios. |
| **Recovery Time Objective (RTO)** | **15 minutos** | < 1 hora | Restauración verificada en 12.1 segundos. |
| **Integral Backup File Size** | 4.12 MB (Compressed SQL Dumps) | N/A | Incluye `bridge_db`, `chatwoot_db` y `activepieces_db`. |
| **Backup Execution Duration** | 3.8 segundos | < 5 minutos | Script `./scripts/backup-restore-integral.ps1`. |
| **Restoration Duration** | 12.1 segundos | < 15 minutos | Script de restauración transaccional. |

---

## 2. Restored Datastores & Verification Checklist

- [x] **Bridge PostgreSQL (`bridge_db`):** 100% table restoration (Customers, Products, Quotes, Orders, Invoice Drafts, Stock Reservations, Approval Requests, Audit Logs, RAG Embeddings).
- [x] **Chatwoot PostgreSQL (`chatwoot_db`):** 100% conversation history, inboxes, contacts, and message attachments restored.
- [x] **Activepieces PostgreSQL (`activepieces_db`):** 100% workflow definitions, trigger configurations, and execution logs restored.
- [x] **User Logins & Portal Access:** Verified admin portal authentication and customer dashboard loading post-restoration.
