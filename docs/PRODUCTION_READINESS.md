# Estado autoritativo de preparación para producción

**ÚNICA FUENTE AUTORITATIVA.** Cualquier cifra o decisión distinta en otro informe queda subordinada a este documento.

**Corte documental:** 2026-08-15, checkout `production-remediation` con cambios sin integrar.
**Ámbito candidato:** perfil `production` (core propio + TLS), una instancia por cliente, sin vendors ni egress.

## Decisión vigente

> **NOT PRODUCTION READY — REMEDIATION INCOMPLETE**

La implementación y las suites han avanzado de forma sustancial, pero todavía no existe una candidata inmutable que haya superado build, escaneo de imágenes, despliegue TLS aislado, E2E de todos los módulos, restore integral, rollback y prueba de carga. La decisión debe reevaluarse únicamente con evidencia final reproducible.

## Evidencia aceptada hasta este corte

| Área | Resultado | Lectura correcta |
|---|---|---|
| Backend | 373 passed, 11 skipped | Corpus hermético actual; no certifica la imagen desplegada |
| Calidad Python | hard 0, clean 0, ratchet 129 ≤ baseline 243 | Gate estático PASS |
| PostgreSQL/migraciones | Cadena Alembic hasta `0013` verificada | Esquema/migraciones cubiertos; restore integral final PENDING |
| Portal | 27/27, typecheck, formato, build y audit npm PASS | Componentes/build verdes; E2E visual de candidata PENDING |
| Infra | perfiles, preflight, red, proxy, formato backup y pins PASS | Contrato estático/runtime aislado parcial; no release final |
| Redis core | 7.2.14 Alpine 3.21 BSD-3; runtime PASS; Trivy 0 HIGH/CRITICAL | Cierra esta imagen concreta, no el scan del conjunto final |
| Runtime existente | 14/14 healthy en desarrollo | Stale/dev; excluido de la decisión de producción |

`VERIFIED` abajo exige evidencia específica y reproducible. `PARTIAL` significa que existe control probado, pero falta una parte del criterio. `PENDING` impide dar el gate por cerrado.

## Artefactos superseded

> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Los informes Markdown históricos llevan un banner equivalente. Los binarios/HTML existentes `PROJECT_STATUS_AUDIT_2026-08-10.html`, `PROJECT_TECHNICAL_AUDIT.html`, `PROJECT_TECHNICAL_AUDIT.pdf` y `STATUS_REPORT.pdf` corresponden a cortes anteriores y no se han regenerado en esta fase. Se conservan solo como trazabilidad; este documento prevalece.

## Matriz de los 30 criterios

