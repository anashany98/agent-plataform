> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# 08 - Matriz de capacidades

| Capacidad | Responsable/fuente real | Estado | Tests y e2e | Defecto/riesgo principal | Trabajo pendiente |
|---|---|---|---|---|---|
| Autenticación | Bridge/users | VERIFIED | Login runtime + tests | Custom JWT/PBKDF2; entorno development | Añadir lockout distribuido, iss/aud y pruebas proxy |
| Usuarios | Bridge/users | PARTIALLY VERIFIED | CRUD/RBAC local parcial | Sin UI real, lifecycle/retención | Tests CRUD completos y e2e |
| Roles/permisos | Bridge | PARTIALLY VERIFIED | Viewer/admin tests | Sin matriz exhaustiva; race aprobación | Contract tests por endpoint |
| Clientes | Bridge customers | PARTIALLY VERIFIED | Seed/import local | No CRUD/API ni sincronización GHL | Definir ownership y endpoints mínimos |
| Productos | PrestaShop pretendido; Bridge real | BROKEN | Tests locales/mocks | 100 demo tratados como verificados | Eliminar demo y validar sandbox |
| Categorías | PrestaShop | NOT IMPLEMENTED | Ninguno | Solo string copiado | API/sync/contrato |
| Tarifas | Bridge pricelists | PARTIALLY VERIFIED | Descuento demo | Ignora specific prices/grupos reales | Motor contractual PrestaShop |
| Stock | PrestaShop pretendido; Bridge real | BROKEN | Reserva local test | Stale y no sincronizado | Reserva/confirmación en autoridad |
| Presupuestos | Bridge | PARTIALLY VERIFIED | Tests SQLite con demo | Sin expiración/frescura/versión oferta | Snapshot trazable y e2e |
| Pedidos | Bridge | BROKEN | Tests locales | `no acepto`; no PrestaShop | Máquina de estados e idempotencia |
| Reservas | Bridge | BROKEN | Atomicidad simple test | Sin TTL/liberación/cancelación | Lifecycle y lock externo |
| Facturas | Bridge draft | NOT IMPLEMENTED | Se prueba borrador | No emisión/export/serie legal | Integrar sistema fiscal; aprobación robusta |
| Aprobaciones | Bridge/Portal | PARTIALLY VERIFIED | Single-use secuencial | Condición de carrera | Update condicional y concurrencia |
| Conversaciones | Chatwoot | BROKEN | Payload sintético | Web caído, DB vacía, no widget/e2e | Onboarding e2e y retries |
| Handoff humano | Chatwoot adapter | BROKEN | Ninguno real | Solo cambia status, no asigna | Asignación a equipo/agente + SLA |
| Agentes | Bridge/FlowWink/LLM | BROKEN | Mock explícito | Sin tool calling, registro en memoria, no red | Reducir a Bridge versionado y allowlist |
| Documentos | Bridge uploads | PARTIALLY VERIFIED | TXT real en test | Runtime vacío; MIME/AV incompletos | Corpus ficticio e2e y hardening |
| RAG | Bridge/pgvector/Ollama | PARTIALLY VERIFIED | TF-IDF local | Embeddings reales bloqueados; filtro evadible | Embedding/reranker real, evals y ACL |
| SEO | Ninguno | NOT IMPLEMENTED | Ninguno | Solo texto i18n/documentación | Retirar de promesa o implementar |
| Automatizaciones | Activepieces | BROKEN | Adapter mock | 0 flujos, fake execution ID, no egress | Flujo real o retirar componente |
| Costes | AuditLog/LLM router | BROKEN | Mock confirma 0 | Estimador siempre 0; kill switch inerte | Tarifario versionado y guardas duras |
| Importación | Bridge | PARTIALLY VERIFIED | CSV/dedup local | N+1, no upsert/escala | Batch, transacción, reportes y e2e |
| Exportación | Ninguno | NOT IMPLEMENTED | Ninguno | Lock-in y derechos de datos | Export CSV/JSON por dominio |
| Backup | Scripts | IMPLEMENTED BUT NOT TESTED | Revisión estática | Inconsistente/incompleto; convención distinta | Backup real con fixture y manifiesto |
| Restauración | Scripts | BLOCKED | No ejecutada | Sin backup válido/passphrase/recursos | Restore aislado + evidencia RPO/RTO |
| Actualización | Scripts/Git | BROKEN | No ejecutada | No `.git`; checkout global | Releases inmutables por imagen |
| Rollback | Scripts/Git/backup | BROKEN | No ejecutada | Depende de update/restore rotos | Ensayo completo |
| Monitorización | Health/metrics mínimos | NOT IMPLEMENTED | Health puntual | Sin collector/dashboard/SLO | Stack mínimo y runbooks |
| Alertas | Ninguno | NOT IMPLEMENTED | Ninguno | Fallos actuales no notifican | Alertas de servicio/cola/coste/backup |
| Privacidad/eliminación | Ninguno | NOT IMPLEMENTED | Ninguno | Sin retención, export ni borrado | Política y herramientas por cliente |

## Resumen cuantitativo

- VERIFIED: 1 capacidad de negocio transversal (autenticación).
- PARTIALLY VERIFIED: 9.
- IMPLEMENTED BUT NOT TESTED: 1.
- BROKEN: 11.
- NOT IMPLEMENTED: 7.
- BLOCKED: 1.

El conteo es orientativo por filas y no equivale a porcentaje de producto. Las capacidades críticas de venta real están BROKEN.

## Archivos revisados y evidencia

Rutas/modelos/servicios propios, tests ejecutados, DB real, adaptadores, scripts y runtime Docker.

## Riesgos y pendiente

- La UI y documentación presentan más módulos de los que existen.
- Los tests locales elevan cobertura sin verificar integraciones principales.
- La matriz debe convertirse en criterios de aceptación y puertas de release; no basta con cambiar etiquetas.
