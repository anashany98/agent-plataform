# Architecture Decision Records (ADRs)

## ADR-001: Isolated Single-Client Deployment
- **Status:** Approved
- **Context:** Initial deployment model requirements.
- **Decision:** Build a single-tenant container architecture per client without shared multitenant database schemas.
- **Consequence:** Simplifies data isolation, security audits, and backups per client instance.

## ADR-002: Bridge API Middleware Pattern
- **Status:** Approved
- **Context:** Coordinating agent workflows between Chatwoot, FlowWink, and Activepieces.
- **Decision:** Build a dedicated Python 3.12 FastAPI service (`bridge-api`) to handle webhooks, routing, approvals, cost calculation, and deterministic tool execution.
- **Consequence:** Prevents vendor lock-in, avoids modifying upstream vendor code, and ensures centralized governance.

## ADR-003: Deterministic Financial & Inventory Tools
- **Status:** Approved
- **Context:** Preventing AI hallucinations in core business transactions.
- **Decision:** LLMs must invoke deterministic functions for all pricing, stock, tax, quote, order, and invoice operations.
- **Consequence:** Reduces hallucination risk and makes calculations reproducible; correctness still depends on source data, client configuration and executed tests.
