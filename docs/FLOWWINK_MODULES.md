> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Documento histórico; sus estados, rutas o contratos pueden no corresponder al árbol actual. Consulte `docs/PRODUCTION_READINESS.md` y la documentación canónica homónima de 2026-08-15.

# FlowWink Modules Audit

| Module Name | Implementation Status | Functional Description | Cross-Cutting Concerns |
|---|---|---|---|
| **Agent Registry** | Complete UI / Mock Backend | Manages agent definitions, system prompts, model profiles, and capabilities. | Telemetry, Audit |
| **MCP Integration** | Complete | Protocol client for Model Context Protocol tools and servers. | Security, Validation |
| **Process Engine** | Complete | Process simulation and quote-to-cash execution engine. | Idempotency |
| **Product & Inventory** | Partial UI / Edge Shim | Product catalogue viewer, stock checks, pricing rules. | Deterministic API |
| **Order & Invoicing** | Partial UI / Edge Shim | Order creation and invoice draft generation. | Approval Workflows |
| **CRM & Leads** | Complete UI | Lead capture, contact timeline, opportunity tracking. | Bridge Sync |
| **SEO Continuous Cycle**| Complete Logic | Technical crawler, metadata checker, content recommendations. | Approvals |
| **RAG Knowledge Base** | Complete Frontend | Document chunking, pgvector embedding queries, citation display. | Vector Store |
