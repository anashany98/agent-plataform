# Borrador — informe final de rendimiento

> **DRAFT / CARGA Y SOAK PENDING.** Plan y límites en [PERFORMANCE_REPORT.md](PERFORMANCE_REPORT.md).

## Identidad

| Campo | Valor |
|---|---|
| Versión/commit/imágenes | PENDING |
| Host/CPU/RAM/disco | PENDING |
| Perfil y límites efectivos | PENDING |
| Herramienta/configuración | PENDING |
| Dataset/checksum | PENDING |
| Duración/concurrencia | PENDING |

## Resultados

| Escenario | RPS | p50 | p95 | p99 | Error inesperado | CPU/RAM pico | Estado |
|---|---:|---:|---:|---:|---:|---|---|
| Lecturas mixtas | | | | | | | PENDING |
| Escrituras idempotentes | | | | | | | PENDING |
| Confirmación concurrente | | | | | | | PENDING |
| RAG ingesta/consulta | | | | | | | PENDING |
| Scheduler/outbox | | | | | | | PENDING |
| Backup bajo carga | | | | | | | PENDING |
| Restart/degradación Redis | | | | | | | PENDING |
| Degradación PostgreSQL | | | | | | | PENDING |
| Soak | | | | | | | PENDING |

## Capacidad y DR

| Métrica | Resultado | Objetivo aprobado | Veredicto |
|---|---|---|---|
| Startup/ready | PENDING | | |
| Backlog máximo/recuperación | PENDING | | |
| Backup RPO/tiempo | PENDING | | |
| Restore RTO | PENDING | | |
| Crecimiento de disco | PENDING | | |
| Reinicios/OOM/fugas | PENDING | 0 no planificados | |

## Veredicto

**PENDING.** No extrapolar microbenchmarks históricos ni resultados del stack dev. Adjuntar series crudas y fijar SLO/capacidad por cliente antes de firma.
