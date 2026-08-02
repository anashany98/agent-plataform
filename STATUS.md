# Estado autoritativo del proyecto

**Fecha:** 2026-08-02
**Rama:** `production-remediation`
**Recovery commit:** `ed77056`
**Fase activa:** Fase 2 — corrección de P0 y P1
**Decisión:** **NOT PRODUCTION READY — CRITICAL RISK**

## Estado verificable

- El workspace fue entregado sin `.git`; se inicializó un repositorio local y se creó un punto de recuperación antes de la remediación.
- Compose declara 14 servicios, 3 redes y 9 volúmenes; la configuración sintáctica se valida.
- Todos los contenedores del proyecto están detenidos. Los volúmenes permanecen intactos.
- El host tiene 31,46 GiB de RAM y estaba al 87,7 % de uso en la captura de baseline; no se iniciará build/full stack hasta disponer de margen seguro.
- La Fase 1 contrastó los 30 defectos heredados y añadió dos: aislamiento explícito ausente y harness no hermético. Permanecen abiertos 6 P0, 21 P1 y 5 P2.
- La suite backend heredada vuelve a dar 31 tests aprobados al fijar el host sintético, pero usa SQLite, demo, mocks/stubs y no valida el producto end-to-end.
- La suite nueva contiene 19 tests rojos reproducibles para P0/P1; son evidencia previa a la corrección, no una suite verde.
- El build del portal fue reproducido anteriormente; la UX dinámica permanece sin validar.

## Stop-ship abiertos

1. Datos demo pueden entrar en respuestas y operaciones comerciales.
2. Una negación puede confirmar una operación por coincidencia de substring.
3. Precio/variantes/impuestos no usan correctamente la autoridad comercial.
4. Stock y reservas divergen de PrestaShop y carecen de ciclo de vida completo.
5. La migración incluye un downgrade destructivo mediante `drop_all`.
6. Doce tablas con datos de cliente carecen de contexto explícito de instalación/tenant/cliente.

## Fases

| Fase | Estado | Evidencia o bloqueo |
|---|---|---|
| 0 — Baseline | VERIFIED | Cuatro documentos completos; topología, estados, enlaces y Compose contrastados sin arrancar servicios |
| 1 — Reproducción | VERIFIED | 19 tests rojos; registros de defectos/riesgos/evidencia; 32 defectos contrastados |
| 2 — P0/P1 | IN PROGRESS | Corregir primero aislamiento, demo, confirmación, pricing/stock y migraciones |
| 3–29 | BLOCKED | Orden obligatorio; dependen de P0/P1 y core estable |
| Release | BLOCKED | No se cumplen gates de producción |

## Fuente de verdad

- Readiness: `docs/PRODUCTION_READINESS.md`.
- Trabajo: `TASKS.md`.
- Bloqueos: `BLOCKERS.md`.
- Evidencia: `docs/TEST_EVIDENCE.md`, `docs/baseline/` y `docs/remediation/`.
- Auditoría de origen: `docs/PROJECT_TECHNICAL_AUDIT.md`.
