> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Documento histórico; sus estados, rutas o contratos pueden no corresponder al árbol actual. Consulte `docs/PRODUCTION_READINESS.md` y la documentación canónica homónima de 2026-08-15.

# Security & Operational Risk Audit

## Key Risk Areas & Mitigations

### 1. Hallucination in Pricing / Stock / Invoices
- **Risk:** LLM generating incorrect prices, tax rates, stock availability, or invoice totals.
- **Mitigation:** LLMs are strictly forbidden from producing math or prices directly. All calculations are deferred to deterministic Python functions via Bridge API tools (`calculate_price`, `check_stock`, `create_invoice_draft`).

### 2. Prompt Injection Attacks
- **Risk:** Malicious user messages attempting to bypass human approval or extract private customer data.
- **Mitigation:** Input sanitation, role separation, strict tool schema validation, human approval gateways for sensitive endpoints.

### 3. Duplicate Order / Webhook Execution
- **Risk:** Network retries causing duplicate order creation or double billing.
- **Mitigation:** Mandatory idempotency keys cached in Redis for every mutation tool call and webhook handler.

### 4. Database Coupling
- **Risk:** Direct queries into vendor databases breaking on upstream updates.
- **Mitigation:** Zero direct DB sharing across vendor microservices. All interactions take place via HTTP APIs, webhooks, or Bridge API wrappers.
