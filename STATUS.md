# Estado autoritativo del proyecto

**Fecha:** 2026-08-02
**Rama:** `production-remediation`
**Recovery commit:** `ed77056`
**Commit P0:** `de236e9`
**Commit P1 de invariantes:** `48051e8`
**Fase activa:** Fase 2 — corrección de P1 (P0 cerrados)
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
- Permanecen 19 P1 y 4 P2 no verificados; no existe candidata de release ni evidencia E2E/live suficiente.
- El build del portal fue reproducido anteriormente; la UX dinámica permanece sin validar.

## Stop-ship abiertos tras el cierre P0

1. Webhooks/GHL ya tienen inbox durable, lease y checkpoints, pero falta reconciliación/outbox ante resultados externos ambiguos y una prueba exhaustiva de fault injection.
2. RAG niega ACL ausentes, pero clasificación, DLP y corpus de prompt injection/exfiltración permanecen abiertos.
3. Egress, proxy y Chatwoot no están verificados en runtime; la asignación de handoff solo está demostrada con contratos locales.
4. Restore, release/rollback, dependencias, observabilidad, recursos y licencias siguen sin gate aprobado.
5. No existe release candidata, build limpio ni E2E crítico completo contra proveedores locales/sandbox autorizados.

## Fases

| Fase | Estado | Evidencia o bloqueo |
|---|---|---|
| 0 — Baseline | VERIFIED | Cuatro documentos completos; topología, estados, enlaces y Compose contrastados sin arrancar servicios |
| 1 — Reproducción | VERIFIED | 19 tests rojos; registros de defectos/riesgos/evidencia; 32 defectos contrastados |
| 2 — P0/P1 | IN PROGRESS | Seis P0 y siete P1 `VERIFIED`; quedan 19 P1 no verificados, varios con remediación parcial |
| 3–29 | BLOCKED | Orden obligatorio; dependen de P0/P1 y core estable |
| Release | BLOCKED | No se cumplen gates de producción |

## Fuente de verdad

- Readiness: `docs/PRODUCTION_READINESS.md`.
- Trabajo: `TASKS.md`.
- Bloqueos: `BLOCKERS.md`.
- Evidencia: `docs/TEST_EVIDENCE.md`, `docs/baseline/` y `docs/remediation/`.
- Auditoría de origen: `docs/PROJECT_TECHNICAL_AUDIT.md`.