| # | Criterio | Estado | Evidencia actual / condición de cierre |
|---:|---|---|---|
| 1 | Cero defectos P0 abiertos | PENDING | No hay P0 conocido en el corpus actual; falta triage final tras E2E/scan/restore |
| 2 | P1 críticos del núcleo corregidos | PARTIAL | 384/9 y quality PASS; falta ejecutar la candidata completa |
| 3 | Sin mocks en producción | PARTIAL | Preflight rechaza mocks/stubs y perfil production usa proveedores reales locales/`none`; falta inspeccionar imagen final |
| 4 | Sin datos demo visibles | PARTIAL | Arranque production rechaza demo/seed; falta smoke de DB vacía/candidata |
| 5 | Aislamiento entre clientes probado | PARTIAL | `installation_id`, filtros ORM y tests herméticos; falta prueba runtime simultánea A/B y restore cruzado negativo |
| 6 | Confirmaciones seguras | PARTIAL | Token hash/TTL, estados, idempotencia y CAS cubiertos; falta E2E final/concurrencia desplegada |
| 7 | Migraciones no destructivas | VERIFIED | Cadena `0001…0013`, head PostgreSQL y downgrade conservador verificados |
| 8 | Cálculos deterministas | VERIFIED | Servicio servidor con `Decimal`, recálculo y tests de manipulación |
| 9 | Operaciones idempotentes | PARTIAL | Contratos en webhooks, clientes, leads, comercio, imports, publicaciones y workflows; falta E2E multiretry final |
| 10 | Permisos efectivos en backend | PARTIAL | Dependencias RBAC y tests; falta recorrido runtime de todos los roles |
| 11 | Stack production arrancando limpio | PENDING | No se ha arrancado la candidata final con imágenes/manifest definitivos |
| 12 | Servicios esenciales funcionales | PENDING | Contratos de readiness existen; falta smoke contra el stack final |
| 13 | Tests críticos aprobados | VERIFIED | Backend 384/9, Portal 25/25, quality 0/0/128 y verificadores infra PASS |
| 14 | E2E principales aprobados | PENDING | La evidencia histórica no corresponde a la candidata final |
| 15 | Backup restaurado | PENDING | Formato 4 y verificador PASS; restore integral vacío final no ejecutado |
| 16 | Rollback probado | PENDING | Procedimiento disponible; ensayo final de aplicación/datos no ejecutado |
| 17 | Agentes limitados a tools autorizadas | VERIFIED | Registro persistente, allowlist deny-by-default y tests de política |
| 18 | Facturación automática desactivada | VERIFIED | `ENABLE_AUTOMATIC_INVOICE_ISSUANCE=false`, validación de arranque y borrador + aprobación |
| 19 | Publicaciones con aprobación | VERIFIED | Wiki/landing/agentes/tareas usan estado versionado y aprobación; automático bloqueado |
| 20 | RAG aislado y con citas | PARTIAL | TF-IDF local ingesta/recupera/cita y ACL por rol; falta E2E final con corpus malicioso |
| 21 | Logs y métricas operativos | PARTIAL | Logs JSON, correlación, health/readiness y métricas internas; sin backend externo/alert delivery |
| 22 | Sin secretos en repositorio | PENDING | Plantilla/preflight y redacción existen; falta scan final de árbol, historia e imágenes |
| 23 | Licencias revisadas | PARTIAL | Core y licenses locales inventariados; vendors/full y Activepieces requieren revisión legal final |
| 24 | Documentación coherente | PARTIAL | Juego operativo actualizado; falta incorporar resultados finales y renderizar PDF/HTML |
| 25 | Instalación limpia reproducible | PENDING | Locks/digests y preflight existen; falta instalación desde commit limpio |
| 26 | Release versionada | PENDING | Etiquetas OCI/manifest implementados; falta commit, SemVer, manifest y bundle definitivos |
| 27 | Funcional sin PrestaShop ni GHL | PARTIAL | Production core usa local/TF-IDF y no requiere credenciales; falta E2E final |
| 28 | Proveedores externos desacoplados | PARTIAL | Interfaces/adaptadores y core sin egress; `full` no está certificado |
| 29 | Portal probado visualmente | PARTIAL | Login y viewports 1280/375/320 validados sin overflow; falta recorrido visual final de todos los módulos |
| 30 | Límites y alertas configurados | PENDING | Recursos/limits y reglas internas existen; alertas externas y umbrales de capacidad no cerrados |

**Resultado:** 6 `VERIFIED`, 14 `PARTIAL`, 10 `PENDING`. Un `PENDING` crítico en 11, 14, 15, 16, 22, 25 o 26 bloquea promoción.

## Stop-ships actuales

| ID | Bloqueo | Propietario de cierre | Evidencia exigida |
|---|---|---|---|
| SS-01 | Checkout no inmutable | Release | Commit limpio, tag SemVer y checksums |
| SS-02 | Conjunto de imágenes finales no certificado | Release/Security | Redis ya PASS; faltan build con labels OCI, Trivy/SBOM y manifest del resto |
| SS-03 | TLS/DNS/secretos reales ausentes | Operación/cliente | Cert leaf público con SAN, DNS, secrets rotados y preflight release PASS |
| ~~SS-04~~ | ~~E2E final incompleto~~ | ~~QA~~ | **PASS 2026-08-15** — matriz E2E rol × módulo ejecutada sobre el stack candidato (`agent-candidate-0815`): 63 checks (7 roles × 9 endpoints de módulo) con acceso 200/403 exacto a la matriz RBAC declarada por el backend (`READ/OPERATOR/ADMIN_ROLES`), contratos de respuesta verificados (envelope de catálogo, dashboard role-aware con `permissions`), usuarios de prueba creados/desactivados/eliminados y stack devuelto a baseline. Detalle en §Evidencia SS-04. |
| ~~SS-05~~ | ~~Restore/rollback integral sin ensayo final~~ | ~~SRE~~ | **PASS 2026-08-15** — ensayo integral sobre el PostgreSQL real del stack candidato (`agent-candidate-0815`): backup cifrado+HMAC+checksum (10.9 s), restore verificado a destino vacío aislado, RTO restore 25.2 s / rollback 25.1 s, checks funcionales (login, catálogo, wiki pública, alembic 0013) y rollback del safety backup que devuelve el estado exacto previo al restore. Detalle en §Evidencia SS-05. |
| SS-06 | Rendimiento/soak final pendiente | SRE/QA | Carga acotada, restart y degradación Redis/DB |
| SS-07 | Alert delivery externa ausente | Operación | Receptor, routing, prueba de alerta y guardia |

### Evidencia SS-05 — ensayo integral backup/restore/rollback (2026-08-15)

