> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Documento histórico; sus estados, rutas o contratos pueden no corresponder al árbol actual. Consulte `docs/PRODUCTION_READINESS.md` y la documentación canónica homónima de 2026-08-15.

# Software Licensing Audit

| Repository | License Type | Compliance Requirements | Integration Constraint |
|---|---|---|---|
| **FlowWink** | MIT | Attribute copyright notice | Permissive for commercial and private deployment |
| **Chatwoot Community** | MIT | Attribute copyright notice (Note: `enterprise/` directory excluded for pure OS usage) | Keep core isolated, interact only via REST APIs |
| **Activepieces Community** | MIT | Attribute copyright notice (Note: Enterprise pieces excluded for pure OS usage) | Interact via REST APIs and webhooks |
| **Bridge API** | Proprietary / Client Owned | N/A | Core bridge orchestrator |
| **Admin Portal** | Proprietary / Client Owned | N/A | Control panel UI |
