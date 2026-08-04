# Estado autoritativo del proyecto

**Fecha:** 2026-08-03
**Rama:** `production-remediation`
**Recovery commit:** `ed77056`
**Commit P0:** `de236e9`
**Commit P1 de invariantes:** `48051e8`
**Commit harness hermético (D-032):** `4afd0c7`
**Commit tool policy (D-012):** `4d97449`
**Commit resiliencia (D-021):** `3733bad`
**Commit crash recovery (D-035):** `5a3edf8`
**Commit reconciliación GHL (D-010):** `ce2723c`
**Commit clasificación/DLP RAG (D-020):** `0541650`
**Commit dependencias (D-017):** `7fb4f45`
**Commit observabilidad (D-028):** `af53b8b`
**Commit lifecycle (D-029):** `ff0eed8`
**Commit portal/docs (D-026/D-027):** `33d77c1`
**Commit quality gates (D-030):** `ca73a6c`
**Commit automatizaciones FlowWink lote 1 (D-012):** `bf647cf`
**Commit Agentes/IA FlowWink lote 2 (D-012):** `59558a1`
**Commit backup/restore/rollback (D-015/D-016):** `6b34200`
**Fase activa:** Fase 3 — extracción de automatizaciones FlowWink sin Supabase (Wave 1 de P1/P2 agotada)
**Ruta aprobada:** Ruta A — candidata core con limitaciones documentadas (`DECISIONS.md` D-007)
**Decisión:** **NOT PRODUCTION READY — CRITICAL RISK**

## Estado verificable

