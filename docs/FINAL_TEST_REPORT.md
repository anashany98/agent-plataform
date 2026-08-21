# Borrador — informe final de pruebas

> **DRAFT / EVIDENCIA FINAL PENDING.** Resumen actual en [TEST_REPORT.md](TEST_REPORT.md).

## Identidad

| Campo | Valor |
|---|---|
| Versión/commit | PENDING |
| Imágenes/IDs | PENDING |
| Perfil/Compose project | `production` / PENDING |
| Host y recursos | PENDING |
| Dataset/checksum | PENDING |
| Inicio/fin UTC | PENDING |

## Gates automatizados

| Suite | Resultado provisional | Resultado candidata | Evidencia |
|---|---|---|---|
| Backend | 384 passed, 9 skipped | PENDING | |
| Skips clasificados con `-rs` | 9 actuales | PENDING | |
| PostgreSQL/migraciones | head `0013` | PENDING | |
| Quality | 0 / 0 / 128 ≤ 243 | PENDING | |
| Portal | 25/25 | PENDING | |
| Typecheck/format/build | PASS | PENDING | |
| npm/pip audit | 0 | PENDING | |
| Infra verifiers | PASS | PENDING | |

## E2E candidata

| Área | Positivo | RBAC negativo | Tenant B | Retry/CAS | Restart/degradación | Estado |
|---|---|---|---|---|---|---|
| Auth/usuarios | | | | | | PENDING |
| Clientes/catálogo/leads | | | | | | PENDING |
| Quotes/orders/invoices | | | | | | PENDING |
| Aprobaciones | | | | | | PENDING |
| Agentes/tools | | | | | | PENDING |
| RAG/OCR | | | | | | PENDING |
| Wiki/SEO/landing | | | | | | PENDING |
| Tareas/workflows/outbox | | | | | | PENDING |
| Imports/lifecycle | | | | | | PENDING |
| Health/metrics/Portal | | | | | | PENDING |

## Operación y DR

| Prueba | Resultado | RPO/RTO | Evidencia |
|---|---|---|---|
| Backup integral formato 4 | PENDING | | |
| Restore destino vacío | PENDING | | |
| Update | PENDING | | |
| Rollback app+datos | PENDING | | |
| Carga/soak | PENDING | | |
| Alert delivery | PENDING | | |

## Defectos

| ID | Severidad | Descripción | Estado/waiver |
|---|---|---|---|
| PENDING | | | |

## Veredicto QA

**PENDING.** No firmar mientras un gate crítico esté vacío o se haya ejecutado contra una imagen/commit distinto.
