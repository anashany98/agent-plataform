> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# 11 - Tests faltantes

## P0 antes de cualquier piloto

| Test | Tipo | Criterio de aceptación | Dependencia | Esfuerzo |
|---|---|---|---|---|
| Exclusión de demo | Regresión | Ninguna ruta externa devuelve/cotiza `source=demo` | Fix catálogo | S |
| Negación/consentimiento | Tabla de casos | `no acepto`, “aún no”, citas y texto adversarial nunca confirman | State machine | S |
| Precio contractual | Contract/e2e | Variante, specific price, grupo, cantidad, IVA y moneda coinciden con PrestaShop | Sandbox | M |
| Stock/pedido concurrente | Concurrencia | N compradores no sobre-venden; un pedido externo por idempotency key | Sandbox + PostgreSQL | M |
| Aprobación concurrente | Concurrencia | Solo una transición terminal; sin last-write-wins | PostgreSQL | S |
| GHL retry/idempotencia | Fault injection | Caída tras cada efecto no duplica contacto/oportunidad | Sandbox/fake contractual stateful | M |
| Chat e2e | E2E | Widget → webhook HMAC → respuesta visible → asignación humana | Chatwoot funcional | M |
| Backup/restore completo | DR | Tres DB, uploads y configuración restauran hashes/contadores | Host aislado | M |

## Seguridad

- Matriz RBAC de cada endpoint y cambio de rol/desactivación concurrente.
- Rate limit con proxy confiable, spoof de `X-Real-IP`, múltiples workers y Redis.
- HMAC replay por delivery ID, timestamp boundary, JSON exacto, key rotation.
- RAG: paráfrasis de secreto, ACL por defecto, prompt injection en documentos, MIME spoof, zip bomb, PDF/image corruptos y antivirus.
- SSRF/allowlist para URLs de integraciones y ruta Activepieces.
- XSS con nombres/descripciones externos, CSP real y manejo de token de portal.
- Secret scanning, logging redaction y ausencia de credenciales en backups/artefactos.
- Migración upgrade/downgrade sobre datos ficticios; downgrade nunca debe `drop_all` en producción.

## Resiliencia e integración

- Timeouts, 429/5xx, jitter/backoff, circuit breaker y recuperación para cada adapter.
- Outbox/delivery tras reinicio de Bridge/worker.
- Chatwoot reinicio con PID stale y proxy reinicio con capabilities.
- Caída de DB/Redis/modelo y semántica correcta de health/readiness.
- Reconciliación de producto eliminado, stock cambiado y precio expirado.
- Activepieces: ID real, estado de ejecución y rechazo de ruta no allowlisted.

## Datos y escalabilidad

- Import 10.000 filas con límites CPU/RAM, rollback, duplicados en DB y batch performance.
- RAG con corpus grande, calidad top-k, latencia, N+1, dimensión y migración de modelo.
- Pool de DB, agotamiento de conexiones y múltiples réplicas Bridge.
- Retención/limpieza de auditoría, idempotencia, uploads y reservas expiradas.
- Aislamiento con dos proyectos/volúmenes/secretos ficticios y prueba negativa cruzada.

## Frontend/UX

- Unit/component tests de login, cambio de contraseña, expiración 401, error y carga.
- E2E de dashboard/aprobación y cada enlace; hoy varios anchors no tienen sección.
- Escritorio, 1366×768, tablet y móvil; light/dark; zoom 200 %.
- Axe/WCAG: contraste, foco, teclado, labels, tabla y reduced motion.
- Traducciones: evitar strings hardcoded, idioma incompleto y claves i18n muertas.
- Visual regression con datos claramente demo.

## Operación y ciclo de vida

- Provision Linux/Windows desde cero, dominio inválido, puerto ocupado y permisos de ficheros.
- Update compatible/incompatible, migración fallida, rollback automático y actualización simultánea de dos clientes.
- Alertas para chat sin respuesta, worker, DB lenta, backup, disco, certificado y coste.
- Exportación y eliminación segura por cliente.

## Estado y bloqueos

Los tests locales pueden añadirse ya. Sandbox/E2E/DR/Playwright están BLOCKED por credenciales, fallos de red/proxy/Chatwoot y RAM > 90 %. No deben sustituirse por mocks para declarar éxito.