- El workspace fue entregado sin `.git`; se inicializó un repositorio local y se creó un punto de recuperación antes de la remediación.
- Compose declara 14 servicios, 3 redes y 9 volúmenes; la configuración sintáctica se valida.
- Todos los contenedores del proyecto están detenidos. Los volúmenes permanecen intactos.
- El host tiene 31,46 GiB de RAM y estaba al 87,7 % de uso en la captura de baseline; no se iniciará build/full stack hasta disponer de margen seguro.
- Los seis P0 reproducidos están corregidos y verificados en `de236e9`: demo, confirmación, pricing/fiscalidad, stock, migraciones y aislamiento por instalación.
- El corpus backend pasa 159 pruebas y las migraciones herméticas 23; las reproducciones rojas de Fase 1 se conservan como evidencia histórica previa a cada fix.
- PostgreSQL 15 efímero verificó la revisión `0003`, 12 FKs compuestas `DEFERRABLE INITIALLY DEFERRED`, confirmación, aprobación CAS, presupuesto LLM, oversell, carreras de reservas, `python -O`, downgrade/reupgrade y adopción histórica; cada ensayo terminó sin filas ni contenedores residuales.
- `48051e8` cerró seis P1 y un P2: aprobación CAS, Activepieces estricto, coste/presupuesto IA, paginación/visibilidad PrestaShop, importación atómica idempotente y health separado. Sumado al verificador PostgreSQL cerrado en `de236e9`, hay siete P1 verificados; Webhooks/GHL, RAG, resiliencia, perfil seguro y handoff conservan alcance parcial o live pendiente.
- El 2026-08-03 se re-verificó el corpus en vivo: la corrida combinada reproducía 2 fallos por contaminación de entorno (D-032); tras `4afd0c7` el corpus combinado pasa 159/159 en ambos órdenes de colección con entorno limpio. D-032 queda VERIFIED (P2).
- El 2026-08-03 se cerró D-012 con `4d97449`: `ToolExecutor` deny-by-default (`/agents/tools/invoke`), allowlist estricta por agente, argumentos validados, herramientas financieras prohibidas y auditoría; 10 evals nuevos y corpus combinado 169/169.
- El 2026-08-03 se cerró D-021 con `3733bad`: circuit breakers por proveedor en los cuatro adapters HTTP, outbox durable con claim CAS, backoff determinista y DLQ (`OutboxService`, migración `0004`), captura GHL reencolada con checkpoints durables, endpoints `/outbox*` con roles y métricas; 18 evals nuevos y corpus combinado 187/187 en ambos órdenes de colección.
- El 2026-08-03 se cerró D-035 con `5a3edf8`: el webhook checkpointa el resultado tras cada efecto externo visible y el takeover con checkpoint de éxito completa sin repetir efectos (`_resume_webhook_from_checkpoint`); 3 evals de crash/recovery y corpus combinado 190/190 en ambos órdenes de colección. La microventana efecto→checkpoint persiste hasta disponer de claves de idempotencia del proveedor (D-010).
- El 2026-08-03 se cerró D-010 con `ce2723c`: como GHL no acepta claves de idempotencia, la microventana efecto→checkpoint (residual de D-035) se cierra con reconciliación previa al efecto (`find_opportunity_by_reference` por custom field `external_reference` y `find_note_by_body`) en el dispatcher del outbox y en `/integrations/ghl/leads`; una búsqueda fallida falla cerrada, un lead sin referencia va directo a DLQ y cada reconciliación queda auditada (`ghl_lead_reconciled`); 6 evals nuevos y corpus combinado 196/196 en ambos órdenes de colección. Residual: contrato live del endpoint de búsqueda pendiente de sandbox GHL (B-004).
- El 2026-08-03 se cerró D-020 con `0541650`: clasificación public/internal/confidential/restricted con ACL deny-by-default (legado sin clasificación conserva ACL estricta), DLP determinista en ingesta (DNI/NIE con letra, tarjeta con Luhn, IBAN ES mod-97, JWT, AWS, claves sk_live, claves privadas) que eleva la clasificación a confidential sin persistir valores y redacta respuesta y citas, bloqueo de consultas con patrones de inyección y marcado `trusted=false` del contenido recuperado; 10 evals nuevos y corpus combinado 206/206 en ambos órdenes de colección.
- El 2026-08-03 se cerró D-017 con `7fb4f45`: Pillow fijado en 12.x (cierra 49 CVEs en 10.x/11.x), pypdf en 6.x (cierra CVE de 5.9.0), Vite subido a ^7 (esbuild path traversal cerrado); script `scripts/audit_dependencies.py` ejecuta pip-audit + npm audit y falla si high/critical >0; 6 evals nuevos y corpus combinado 212/212 en ambos órdenes de colección.
- El 2026-08-03 se cerró D-028 con `af53b8b`: middleware FastAPI con logs JSON correlacionados (correlation_id/request_id/tenant_id/user_id/route/method/status/latency_ms), contextvars por proceso con restauración robusta, helpers `log_event` y `record_metric` con redacción determinista (password/secret/token/bearer/private_key/JWT/sk_live/tarjeta/clave privada), métricas Prometheus para HTTP/outbox/breaker/RAG/alerts y reglas in-memory (`circuit_breaker_open`, `outbox_dead_letter_growth`, `rag_abstention_rate`, `dlp_findings`) integradas en `/metrics` con `recent` y `evaluated`; 10 evals nuevos y corpus combinado 222/222 en ambos órdenes de colección.
- El 2026-08-03 se cerró D-029 con `ff0eed8`: `LifecycleService` con export JSON portable de datos operativos (sin users ni AuditLog), erase con retención configurable e inmediata, proceso de borrados vencidos y legal hold que bloquea cualquier erase mientras está activo; borrado en orden FK con eliminación de archivos RAG dentro del directorio de subidas; modelo `InstallationLifecycle` + migración aditiva `0005`; endpoints `/lifecycle/*` con `ADMIN_ROLES` y auditoría completa; 6 evals nuevos y corpus combinado 228/228 en ambos órdenes de colección. Residual: revisión legal de la política de retención (B-008).
- El 2026-08-03 se cerraron D-026/D-027 con `33d77c1`: README reescrito contra la fuente autoritativa y banners SUPERSEDED en `REMEDIATION_REPORT`, `MASTER_PLATFORM_REPORT`, `FINAL_REPORT` y `COMMERCIAL_READINESS_REPORT`; la navegación del portal deja de prometer módulos fantasma (cinco anchors rotos) con secciones reales respaldadas por `GET /tools/products`, nuevo `GET /rag/documents`, `GET /agents` y `GET /users`; runner frontend vitest + testing-library + vitest-axe con 5 evals verdes; 1 eval backend nuevo y corpus combinado 229/229. Residual: E2E visual en viewports acordados (Fase 19).
- El 2026-08-03 se cerró D-030 con `ca73a6c`: `scripts/quality_gates.py` con tres puertas (`ruff-hard` E9,F a 0, `ruff-clean-zone` a 0 y `ruff-ratchet` con baseline visible de 213 en `scripts/quality_baseline.json`), B008 excluido globalmente por el patrón `Depends()` de FastAPI, deuda de estilo en tests legacy corregida; 6 evals nuevos y corpus combinado 235/235 en ambos órdenes de colección. Con este cierre la Wave 1 (defectos corregibles sin runtime) queda agotada; los P1 restantes requieren runtime/Docker o decisión del propietario.
- El 2026-08-04, tras la decisión D-012 (propietario rechaza Supabase y selecciona extraer 6 dominios de FlowWink al Bridge), se entregó el lote 1 de automatizaciones con `bf647cf`: `app/services/automations.py` con router de email de proveedor local (sin red), `quote-expiry-reminders` idempotente por ventana, `dunning-processor` que solo notifica y marca `overdue` sin mutar importes, `generate-invoice-pdf` determinista de solo lectura, `send-webhook` firmado HMAC sobre circuit breaker y sweep agregado pull; endpoints `/automations/sweep` y `/automations/invoices/{id}/pdf` con roles. 7 evals nuevos; corpus 242/242; `automations.py` entra en la zona limpia del gate D-030. Esto es funcionalidad nueva (T-015), no cierra defectos: los conteos P0/P1/P2 no cambian.
- El 2026-08-04 se verificaron D-015 y D-016 con `6b34200`: `app/services/backup.py` con `create_backup` (manifiesto con conteos+sha256 por tabla), `restore_backup` a motor vacío y `verify_backup`; **restauración REAL** verificada en SQLite (hermético) y en PostgreSQL efímero (opt-in, contenedor pgvector, dos BDs, extension vector); `rollback_installation` restaura los datos de una instalación a un punto conocido tras una mala release, independiente del resto. 4 evals; corpus 248. Cierra dos P1: quedan 9 abiertos, todos de runtime/bloqueados.
- El 2026-08-04 se entregó el lote 2 de Agentes/IA con `59558a1`: `app/services/agent_ai.py::docs_chat` (port de `docs-chat` de FlowWink) con búsqueda RAG y ACL por rol, abstención sin evidencia, citas verificables y respuesta extractiva honesta cuando no hay proveedor LLM real (B-006); endpoint `/agents/docs-chat` con roles. 3 evals nuevos; corpus 245/245; `agent_ai.py` en zona limpia del gate D-030. Funcionalidad nueva (T-017), no cambia conteos de defectos.
- El 2026-08-03, con autorización del propietario, se detuvieron los tres compose projects del workspace antiguo (`agent-platform`, `agent-piloto-rc1`, `agent-cliente-demo-es-staging`); volúmenes intactos y puerto 9000 liberado. La memoria de la VM Docker queda pendiente de liberación/medición (B-001 mitigado).
- Permanecen 9 P1 y 0 P2 no verificados; no existe candidata de release ni evidencia E2E/live suficiente.
- El build del portal fue reproducido anteriormente; la UX dinámica permanece sin validar.

