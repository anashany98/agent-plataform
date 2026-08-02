# FlowWink Runtime Audit & Capability Report — v0.9.0-rc1

**Component Name:** FlowWink Vendor Engine (`vendor/flowwink`)  
**Deployment Container:** `flowwink-app` (Port `:8090` / `:8490`)  
**Architecture Role (Option A):** Interactive React SPA Frontend & Agent Prompt Configuration  
**Audit Date:** 2026-07-31  

---

## 1. Operating Status & Function Classification

In compliance with **Option A Architecture**, FlowWink serves as an interactive React SPA user interface for agent management and prompt configuration. 

All transactional domain operations, stock reservations, pricing calculations, quote generation, and invoice draft issuances are strictly delegated to **Bridge API** (`bridge-api:8005`).

| FlowWink Feature | Status Classification | Operating Mechanism |
|---|---|---|
| **SPA UI Frontend** | **VERIFIED** | Served via Nginx on `:8090` (`:8490` pilot) |
| **Agent Prompt Config** | **VERIFIED** | Transmitted via REST API to Bridge API |
| **Transactional Logic** | **DELEGATED TO BRIDGE API** | Bridge API `deterministic_tools.py` |
| **Tool Invocation Engine** | **VERIFIED** | Invocations routed to Bridge API endpoints |
| **Database Persistence** | **DELEGATED TO BRIDGE DB** | `bridge-db` (Postgres 15) |

---

## 2. Tool Invocation Execution Audit

### Verified Agent Tools Delegated to Bridge API:
1. `search_products`: Evaluated via deterministic SQL query over `products` table.
2. `get_customer`: Pricelist and customer profile lookup from `customers` table.
3. `calculate_price`: Tax calculation (21% VAT standard / configurable), volume discounts, shipping calculation.
4. `check_stock`: Atomic stock availability verification in `products` table.
5. `create_quote`: Transactional quote creation and payload formatting.

**Execution Log Example:**
- **Agent ID:** `sales_agent_01`
- **Tool Invocations:** `search_products(query='Industrial')` -> `calculate_price(qty=10)` -> `create_quote()`
- **Status:** **VERIFIED**
