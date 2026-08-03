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
**Fase activa:** Fase 2 — Wave 1 de P1/P2 corregibles sin runtime (P0 cerrados)
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
- El 2026-08-03, con autorización del propietario, se detuvieron los tres compose projects del workspace antiguo (`agent-platform`, `agent-piloto-rc1`, `agent-cliente-demo-es-staging`); volúmenes intactos y puerto 9000 liberado. La memoria de la VM Docker queda pendiente de liberación/medición (B-001 mitigado).
- Permanecen 13 P1 y 3 P2 no verificados; no existe candidata de release ni evidencia E2E/live suficiente.
- El build del portal fue reproducido anteriormente; la UX dinámica permanece sin validar.

## Stop-ship abiertos tras el cierre P0

1. Webhooks/GHL ya tienen inbox durable, lease, checkpoints, recuperación de crash ambiguo tras efecto y reconciliación previa al efecto (D-010 cerrado); queda el fault injection live contra el proveedor real (bloqueado por B-004).
2. RAG ya tiene clasificación, DLP y corpus anti prompt injection verificados en `0541650`; queda el dataset de exfiltración a escala real y el E2E del proveedor RAG real (B-006 bloquea el sandbox).
3. Egress, proxy y Chatwoot no están verificados en runtime; la asignación de handoff solo está demostrada con contratos locales.
4. Restore, release/rollback, observabilidad, recursos y licencias siguen sin gate aprobado; las dependencias están verificadas (`7fb4f45`).
5. No existe release candidata, build limpio ni E2E crítico completo contra proveedores locales/sandbox autorizados.

## Fases

| Fase | Estado | Evidencia o bloqueo |
|---|---|---|
| 0 — Baseline | VERIFIED | Cuatro documentos completos; topología, estados, enlaces y Compose contrastados sin arrancar servicios |
| 1 — Reproducción | VERIFIED | 19 tests rojos; registros de defectos/riesgos/evidencia; 32 defectos contrastados |
| 2 — P0/P1 | IN PROGRESS | Seis P0, trece P1 y dos P2 `VERIFIED`; quedan 13 P1 y 3 P2 no verificados, varios con remediación parcial |
| 3–29 | BLOCKED | Orden obligatorio; dependen de P0/P1 y core estable |
| Release | BLOCKED | No se cumplen gates de producción |

## Fuente de verdad

- Readiness: `docs/PRODUCTION_READINESS.md`.
- Trabajo: `TASKS.md`.
- Bloqueos: `BLOCKERS.md`.
- Evidencia: `docs/TEST_EVIDENCE.md`, `docs/baseline/` y `docs/remediation/`.
- Auditoría de origen: `docs/PROJECT_TECHNICAL_AUDIT.md`.
