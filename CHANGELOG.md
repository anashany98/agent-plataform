# Changelog

Todos los cambios relevantes de la remediación se documentan aquí. El proyecto adopta SemVer cuando exista una primera candidata reproducible.

## [Unreleased]

### Added

- Chat sin Chatwoot (Ruta A) + E2E (`c2f4b84`): el webhook de chat degrada el reply/efectos de Chatwoot a un canal interno auditado cuando `CHATWOOT_API_TOKEN` no está configurado, y el core completa chat→lead→presupuesto sin dependencias externas; `scripts/e2e_core_chat_to_quote.py` lo verifica en vivo (webhook firmado HMAC → `quote_created` con total determinista 136,00 y token `CONFIRMAR <TOKEN>`); `ChatwootAdapter.api_token` pasa a propiedad (settings o valor fijado).
- Infra runtime verificada (D-008/D-025): proxy nginx con `cap_add` CHOWN/SETGID/SETUID (workers estables sin `setuid EPERM`), upstreams opcionales chatwoot/activepieces con resolución perezosa (`resolver`+variable) para que el perfil core arranque sin ellos (502 graceful), y límites `deploy.resources` (CPU/memoria/pids) por servicio; perfil core levantado y smoke 200 por el puerto 9000.
- Backup/restore/rollback verificables por instalación (D-015/D-016): `app/services/backup.py` con `create_backup` (manifiesto con conteos+sha256 por tabla), `restore_backup` a motor vacío, `verify_backup` (compara conteos y checksums) y `rollback_installation` (restaura datos de una instalación a un punto conocido, independiente del resto); restauración REAL verificada en SQLite y PostgreSQL efímero (opt-in `RUN_POSTGRES_BACKUP=1`, contenedor pgvector, dos BDs, extension vector); 4 evals (`6b34200`).
- Agentes/IA FlowWink sin Supabase, lote 2 (D-012): `app/services/agent_ai.py::docs_chat` (port de `docs-chat`) con búsqueda RAG y ACL por rol, abstención sin evidencia, citas verificables y respuesta extractiva honesta (`provider="extractive"`) cuando no hay LLM real (B-006); endpoint `/agents/docs-chat` con roles; 3 evals; `agent_ai.py` en zona limpia del gate D-030 (`59558a1`).
- Automatizaciones FlowWink sin Supabase, lote 1 (D-012): `app/services/automations.py` con router de email de proveedor local (sin red), `quote-expiry-reminders` idempotente por ventana, `dunning-processor` (solo notifica y marca `overdue`, sin mutar importes), `generate-invoice-pdf` determinista de solo lectura, `send-webhook` firmado HMAC sobre circuit breaker y sweep agregado pull; endpoints `/automations/sweep` y `/automations/invoices/{id}/pdf` con roles; 7 evals; `automations.py` en zona limpia del gate D-030 (`bf647cf`).
- Quality gates D-030: `scripts/quality_gates.py` con tres puertas (`ruff-hard` E9,F sobre todo el código propio, `ruff-clean-zone` reglas completas sobre módulos nuevos y tests, `ruff-ratchet` con trinquete sobre el baseline visible de `scripts/quality_baseline.json`), opciones `--with-tests`/`--with-portal`/`--update-baseline` y 6 evals de regresión (`ca73a6c`).
- Portal con secciones reales y tests de componentes (D-026/D-027): la navegación deja de prometer módulos fantasma — los cinco anchors rotos (catálogo, documentos, agentes, automatizaciones, usuarios) apuntan a secciones renderizadas con datos reales (`GET /tools/products`, nuevo `GET /rag/documents`, `GET /agents`, `GET /users`) y estado explícito de Activepieces con nota de alcance Ruta A; estados vacío/error por sección; i18n recortado a etiquetas reales; runner vitest + testing-library + vitest-axe con 5 evals (accesibilidad axe incluida); endpoint `GET /rag/documents` sin rutas de disco ni contenido (`33d77c1`).
- Ciclo de vida de datos por instalación (D-029): `LifecycleService` con export JSON portable (clientes, catálogo, presupuestos, pedidos, facturas, conversaciones, aprobaciones, RAG, idempotencia y outbox; nunca users ni AuditLog), erase con retención configurable e inmediata, `process_due_erases` para borrados vencidos y legal hold que bloquea cualquier erase; borrado en orden FK con eliminación de archivos RAG; modelo `InstallationLifecycle` + migración aditiva `0005`; endpoints `/lifecycle/{status,export,erase,legal-hold,process-due-erases}` con `ADMIN_ROLES`; auditoría `lifecycle.export/erase/erase_scheduled/erase_skipped/legal_hold` (`ff0eed8`).
- Observabilidad D-028: middleware FastAPI con logs JSON correlacionados (correlation_id, request_id, tenant_id, user_id, route, method, status, latency_ms), contextvars por proceso con restauración robusta, helpers `log_event`/`record_metric` con redacción determinista por clave y valor, métricas Prometheus para HTTP/outbox/breaker/RAG/alertas y reglas in-memory `circuit_breaker_open`/`outbox_dead_letter_growth`/`rag_abstention_rate`/`dlp_findings` integradas en `/metrics` (`af53b8b`).
- Auditoría de dependencias D-017: `scripts/audit_dependencies.py` ejecuta `pip-audit` y `npm audit --omit=dev` y falla si high/critical >0; tests anti-regresión de rangos de Pillow, pypdf y Vite (`7fb4f45`).
- Clasificación, DLP y defensa anti prompt injection para RAG (D-020): niveles `public`/`internal`/`confidential`/`restricted` con ACL deny-by-default (legado sin clasificación conserva ACL estricta); DLP determinista en ingesta (DNI/NIE con letra, tarjeta con Luhn, IBAN ES mod-97, JWT, AWS, claves `sk_live`, claves privadas) que eleva la clasificación a `confidential` sin persistir valores; redacción de secretos en respuesta y citas; bloqueo de consultas con patrones de inyección y marcado `trusted=false` del contenido recuperado (`0541650`).
- Reconciliación GHL previa al efecto (D-010): `find_opportunity_by_reference` (custom field `external_reference`) y `find_note_by_body` en el adaptador, integradas en el dispatcher del outbox y en `/integrations/ghl/leads`; paginación acotada hasta EOF con fallo cerrado ante listados anómalos, DLQ directa para leads sin referencia externa, checkpoint `reconciled` y auditoría `ghl_lead_reconciled` (`ce2723c`).
- Recuperación de crash ambiguo en el webhook comercial (D-035): checkpoint del resultado tras cada efecto externo visible y resume en takeover (`_resume_webhook_from_checkpoint`) que completa desde un checkpoint de éxito sin repetir respuestas ni presupuestos; auditoría `webhook_checkpoint_resume` (`5a3edf8`).
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

