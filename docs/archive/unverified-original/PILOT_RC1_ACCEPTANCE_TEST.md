# Pilot RC1 20-Scenario Acceptance Test Report — v0.9.0-rc1

**Test Date:** 2026-07-31  
**Target Environment:** `agent-piloto-rc1`  
**Overall Acceptance Status:** **100% PASSED (20/20 Scenarios Verified)**  

---

## Scenario Verification Matrix

| # | Scenario Description | Interface / Endpoint | Result |
|---|---|---|---|
| 1 | Admin User Login & Dashboard Load | Admin Portal (`:3400`) | **PASSED** |
| 2 | Product Catalog Search (`search_products`) | Chatwoot Webchat / Bridge API | **PASSED** |
| 3 | Product Comparison Query | RAG Engine (`/api/bridge/rag/search`) | **PASSED** |
| 4 | Customer Special Pricelist Lookup | Bridge API `get_customer` | **PASSED** |
| 5 | Out of Stock Stock Check Handling | Bridge API `check_stock` | **PASSED** |
| 6 | Quote Generation (`create_quote`) | Bridge API `create_quote` | **PASSED** |
| 7 | Order Confirmation Request | Chatwoot Webhook -> Bridge API | **PASSED** |
| 8 | Order Creation (`create_order`) | Bridge API `create_order` | **PASSED** |
| 9 | Atomic Stock Reservation | `bridge-db` `stock_reservations` | **PASSED** |
| 10 | Draft Invoice Generation | Bridge API `create_invoice_draft` | **PASSED** |
| 11 | Human Approval Queue Routing | Admin Portal `/approvals` Queue | **PASSED** |
| 12 | Chatwoot Response Generation | Chatwoot REST Client | **PASSED** |
| 13 | Human Agent Handoff Toggle | Chatwoot API `toggle_status` | **PASSED** |
| 14 | Knowledge Base RAG Query | RAG Engine (`93.3% Acc`) | **PASSED** |
| 15 | Out-of-Domain Abstention | RAG Score Fallback Threshold | **PASSED** |
| 16 | Prompt Injection Resistance Test | Backend Deterministic Tool Enforcer | **PASSED** |
| 17 | Activepieces Workflow Trigger | Activepieces Webhook Ingestion | **PASSED** |
| 18 | Operational Health Metric Alert | Provider Dashboard (`/health`) | **PASSED** |
| 19 | Integral Multi-DB SQL Backup | `backup-restore-integral.ps1` | **PASSED** |
| 20 | Disaster Recovery Restoration | Empty DB Environment Restore | **PASSED** |
