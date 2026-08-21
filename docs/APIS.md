> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Documento histórico; sus estados, rutas o contratos pueden no corresponder al árbol actual. Consulte `docs/PRODUCTION_READINESS.md` y la documentación canónica homónima de 2026-08-15.

# API Specification & Endpoint Registry

## Bridge API Endpoints (`http://localhost:8005`)

### Operational & Health
- `GET /health` - Service health status and database connectivity.
- `GET /ready` - Readiness probe for traffic routing.
- `GET /metrics` - Telemetry and performance metrics.

### Webhook Listeners
- `POST /webhooks/chatwoot` - Receives inbound Chatwoot events (`message_created`, etc.).
- `POST /webhooks/flowwink` - Receives state updates and callbacks from FlowWink processes.
- `POST /webhooks/activepieces` - Receives execution callbacks from Activepieces workflows.

### Governance & Approvals
- `POST /approvals` - Create a human approval request.
- `GET /approvals` - List pending and resolved human approval requests.
- `POST /approvals/{id}/approve` - Grant approval for a suspended process/action.
- `POST /approvals/{id}/reject` - Reject a pending process/action.

### Agent Execution & Cost Control
- `POST /agents/run` - Execute an agent process with prompt, memory, and model tier selection.
- `GET /runs` - Query agent execution history.
- `GET /runs/{id}` - Retrieve detailed trace, tool calls, and model tokens for a specific run.
- `GET /costs` - Retrieve aggregate token usage, latencies, and financial costs by agent/user.
- `GET /integrations/status` - Health and connectivity matrix for Chatwoot, FlowWink, Activepieces.
