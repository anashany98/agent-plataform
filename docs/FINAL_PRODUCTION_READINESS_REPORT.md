# Borrador — informe final de preparación para producción

> **DRAFT / NO APROBADO.** Este archivo se completará únicamente con evidencia de la candidata inmutable. Hasta entonces, la fuente autoritativa es [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).

## Decisión vigente

> **NOT PRODUCTION READY — REMEDIATION INCOMPLETE**

No cambiar esta frase por una decisión favorable mientras falten candidata, escaneo de imágenes, E2E final, restore/rollback integral o carga/soak.

## Identidad de candidata

| Campo | Valor |
|---|---|
| Versión | PENDING (`0.9.1-<sha12>` esperado) |
| Tag Git | PENDING |
| Commit SHA completo | PENDING |
| Estado del checkout | PENDING — debe ser limpio |
| Fecha/hora UTC de corte | PENDING |
| Release manifest/checksum | PENDING |
| Perfil | `production` core |
| Instalación de prueba | PENDING, sin datos reales |

## Evidencia ya aceptada

| Área | Resultado |
|---|---|
| Backend | 384 passed, 9 skipped |
| Quality | hard 0, clean 0, ratchet 128 ≤ 243 |
| PostgreSQL | Alembic head `0013` |
| Portal | 25/25 + typecheck/format/build/audit PASS |
| Dependencias | npm/pip audit 0 en la ejecución reportada |
| Infra | perfiles, preflight, red, proxy, backup-format y vendor pins PASS |
| Redis core | 7.2.14 Alpine 3.21 BSD-3, runtime PASS, Trivy 0 HIGH/CRITICAL |
| Visual base | login 1280/375/320; Nginx UID 101/read-only 200/headers |

Esta evidencia corresponde al árbol actual y debe repetirse o vincularse de forma inequívoca al commit final.

## Gates finales

| Gate | Estado | Referencia de evidencia |
|---|---|---|
| Checkout/tag/manifest inmutable | PENDING | |
| Build reproducible Bridge/Portal | PENDING | |
| Labels/version/commit coherentes | PENDING | |
| Trivy de imágenes finales | PARTIAL | Redis 7.2.14 PASS; resto PENDING |
| SBOM y checksums | PENDING | |
| Secret scan tree/historia/bundle/capas | PENDING | |
| Stack production TLS limpio, 6/6 | PENDING | |
| E2E todos los módulos/roles | PENDING | |
| Aislamiento A/B runtime | PENDING | |
| Portal visual final | PENDING | |
| Backup + restore a destino vacío | PENDING | |
| Update + rollback | PENDING | |
| Carga, soak y degradación | PENDING | |
| Alert delivery/guardia | PENDING | |
| Licencia/notices finales | PENDING | |

## Alcance y limitaciones que deben figurar en la decisión

- solo perfil core sin vendors ni egress;
- SEO estático sobre HTML suministrado: sin crawler/fetch/publicación;
- wiki/landing con aprobación y publicación local únicamente;
- email en spool local: `accepted=false`, sin entrega;
- facturas como flujo interno, no emisión fiscal automática;
- LLM generativo `none`; RAG `local_tfidf`;
- Portal con JWT en `sessionStorage`, sin MFA/SSO;
- `full`, Chatwoot, FlowWink, Activepieces, PrestaShop y GHL no certificados.

## Firma de decisión

| Rol | Nombre | Decisión/fecha |
|---|---|---|
| Release owner | PENDING | |
| QA | PENDING | |
| Security | PENDING | |
| SRE/Operations | PENDING | |
| Legal/Privacy | PENDING | |
| Product owner | PENDING | |
| Cliente/UAT | PENDING | |

La decisión final debe ser exactamente una de las cuatro permitidas en `agents.md` y coincidir con `PRODUCTION_READINESS.md`.
