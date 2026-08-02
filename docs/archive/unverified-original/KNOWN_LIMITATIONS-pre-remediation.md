# Known Limitations — Version v0.9.0-rc1

**Release Tag:** `v0.9.0-rc1`  
**Classification:** Controlled Client Pilot Environment  

---

## 1. Architectural Scope & Deployment Boundaries

1. **Single-Tenant Client Isolated Deployment Only:**
   - Multi-tenant shared database multi-company SaaS mode is **not** supported in `v0.9.0-rc1`. Each client requires an isolated container stack deployment.
2. **Pilot Mode Safeguard (`PILOT_MODE=true`):**
   - Direct automatic invoice issuance is disabled. All invoices are generated as `draft` and held in `/approvals` queue.
3. **FlowWink Component Delegation:**
   - FlowWink functions strictly as an interactive React SPA frontend and agent configuration dashboard. Transactional business logic, stock, pricing, and orders are delegated exclusively to Bridge API per Option A Architecture.

---

## 2. Resource Requirements

- **Minimum Recommended Host Hardware:**
  - **CPU:** 4 vCPUs
  - **RAM:** 8 GB RAM (16 GB recommended for full 14-container stack)
  - **Disk:** 30 GB SSD storage
