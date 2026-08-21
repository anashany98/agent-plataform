> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Documento histórico; sus estados, rutas o contratos pueden no corresponder al árbol actual. Consulte `docs/PRODUCTION_READINESS.md` y la documentación canónica homónima de 2026-08-15.

# Bridge API Complete Endpoint Reference

Interactive OpenAPI documentation is served at `http://localhost:8005/docs`.

## Key Endpoints Summary

### System & Health
- `GET /health` -> `{"status": "ok", "service": "bridge-api", "db_status": "healthy"}`
- `GET /ready` -> `{"status": "ready"}`
- `GET /metrics` -> Audit count, total and pending approvals.

### Webhooks
- `POST /webhooks/chatwoot` -> Ingest Chatwoot events (`message_created`, etc.) with HMAC & Idempotency.
- `POST /webhooks/flowwink` -> Ingest FlowWink state updates.
- `POST /webhooks/activepieces` -> Ingest Activepieces workflow callbacks.

### Agent Execution & Governance
- `POST /agents/run` -> Execute agent prompt with model profile selection.
- `GET /approvals` -> List human approval queue.
- `POST /approvals/{id}/approve` -> Approve pending request.
- `POST /approvals/{id}/reject` -> Reject pending request.
- `GET /costs` -> Query aggregate token usage and costs.