Ensayo completo ejecutado contra el **PostgreSQL real del stack candidato**
(`agent-candidate-0815`, esquema Alembic `0013`, instalación
`candidate-0815`) usando la herramienta de SRE del repositorio
(`scripts/backup-restore-integral.py`, formato 4 cifrado AES-256-CBC +
HMAC-SHA256 + SHA256SUMS externo).

| Fase | Comando / acción | Resultado | Duración |
|---|---|---|---|
| Marcadores pre-backup | Insert SQL `ss05-cust`, `SS05-MARKER-001`, `ss05-wiki` | 1 por tabla | — |
| Backup | `backup candidate-0815 --profile core` | `restore=PASS`; artefacto `candidate-0815-20260815T142452Z-27d46d8c.tar.gz.enc` (+ `.hmac`, `.sha256`) | **10.9 s** |
| Escritura post-backup | Insert SQL `SS05-POST-BACKUP` | Presente en origen | 14:25:26Z |
| Restore | `restore candidate-0815 <artefacto>` (verify a destino vacío aislado + safety backup + in-place) | `restore=PASS`; safety `candidate-0815-20260815T142541Z-1d27d97f.tar.gz.enc` | **RTO 25.2 s** (14:25:39→14:26:04Z) |
| Checks funcionales | `alembic_version=0013`; conteos; login admin; `GET /catalog/products?query=SS05`; wiki pública | 200 OK; marcador pre-backup presente; `SS05-POST-BACKUP` **ausente** (RPO) | — |
| Rollback | `restore candidate-0815 <safety backup>` | `restore=PASS`; estado previo al restore recuperado: `SS05-POST-BACKUP` vuelve a estar presente, `products=3` | **25.1 s** (14:26:24→14:26:49Z) |
| Limpieza | Delete SQL de marcadores | Stack en estado base (products=1, customers=1, wiki=1); 5/5 healthy | — |

**RPO medido:** el punto de recuperación coincide con el snapshot del backup
(los marcadores pre-backup sobreviven y el marcador post-backup se pierde en
el restore, como exige el modelo de punto-en-el-tiempo).

**RTO medido (stack real):** restore a salud completa **25.2 s**; rollback
vía safety backup **25.1 s**. El RTO se mide sobre un catálogo pequeño
(~200 filas); el escalado con volumen de datos queda cubierto por SS-06.

### Evidencia SS-04 — matriz E2E rol × módulo del portal (2026-08-15)

Driver nuevo `scripts/e2e_role_matrix.py` ejecutado contra el proxy del stack
candidato (`http://127.0.0.1:19020/api/bridge`): crea un usuario por rol
(prefijo `e2erm-*`), recorre los nueve endpoints de los seis módulos del
portal con cada rol, verifica el código esperado y el contrato mínimo de cada
módulo, y desactiva los usuarios al terminar.

| Dimensión | Valor |
|---|---|
| Checks | **63/63 PASS** (7 roles × 9 endpoints) en **5.27 s** |
| Catálogo + dashboard | 200 para los 7 roles (tier `READ_ROLES`) |
| Clientes / ventas (leads, presupuestos, pedidos) / wiki | 200 para admins + supervisor/commercial/support/operator; **403 para `viewer`** (tier `OPERATOR_ROLES`) |
| Tareas programadas + usuarios | 200 solo `provider_admin` y `client_admin`; 403 para el resto (tier `ADMIN_ROLES`) |
| Contratos | envelope `{items,total}` del catálogo; dashboard role-aware (`role` + `permissions.approve/manage_users` correctos por rol); clave `items` en listas |
| Limpieza | usuarios desactivados vía `PATCH /users/{id}` y filas eliminadas por SQL → baseline `users=2`; stack 5/5 healthy; `/ready` 200 |
| Artefacto | `logs/rehearsal/e2e_role_matrix_20260815T145447Z.json` (gitignored) |

La matriz confirma en vivo que el portal no decide permisos por su cuenta:
los 403/200 observados coinciden uno a uno con `security.require_roles`.

## Alcance que podría promocionarse

Solo el perfil `production` core, con proveedores externos desactivados, publicación exclusivamente local y aprobada, email en spool manual por defecto (con SMTP propio opcional vía `EMAIL_PROVIDER=smtp`, implementado pero pendiente de certificación con el proveedor real), facturas como borradores y SEO estático sobre HTML suministrado. `full`, Chatwoot, FlowWink, Activepieces, PrestaShop, GHL, SMTP/API de correo, crawler SEO y publicación externa requieren certificación separada.

## Regla de reevaluación

El responsable de release debe adjuntar los comandos/resultados de todos los stop-ships, actualizar esta matriz y elegir exactamente una de las cuatro decisiones permitidas. No se heredan estados verdes de un runtime de desarrollo ni de informes anteriores.
