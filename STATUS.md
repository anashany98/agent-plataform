# Estado autoritativo del proyecto

**Fecha:** 2026-08-02
**Rama:** `production-remediation`
**Recovery commit:** `ed77056`
**Commit P0:** `de236e9`
**Fase activa:** Fase 2 — corrección de P1 (P0 cerrados)
**Decisión:** **NOT PRODUCTION READY — CRITICAL RISK**

## Estado verificable

- El workspace fue entregado sin `.git`; se inicializó un repositorio local y se creó un punto de recuperación antes de la remediación.
- Compose declara 14 servicios, 3 redes y 9 volúmenes; la configuración sintáctica se valida.
- Todos los contenedores del proyecto están detenidos. Los volúmenes permanecen intactos.
- El host tiene 31,46 GiB de RAM y estaba al 87,7 % de uso en la captura de baseline; no se iniciará build/full stack hasta disponer de margen seguro.
- Los seis P0 reproducidos están corregidos y verificados en `de236e9`: demo, confirmación, pricing/fiscalidad, stock, migraciones y aislamiento por instalación.
- La matriz P0 local pasa 101 pruebas funcionales/aislamiento y 23 pruebas de migración; las reproducciones rojas de Fase 1 se conservan como evidencia histórica previa al fix.
- PostgreSQL 15 efímero verificó clean upgrade, 12 FKs compuestas `DEFERRABLE INITIALLY DEFERRED`, confirmación concurrente, oversell, carreras de release/cancel/expire, ejecución con `python -O`, downgrade/reupgrade con reserva activa y adopción histórica desde `0001`; cada ensayo terminó sin filas ni contenedores residuales.
- La revisión adversarial añadió cinco defectos P1: truncado PrestaShop, exposición de productos no vendibles/precios ocultos, lease inseguro de webhooks, importaciones no idempotentes y un verificador susceptible de falso positivo. Este último quedó verificado en `de236e9`; permanecen 25 P1 y 5 P2 abiertos.
- El build del portal fue reproducido anteriormente; la UX dinámica permanece sin validar.

## Stop-ship abiertos tras el cierre P0

1. Webhooks, GHL e importaciones aún carecen de un modelo completo de inbox/outbox, lease e idempotencia transaccional.
2. RAG mantiene ACL/exfiltración abierta y PrestaShop puede truncar catálogos grandes o exponer productos con precio oculto/no vendibles.
3. Egress, proxy y Chatwoot no están reparados ni verificados en runtime.
4. Restore, release/rollback, dependencias, observabilidad, recursos y licencias siguen sin gate aprobado.
5. No existe release candidata, build limpio ni E2E crítico completo contra proveedores locales/sandbox autorizados.

## Fases

| Fase | Estado | Evidencia o bloqueo |
|---|---|---|
| 0 — Baseline | VERIFIED | Cuatro documentos completos; topología, estados, enlaces y Compose contrastados sin arrancar servicios |
| 1 — Reproducción | VERIFIED | 19 tests rojos; registros de defectos/riesgos/evidencia; 32 defectos contrastados |
| 2 — P0/P1 | IN PROGRESS | Seis P0 `VERIFIED` en `de236e9`; corrección P1 en orden de riesgo |
| 3–29 | BLOCKED | Orden obligatorio; dependen de P0/P1 y core estable |
| Release | BLOCKED | No se cumplen gates de producción |

## Fuente de verdad

- Readiness: `docs/PRODUCTION_READINESS.md`.
- Trabajo: `TASKS.md`.
- Bloqueos: `BLOCKERS.md`.
- Evidencia: `docs/TEST_EVIDENCE.md`, `docs/baseline/` y `docs/remediation/`.
- Auditoría de origen: `docs/PROJECT_TECHNICAL_AUDIT.md`.
