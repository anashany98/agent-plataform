# Changelog

Todos los cambios relevantes de la remediación se documentan aquí. El proyecto adopta SemVer cuando exista una primera candidata reproducible.

## [Unreleased]

### Added

- Resiliencia de integraciones (D-021): circuit breakers por proveedor (`chatwoot`, `ghl`, `prestashop`, `activepieces`), outbox durable con enqueue idempotente, claim CAS, backoff determinista y dead-letter queue, endpoints `GET /outbox`, `POST /outbox/process` y `POST /outbox/{id}/retry` con roles, métricas de outbox/breakers y migración aditiva `0004` (`3733bad`).
- Executor de herramientas deny-by-default (`ToolExecutor`, `/agents/tools/invoke`, `GET /agents/{id}/tools`): allowlist estricta por agente contra un catálogo cerrado, validación de argumentos, herramientas financieras prohibidas para agentes y auditoría de cada decisión (`4d97449`, D-012).
- Prompt operativo raíz en `agents.md`.
- Repositorio Git local y rama `production-remediation`.
- Punto de recuperación pre-remediación `ed77056`.
- Registros autoritativos `TASKS.md`, `STATUS.md`, `DECISIONS.md` y `BLOCKERS.md`.
- Baseline, plan de remediación, readiness y evidencia persistente en `docs/`.
- Registro de 32 defectos, registro de riesgos y evidencia reproducible de Fase 1.
- Diecinueve tests rojos de regresión para aislamiento, demo, confirmación, comercio, migración, integraciones y seguridad.
- Migración `0002` tenant-safe, contexto obligatorio de instalación y 12 relaciones compuestas diferibles.
- Verificadores PostgreSQL efímeros para concurrencia P0, adopción histórica y downgrade/reupgrade seguro.
- Contratos de regresión para demo, confirmación, PrestaShop, stock, aislamiento y falsos positivos del verificador.
- Registro ampliado a 37 defectos tras la revisión adversarial: 7 verificados y 30 abiertos.

### Changed

- La captura de leads GHL ya no se pierde ante averías del proveedor: el webhook comercial completa la respuesta y encola el efecto externo en el outbox con checkpoints durables; la recuperación llega vía `POST /outbox/process` sin duplicar contactos ni oportunidades (`3733bad`, D-021).
- El propietario aprobó la Ruta A (candidata core con limitaciones documentadas) y la parada del stack antiguo, ejecutada el 2026-08-03: compose projects `agent-platform`, `agent-piloto-rc1` y `agent-cliente-demo-es-staging` detenidos con volúmenes intactos; puerto 9000 liberado.
- El estado comercial queda fijado en `NOT PRODUCTION READY — CRITICAL RISK` hasta superar todos los gates.
- Los resultados históricos se tratan como evidencia previa, no como verificación actual.
- La Fase 0 queda cerrada con baseline de host/Git/Docker, inventario, dependencias, propiedad de datos y 30 criterios de readiness bloqueados.
- La Fase 1 contrasta 30 defectos heredados y añade D-031/D-032 sin aplicar todavía correcciones de producción.
- Los seis P0 reproducidos quedan verificados en `de236e9`; la Fase 2 continúa con 25 P1 y 5 P2 abiertos.
- Pricing usa autoridad fiscal/variantes/scopes PrestaShop, precedencia compatible o fail-closed, `Decimal` y umbral de envío por presupuesto.
- El catálogo acepta únicamente orígenes de producción confiables; demo y orígenes desconocidos fallan cerrados.

### Fixed

- El cierre de `installation_scope` restaura el ámbito anterior aunque el cleanup se ejecute en un contexto distinto (cierre de dependencias generador tras un error de petición); los errores esperados ya no se convierten en 500 (`3733bad`).
- El outbox cuenta los intentos correctamente al agotar reintentos y los checkpoints del dispatcher GHL se persisten con diccionarios nuevos para que SQLAlchemy detecte cada actualización JSON (`3733bad`).
- Harness de tests hermético (D-032): los unit tests de guards usan valores production-like explícitos; el corpus combinado `pytest tests bridge-api/tests` pasa 159/159 en cualquier orden de colección y sin entorno del operador (`4afd0c7`).
- Confirmación comercial exacta con token HMAC de 128 bits almacenado como SHA-256, caducidad, actor firmado y replay idempotente.
- Reservas locales con TTL y transiciones atómicas de release/cancel/expire; stock externo no se confirma sin autoridad transaccional.
- Downgrades destructivos sustituidos por migraciones explícitas, compatibles y no destructivas.
- Aislamiento ORM de 14 modelos tenant-owned, incluida identidad de sesión al cambiar de instalación.

### Security

- Los agentes ya no pueden ejecutar herramientas fuera de su allowlist; la inyección de instrucciones por `/agents/run` no ejecuta herramientas, los argumentos no declarados (p. ej. `custom_vat_rate`) se rechazan y los roles viewer no pueden invocar (`4d97449`).
- Se comprobó que `.env` permanece ignorado por Git.
- El escaneo de patrones de secretos previo al recovery commit no detectó coincidencias de alta señal en código propio.
- `.env` continúa ignorado/no trazado y el escaneo P0 no detectó patrones de secreto de alta señal.
- El verificador rechaza bases no efímeras ligadas al run, no usa `assert` y elimina todos sus datos sintéticos incluso bajo `python -O`.
