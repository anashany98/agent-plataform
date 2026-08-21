# Informe de pruebas

**Corte:** 2026-08-15  
**Árbol:** rama `production-remediation`, cambios compartidos aún sin candidata inmutable  
**Resultado documental:** suites herméticas y verificadores parciales verdes; certificación release incompleta.

## Resumen aceptado

| Gate | Resultado | Estado | Alcance que prueba |
|---|---:|---|---|
| Backend combinado | 384 passed, 9 skipped | PASS | Dominio, seguridad, migraciones e infraestructura hermética del árbol actual |
| PostgreSQL/Alembic | head `0013` | PASS | Cadena y contratos de migración en PostgreSQL |
| Quality gates | hard 0; clean 0; ratchet 128 ≤ 243 | PASS | Errores severos, zona limpia y no crecimiento de deuda Ruff |
| Portal Vitest | 25/25 | PASS | Componentes, API client, RBAC y módulos UI cubiertos |
| Portal typecheck/format/build | sin errores | PASS | Tipado, formato y bundle del árbol actual |
| Dependencias | `npm audit` 0; `pip-audit` 0 | PASS | Vulnerabilidades conocidas del lock en la ejecución reportada |
| Infra/perfiles | verifier PASS | PASS | Forma de perfiles core/full/production |
| Preflight | verifier PASS | PASS | Reglas de configuración segura y SemVer |
| Red/proxy | verifiers PASS | PASS | Contrato de redes, proxy y aislamiento esperado |
| Backup formato 4 | verifier PASS | PASS | Cifrado, HMAC, checksums, validación y rechazo de artefactos manipulados |
| Vendor pins | verifier PASS | PASS | Commits/digests declarados no derivan silenciosamente |
| Redis core | 7.2.14 runtime; Trivy 0 HIGH/CRITICAL | PASS | Imagen externa concreta fijada por digest; no cubre el resto del set |
| Portal visual base | login 1280/375/320; Nginx real UID 101/read-only con 200/headers | PASS parcial | Login responsive y endurecimiento del contenedor |

Estos resultados no certifican las imágenes finales. Los números sustituyen los resúmenes históricos de `docs/TEST_EVIDENCE.md`; ese archivo conserva una cronología útil, no el estado vigente.

## Lectura de los skips

El corpus contiene nueve skips asociados a condiciones opt-in o entorno: pruebas live de catálogo/PrestaShop, backup PostgreSQL opt-in, ejecución Linux/Bash y auditorías dependientes del runtime correcto. El release owner debe capturar el listado exacto mediante `pytest -rs` en el mismo job de la candidata y clasificar cada skip como:

- no aplicable al perfil core, con justificación;
- ejecutado en un job específico;
- bloqueo de promoción.

No se admite ocultar un test crítico como skip por ausencia de credenciales o runtime cuando esa capacidad se promociona.

## Cobertura funcional observada

La suite actual incluye pruebas de autenticación/RBAC, tenancy, idempotencia, concurrencia/CAS, cálculo, comercio, approvals, outbox, RAG, seguridad de uploads, providers locales, lifecycle, agentes/tools, wiki, SEO, landing, tareas, imports, migraciones y verificadores operativos. El Portal cubre el cliente API, expiración de sesión, accesibilidad/componentes y módulos de producción.

No se publica un porcentaje de cobertura actual porque no se ha adjuntado un reporte de coverage correspondiente exactamente a los 384 tests. Las cifras históricas (por ejemplo 67 %) son **SUPERSEDED** y no deben reutilizarse.

## Gates pendientes

| Gate final | Estado | Evidencia exigida |
|---|---|---|
| Checkout/tag/manifest inmutables | PENDING | SHA limpio, SemVer, checksums, manifest y labels coincidentes |
| Build reproducible de Bridge/Portal | PENDING | build sin caché desde checkout limpio y comparación de artefactos |
| Escaneo de imágenes restante | PENDING | Redis ya PASS; falta Trivy del resto de imágenes finales, policy y excepciones firmadas |
| SBOM final | PENDING | SBOM por imagen y bundle, coherente con manifest |
| Arranque production TLS desde cero | PENDING | 6 servicios healthy/ready, sin volúmenes previos, logs limpios |
| E2E API+Portal de módulos/roles | PENDING | matriz de positivos/negativos sobre la candidata |
| Aislamiento A/B runtime | PENDING | tokens, recursos, logs, uploads, spool y backups cruzados rechazados |
| Restore integral | PENDING | destino vacío, datos/archivos/env/manifest, checks funcionales y RPO/RTO |
| Update y rollback | PENDING | ensayo con safety backup e identidad exacta de imágenes |
| Carga/soak/degradación | PENDING | p50/p95/p99, error rate, recursos, restart y caída Redis/DB |
| Visual final | PENDING | todos los módulos y roles, desktop/móvil, candidata desplegada |
| Secret scan final | PENDING | working tree, historia, bundle, capas de imagen y logs |

## Matriz E2E final requerida

Por cada módulo core: caso nominal, vacío, validación, rol permitido, rol denegado, instalación B, retry idéntico, retry conflictivo, `If-Match` obsoleto si aplica, restart y dependencia degradada. Deben recorrerse al menos auth/usuarios, clientes, catálogo, leads, presupuestos, pedidos, facturas, approvals, agentes, RAG, wiki, SEO, landing, tareas, imports, lifecycle, outbox y dashboards.

Para funcionalidades públicas, verificar que un borrador nunca sea visible y que una edición no sustituya la revisión publicada. Para email, confirmar explícitamente `accepted=false` y archivo de spool, sin declarar entrega. Para SEO, demostrar ausencia de fetch/publicación externa.

## Decisión

Los gates ejecutados son una evidencia sólida del árbol actual, pero el informe permanece **INCOMPLETE FOR RELEASE**. La decisión exacta y autoritativa es la de [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).