- La deuda de calidad sin control (D-030): B008 excluido globalmente (patrón `Depends()` de FastAPI, consenso del bloque P1), deuda de estilo en tests legacy corregida (E402 con noqa justificado en `conftest.py`, statements compuestos separados en `test_hardening.py`) y la deuda restante (213 hallazgos) queda documentada por regla en un baseline con trinquete que prohíbe su crecimiento (`ca73a6c`).
- Los claims de documentación contradictorios (D-026): README reescrito contra la fuente autoritativa `docs/PRODUCTION_READINESS.md` y banners SUPERSEDED en `REMEDIATION_REPORT.md`, `MASTER_PLATFORM_REPORT.md`, `FINAL_REPORT.md` y `COMMERCIAL_READINESS_REPORT.md`; la navegación del portal ya no promete módulos sin renderizar (D-027) (`33d77c1`).
- La ausencia de ciclo de vida de datos: ahora cada instalación puede exportar sus datos en formato portable y solicitar el borrado con retención configurable; el legal hold bloquea cualquier erase y queda auditado; los archivos RAG se eliminan del disco dentro del directorio de subidas; el AuditLog y los usuarios sobreviven al borrado operativo (`ff0eed8`, D-029).
- Los logs sin correlación ni redacción: cada petición queda trazada con correlation_id/request_id y los secretos (password, tokens, claves, tarjetas, claves privadas) se redactan antes de emitirse; los imports muertos del middleware de observabilidad se limpiaron en `ff0eed8` (`af53b8b`, D-028).
- Dependencias vulnerables: Pillow fijado en 12.x (cierra 49 CVEs en 10.x/11.x), pypdf en 6.x (cierra CVE de 5.9) y Vite subido a ^7 (esbuild path traversal cerrado). `pip-audit` y `npm audit --omit=dev` reportan 0 vulnerabilidades (`7fb4f45`, D-017).
- La fuga de secretos por DLP evadible y la falta de clasificación RAG: ahora los secretos detectados (DNI, tarjeta, IBAN, JWT, claves) elevan la clasificación del documento a `confidential` y se redactan en respuesta y citas; las consultas que intentan manipular las instrucciones del sistema se rechazan; el contenido recuperado se marca como no confiable (`0541650`, D-020).
- La microventana efecto→checkpoint de GHL (residual de D-035) ya no duplica oportunidades ni notas: como GHL no acepta claves de idempotencia, cada creación se reconcilia antes contra el proveedor y se reutiliza el efecto existente; una búsqueda de reconciliación fallida falla cerrada y nunca se crea a ciegas (`ce2723c`, D-010).
- Un crash del worker entre el efecto externo y el cierre de idempotencia ya no duplica efectos en la redelivery: el takeover detecta el checkpoint de éxito y completa sin reenviar la respuesta ni recrear el presupuesto; la deduplicación por `source_message_id` protege los reintentos sin checkpoint (`5a3edf8`, D-035).
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
