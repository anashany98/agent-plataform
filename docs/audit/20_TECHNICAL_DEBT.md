# 20 - Deuda técnica

| ID | Deuda | Principal | Interés actual | Prioridad | Esfuerzo | Pago recomendado |
|---|---|---|---|---|---|---|
| TD-01 | Monolito `main.py` | Mezcla rutas/negocio/integraciones | Races, baja cobertura, cambios riesgosos | P1 | L | Módulos auth/catalog/commerce/integrations/ops |
| TD-02 | Modelo de dominio sin state machine | Strings/status ad hoc | Pedido no autorizado y transiciones inválidas | P0 | M | Estados/transiciones/versionado |
| TD-03 | Réplica de catálogo sin coherencia | Sync simple | Precio/stock stale y bajas huérfanas | P0 | L | Ownership/snapshot/reconcile |
| TD-04 | Migración única dinámica | `create_all/drop_all` | Upgrade/rollback inseguros | P0 | M | Baseline congelada + migrations explícitas |
| TD-05 | Integración resiliente duplicada/ausente | Adapters directos | Timeouts/duplicados, lógica repetida | P1 | L | Cliente común retry/outbox/metrics |
| TD-06 | Estado en memoria | Agents/rate limit | Reinicios y réplicas incoherentes | P1 | M | Persistencia/Redis con TTL |
| TD-07 | Supply chain no reproducible | Ranges/tags | CVE y builds variables | P1 | M | Lock/hash/digest/SBOM/signing |
| TD-08 | Observabilidad pospuesta | Logs/health mínimos | MTTR indeterminado | P1 | L | OTel/logs/metrics/alerts |
| TD-09 | Portal de promesas | Nav/i18n muertos | Confusión comercial y deuda UI | P2 | M | Reducir a scope real + tests |
| TD-10 | Vendor sprawl | FlowWink/AP/CW completos | RAM, upgrades, licencias | P1 | M | ADR keep/remove por capacidad |
| TD-11 | Scripts duplicados Bash/PS | Dos implementaciones | Divergencia y test costoso | P2 | M | Núcleo común/CI de ambas variantes |
| TD-12 | Backup sin modelo DR | Scripts sin restore | Riesgo existencial | P0 | L | Policy, snapshots, restore drills |
| TD-13 | Tipado/formato no gobernado | 297 Ruff/71 MyPy | Fricción y errores | P2 | M/L | Baseline incremental + CI |
| TD-14 | Data lifecycle ausente | Sin export/delete/retención | Riesgo legal y storage | P1 | L | Servicios/políticas auditables |
| TD-15 | Documentación manual contradictoria | Claims copiadas | Falsa confianza | P1 | M | Docs-as-code desde pruebas/manifiesto |

## Orden de pago

1. TD-02/03/04/12: integridad y recuperación.
2. TD-05/06/08: operación real.
3. TD-07/10: supply chain y simplificación.
4. TD-01/13: mantenibilidad después de fijar invariantes con tests.
5. TD-09/11/14/15: producto repetible/comercial.

Evitar un “big-bang refactor”: primero tests de regresión P0, luego cambios por vertical y migraciones compatibles.

