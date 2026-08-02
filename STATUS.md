# Estado autoritativo del proyecto

**Fecha:** 2026-08-02
**Rama:** `production-remediation`
**Recovery commit:** `ed77056`
**Fase activa:** Fase 1 — reproducción y registro de defectos
**Decisión:** **NOT PRODUCTION READY — CRITICAL RISK**

## Estado verificable

- El workspace fue entregado sin `.git`; se inicializó un repositorio local y se creó un punto de recuperación antes de la remediación.
- Compose declara 14 servicios, 3 redes y 9 volúmenes; la configuración sintáctica se valida.
- Todos los contenedores del proyecto están detenidos. Los volúmenes permanecen intactos.
- El host tiene 31,46 GiB de RAM y estaba al 87,7 % de uso en la captura de baseline; no se iniciará build/full stack hasta disponer de margen seguro.
- La auditoría previa del 2026-08-02 registró 5 defectos P0, 21 P1 y 4 P2; la Fase 1 los reproducirá de nuevo antes de corregirlos.
- La última suite backend registrada obtuvo 31 tests aprobados y 67 % de cobertura, pero usa SQLite, demo, mocks/stubs y no valida el producto end-to-end.
- El build del portal fue reproducido anteriormente; la UX dinámica permanece sin validar.

## Stop-ship abiertos

1. Datos demo pueden entrar en respuestas y operaciones comerciales.
2. Una negación puede confirmar una operación por coincidencia de substring.
3. Precio/variantes/impuestos no usan correctamente la autoridad comercial.
4. Stock y reservas divergen de PrestaShop y carecen de ciclo de vida completo.
5. La migración incluye un downgrade destructivo mediante `drop_all`.

## Fases

| Fase | Estado | Evidencia o bloqueo |
|---|---|---|
| 0 — Baseline | VERIFIED | Cuatro documentos completos; topología, estados, enlaces y Compose contrastados sin arrancar servicios |
| 1 — Reproducción | IN PROGRESS | Tests rojos y registro actual de P0/P1 |
| 2 — P0/P1 | BLOCKED | Requiere reproducciones rojas y causa raíz confirmada |
| 3–29 | BLOCKED | Orden obligatorio; dependen de P0/P1 y core estable |
| Release | BLOCKED | No se cumplen gates de producción |

## Fuente de verdad

- Readiness: `docs/PRODUCTION_READINESS.md`.
- Trabajo: `TASKS.md`.
- Bloqueos: `BLOCKERS.md`.
- Evidencia: `docs/TEST_EVIDENCE.md` y `docs/baseline/`.
- Auditoría de origen: `docs/PROJECT_TECHNICAL_AUDIT.md`.