## Stop-ship abiertos tras el cierre P0

1. Webhooks/GHL ya tienen inbox durable, lease, checkpoints, recuperación de crash ambiguo tras efecto y reconciliación previa al efecto (D-010 cerrado); queda el fault injection live contra el proveedor real (bloqueado por B-004).
2. RAG ya tiene clasificación, DLP y corpus anti prompt injection verificados en `0541650`; queda el dataset de exfiltración a escala real y el E2E del proveedor RAG real (B-006 bloquea el sandbox).
3. Egress, proxy y Chatwoot no están verificados en runtime; la asignación de handoff solo está demostrada con contratos locales.
4. Restore, release/rollback, recursos y licencias siguen sin gate aprobado; dependencias (`7fb4f45`) y observabilidad (`af53b8b`) verificadas.
5. No existe release candidata, build limpio ni E2E crítico completo contra proveedores locales/sandbox autorizados.

## Fases

| Fase | Estado | Evidencia o bloqueo |
|---|---|---|
| 0 — Baseline | VERIFIED | Cuatro documentos completos; topología, estados, enlaces y Compose contrastados sin arrancar servicios |
| 1 — Reproducción | VERIFIED | 19 tests rojos; registros de defectos/riesgos/evidencia; 32 defectos contrastados |
| 2 — P0/P1 | IN PROGRESS | Seis P0, diecisiete P1 y cinco P2 `VERIFIED`; quedan 9 P1 no verificados, todos de runtime/bloqueados (Docker/egress/proxy/puertos/recursos, handoff live, release/perfiles, alcance/legal) |
| 3–29 | BLOCKED | Orden obligatorio; dependen de P0/P1 y core estable |
| Release | BLOCKED | No se cumplen gates de producción |

## Fuente de verdad

- Readiness: `docs/PRODUCTION_READINESS.md`.
- Trabajo: `TASKS.md`.
- Bloqueos: `BLOCKERS.md`.
- Evidencia: `docs/TEST_EVIDENCE.md`, `docs/baseline/` y `docs/remediation/`.
- Auditoría de origen: `docs/PROJECT_TECHNICAL_AUDIT.md`.
