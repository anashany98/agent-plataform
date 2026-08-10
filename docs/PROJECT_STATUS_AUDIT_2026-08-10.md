# Estado real y camino a producción — 10 de agosto de 2026

## Executive Summary

- **Decisión: NO-GO — CRITICAL RISK.** El proyecto tiene un núcleo transaccional valioso y varias correcciones P0/P1 bien diseñadas, pero el árbol actual no supera sus propias puertas de calidad, migración e integración. Los 30 criterios de `docs/PRODUCTION_READINESS.md` siguen `BLOCKED`.
- **Hay una regresión destructiva potencial y once fallos reproducidos.** `restore_to_url()` ejecuta `drop_all()` sin demostrar que la base destino esté vacía; la migración no versionada `0006_product_embeddings.py` rompe ocho pruebas de migración; integración falla en idempotencia del webhook y catálogo local.
- **El producto entregado es un core parcial, no la plataforma empresarial descrita.** Funcionan partes de autenticación, aislamiento, comercio determinista, aprobaciones, outbox, RAG y observabilidad, pero faltan el framework persistente de agentes, CRM local completo, Wiki, SEO, SEO continuo, landing pages, CI/CD, operación multiworker y gran parte del portal.
- **No existe una candidata de release verificable.** Docker estaba detenido, el host solo tenía 2,83 GiB de RAM libre y no se revalidaron PostgreSQL, Redis, Ollama, perfiles `full/production`, restore integral, E2E de proveedores ni soak. La rama está 57 commits por delante del remoto y contiene una migración ajena sin seguimiento.

## 1. Alcance, versión y criterio de auditoría

| Elemento | Valor observado |
|---|---|
| Rama | `production-remediation` |
| Commit | `c5c0b5239b8308a9f65eae9f09e11798f9cae7ed` |
| Diferencia remota | 57 commits por delante de `origin/production-remediation` |
| Árbol de trabajo | Limpio salvo `bridge-api/alembic/versions/0006_product_embeddings.py` sin seguimiento |
| Recovery point creado | tag local `audit-start-20260810-c5c0b52` |
| Entorno | Windows 11 Pro 10.0.26200; Python 3.11.7; Node 24.13.0; npm 11.6.2 |
| Recursos | 31,46 GiB RAM total; 2,83 GiB libres; 69,57 GiB libres en C: |
| Docker | CLI 29.5.3 / Compose 5.1.4; daemon no disponible |
| Decisión autoritativa | `NOT PRODUCTION READY — CRITICAL RISK`; 0/30 criterios verificados |

La auditoría cubrió código propio, migraciones, tests, Compose, Dockerfiles, portal, seguridad, documentación y preparación operativa. No se conectó a servicios reales, no se usaron credenciales, no se arrancó Docker y no se ejecutó ninguna operación destructiva.

## 2. Evidencia ejecutada sobre el árbol actual

| Control | Resultado actual | Lectura correcta |
|---|---|---|
| Backend unitario | `23 passed` | Verde, alcance estrecho |
| Integración backend | `2 failed, 30 passed, 3 skipped` | Rojo; rompe flujo local e idempotencia |
| Regresión parcial | `8 failed, 187 passed, 6 skipped` | Rojo; los ocho fallos son migraciones por `0006` |
| Suite backend completa | Timeout a 124,1 s, sin resultado | No puede declararse verde |
| Quality gates | FAIL: 5 `ruff-hard`, 6 `clean-zone`, deuda 242 > baseline 213 | La puerta D-030 ha regresado |
| Portal typecheck | PASS | Tipado compilable |
| Portal tests | PASS 5/5 | Solo componentes con `fetch` mockeado |
| Portal build | PASS | Bundle generable |
| Portal format | FAIL en 7/7 fuentes | Higiene de código no conforme |
| ESLint | FAIL; no existe `eslint.config.*` | Lint frontend inoperante |
| `npm audit --omit=dev` | 0 vulnerabilidades | Runtime productivo sin hallazgos conocidos |
| `npm audit` completo | FAIL: 1 HIGH en `nanoid@3.3.16` | Supply chain de build/CI no conforme |
| Compose `core` / `full` | Configuración estática válida | No acredita arranque ni funcionalidad |
| Compose de producción de ejemplo | Inválido por sí solo: proxy sin `image`/`build` | Perfil production no reproducible |
| Runtime/E2E visual/soak | BLOCKED | Docker detenido y memoria insuficiente |

Los resultados históricos verdes siguen siendo útiles como evidencia de diseño, pero no sustituyen la reverificación del commit actual.

## 3. Qué funciona y merece conservarse

El proyecto no parte de cero. La base útil incluye:

- Contexto obligatorio de instalación y aislamiento ORM de los modelos transaccionales.
- Confirmación estructurada con token/hash/caducidad y cálculos financieros con `Decimal`.
- Reservas de stock, aprobaciones con compare-and-set, idempotencia durable y outbox con DLQ.
- Adaptadores de PrestaShop, GHL, Chatwoot y Activepieces con política de fallo cerrado en varias rutas.
- Clasificación y ACL RAG, DLP determinista, citas y defensas básicas contra prompt injection.
- Logs JSON correlacionados, redacción de secretos y métricas/alertas in-memory.
- Backup lógico de tablas con manifiesto, checksums y pruebas históricas de roundtrip en SQLite/PostgreSQL.
- Portal React en español con login, tema, catálogo, documentos, agentes, usuarios, automatizaciones y aprobaciones.
- Compose `core` y `full` con redes, volúmenes, healthchecks y límites para varios servicios.

Estas capacidades están parcialmente probadas y deben evolucionar de forma incremental; no conviene sustituir la arquitectura completa ni hacer un refactor big-bang.

## 4. Fallos stop-ship y cómo corregirlos

### 4.1 P0 — restore capaz de borrar una base no vacía

`bridge-api/app/services/backup.py:165-171` crea un engine y llama a `Base.metadata.drop_all(engine)` antes de restaurar. El docstring afirma que el destino es una base vacía, pero el código no lo verifica ni exige marker efímero, confirmación o allowlist.

**Impacto:** una URL equivocada puede destruir una base accesible. No se ejecutó por seguridad.

**Solución:** eliminar el borrado implícito; exigir una base nueva o un marker de restore generado para ese run; abortar si existen tablas o filas; restaurar en una base nueva y hacer switch controlado; añadir pruebas negativas contra destino poblado y prueba PostgreSQL con fixture preservado.

### 4.2 P1 — migración `0006` rompe instalación/upgrade

Alembic detecta `0006` como `head`, aunque el archivo no está versionado. Ejecuta `CREATE EXTENSION` sobre SQLite y provoca ocho fallos. Además declara pgvector, pero almacena `ARRAY(Float)`, no tiene modelo, FK tenant-safe, servicio ni índice vectorial funcional. El backup sigue fijado a schema `0005`.

**Solución:** coordinar el cambio ajeno antes de tocarlo. No promoverlo. Completar modelo y servicio con `pgvector.sqlalchemy.Vector`, FK por instalación/producto e índice apropiado; hacer la migración aditiva y explícita por dialecto; actualizar schema version, backup y tests clean/upgrade/downgrade en PostgreSQL. La suite debe volver a cero fallos.

### 4.3 P1 — replay del webhook queda en `processing`

El primer saludo firmado devuelve 200; el mismo mensaje devuelve 202 `processing`. Varias ramas hacen `_checkpoint_idempotency(...); return` y saltan el cierre final.

**Solución:** centralizar un único finalizador que marque `completed` atómicamente antes de devolver; reservar checkpoints para ventanas con efectos externos; cubrir cada rama con replay inmediato, takeover tras lease, crash antes/después del efecto y concurrencia PostgreSQL.

### 4.4 P1 — el core no funciona sin PrestaShop

Un producto local confiable se importa correctamente, pero el chat fuerza `source="prestashop"` y termina en `catalog_empty_handoff`. Esto contradice el requisito de operación independiente y la política que admite fuentes `local/import/prestashop`.

**Solución:** introducir `CatalogProvider`, usar `LocalCatalogProvider` como proveedor real por defecto y hacer configurable la fuente activa; distinguir origen y frescura; permitir PrestaShop como opcional; añadir E2E `chat → producto local → lead → presupuesto` sin servicios externos.

### 4.5 P1 — quality gate regresado y error de runtime latente

`bridge-api/app/main.py:1983` usa `_LOG` sin definir; si falla `commerce_chat`, el propio fallback lanza `NameError`. Hay imports muertos y la deuda Ruff subió de 213 a 242.

**Solución:** definir el logger correcto, limpiar imports, actualizar código nuevo a la zona limpia y mantener el baseline sin aumentarlo. Añadir un test que fuerce la excepción del LLM y verifique el fallback determinista.

### 4.6 P1 — RBAC del portal rompe roles y aprobaciones

El portal descarta el rol devuelto por login, muestra la misma navegación a todos y carga dashboard/costes/aprobaciones con `Promise.all`, aunque los endpoints requieren roles distintos. Un 403 invalida todo el resumen. Roles sin permiso ven botones de aprobación; aprobar/rechazar es de un clic y sin resumen, diff, riesgo, caducidad ni confirmación.

**Solución:** conservar principal y permisos, aplicar matriz de rutas/acciones, cargar widgets de forma independiente, crear endpoint de dashboard por rol y exigir detalle + confirmación accesible + razón + estado in-flight para acciones sensibles. Verificar cada rol contra backend real.

### 4.7 P1 — catálogo del portal truncado y sin frescura

El frontend carga una lista sin búsqueda/paginación y presenta el número recibido como total, aunque el backend limita por defecto a 50. Precio y stock locales se muestran sin `updated_at` ni advertencia.

**Solución:** API paginada con total/cursor, búsqueda, filtros y orden; exponer origen/frescura; advertir que precio/stock no sincronizados requieren confirmación; test con más de 50 productos.

### 4.8 P1 — automatizaciones pueden declarar éxito falso

El proveedor local de email silencia `OSError` y puede responder `accepted=True`; un proveedor desconocido cae a local. El webhook saliente puede usar la idempotency key como secreto HMAC y acepta URL arbitraria sin política SSRF.

**Solución:** spool/outbox durable con estados `queued/delivered/failed`, error explícito y fallback solo opt-in de desarrollo; secreto obligatorio con rotación/key-id/timestamp; SafeFetch con allowlist, resolución DNS/IP y bloqueo de rangos privados.

### 4.9 P1 — SSRF habilitado globalmente en Chatwoot

`docker-compose.yml` fija `SAFE_FETCH_ALLOW_PRIVATE_NETWORK=true` en el entorno compartido de Chatwoot. El vendor desactiva así el filtro de red privada, y la ruta de upload por `external_url` puede recuperar contenido HTTP interno.

**Solución:** mantener el flag en `false` en producción; usar URL pública HTTPS para Bridge o una excepción estricta por host/puerto/ruta; probar loopback, link-local, metadata cloud, RFC1918, redirects y DNS rebinding.

### 4.10 P1 — rate limiting y confianza del proxy eludibles

Uvicorn acepta forwarded headers desde cualquier IP, el rate limiter confía en `X-Real-IP`/`X-Forwarded-For`, `TRUSTED_PROXY_COUNT` no se usa y los buckets viven en memoria por proceso.

**Solución:** aceptar forwarded headers solo desde el CIDR del proxy; sobrescribirlos en el edge; derivar IP mediante cadena validada; mover rate limit y lockout a Redis con claves por instalación, usuario e IP.

### 4.11 P1 — TLS y production Compose no son desplegables

El overlay de producción publica `443:443` y activa `ENABLE_SSL`, pero el proxy solo escucha en 8080 y no hay listener TLS, certificados ni redirección. Combinado con el Compose base conserva además HTTP público en 9000.

**Solución:** Compose de producción completo; listener 443 con secretos/certificados, redirección 80→443, eliminación del 9000 público y pruebas de handshake, headers, WebSocket y renovación.

### 4.12 P1 — supply chain y producción no reproducibles

El audit completo tiene una vulnerabilidad HIGH de build; las imágenes usan tags sin digest; no hay `.github/workflows`; el ejemplo Compose de producción es inválido por sí solo; solo existen perfiles `core/full`, no los seis perfiles solicitados.

**Solución:** actualizar lock/dependencias; gatear dependencias productivas y de build; crear CI autoritativa; generar SBOM; fijar imágenes por digest; convertir production en overlay documentado y validado o compose autocontenido; crear perfiles development/testing/staging/production con configuración fail-closed.

## 5. Qué falta para completar la plataforma

| Dominio | Estado real | Trabajo mínimo pendiente |
|---|---|---|
| Framework de agentes | Parcial/in-memory | Registros persistentes de agente/versión/prompt/tools; runner sync/async; cancelación, timeout, retry, circuit breaker, scheduler, kill switch, historial y evaluaciones |
| Proveedores IA | Parcial/hardcoded | Interfaces LLM/Embedding/Reranker; OpenAI/Ollama/OpenAI-compatible/local; streaming, structured output, tool calling, fallback, costes y política de datos |
| Chat/atención | Parcial | Conversaciones/mensajes/adjuntos persistentes, orden/dedupe, memoria y resumen controlados, handoff visible y E2E Chatwoot |
| Catálogo | Parcial | Provider formal, local/CSV/XLSX/JSON/API, categorías/variantes/tarifas/versionado/import/export y frescura |
| CRM/leads | Muy parcial | LocalCRMProvider, personas/empresas/leads/oportunidades/pipelines/etapas/notas/actividades/tareas/consentimiento/import/export |
| Presupuestos | Parcial interno | CRUD, direcciones, series/numeración, versiones, estados, PDF/envío, rechazo/historial y portal |
| Pedidos | Parcial interno | CRUD/API, lifecycle completo, validación/approval portal, integración de stock y E2E concurrency |
| Facturación | Borradores parciales | Emisión controlada, numeración segura, inmutabilidad, vencimientos, rectificativas, PDF/export contable y permisos |
| Wiki | No implementado | Modelo, versiones, búsqueda, permisos, adjuntos, import/export y drafts con aprobación |
| RAG | Parcial | MIME real/AV, object storage, pipeline async, estado de ingesta, reindex/version/delete, SQL ACL, reranker y benchmark |
| SEO | No implementado | Proyectos/dominos/URLs/keywords/crawls/issues/recomendaciones/reportes y trazabilidad medido/importado/inferido |
| SEO continuo | No implementado | Scheduler, locks, rate limiting, diffs, alertas, ventanas, presupuesto e historial |
| Landing pages | No implementado | Editor/modelo, plantillas, preview/versionado, CSP/XSS/CSRF, formularios, aprobación, publicación/rollback |
| Automatizaciones | Parcial | Definiciones persistentes, triggers/condiciones/ramas/delays/cron, activación/versionado/cancelación/DLQ/UI |
| Aprobaciones | Parcial | Motor común con before/after, riesgo, caducidad, comentarios, revocación, políticas y notificaciones |
| Portal | Muy incompleto | La mayoría de módulos empresariales, CRUD, filtros, búsqueda, paginación, estados de error y permisos reales |
| Auth/RBAC | Parcial | Organizaciones, permisos granulares, sesiones persistentes, recovery, MFA, service accounts, rotación, bloqueo distribuido |
| Observabilidad | Parcial | Collector, OTel/trazas, Prometheus externo, dashboards, SLO/alertas operativas y health de workers/colas/integraciones |
| Infra/DR | Parcial | Runtime production, TLS, digests, hardening completo, backup de objetos/config, retención/offsite, restore integral y RPO/RTO |
| CI/CD/QA | Ausente/parcial | Pipeline, cobertura, E2E, seguridad, migraciones, backup/restore, performance, accesibilidad, SBOM, imágenes y rollback |

## 6. Ruta recomendada a producción

### Fase A — recuperar un árbol promovible (0–7 días de equipo)

1. Aislar o completar `0006` sin descartar el cambio ajeno.
2. Corregir `restore_to_url`, replay del webhook, catálogo local y `_LOG`.
3. Recuperar quality gates, format, ESLint y audit completo a cero HIGH/CRITICAL.
4. Actualizar `STATUS`, `TASKS`, readiness y limitaciones con evidencia actual.
5. Crear una RC identificada por SemVer, commit, tag y changelog.

**Gate de salida:** cero P0/P1 del núcleo; corpus completo verde en ambos órdenes; migraciones PostgreSQL clean/upgrade/downgrade; ninguna operación destructiva implícita.

### Fase B — candidata core independiente (2–4 semanas)

1. LocalCatalogProvider y LocalCRMProvider funcionales.
2. E2E real `chat interno → lead → presupuesto → confirmación → pedido → borrador de factura → aprobación`.
3. Redis real para rate limit, locks, sesiones/colas y worker/scheduler durable.
4. Portal RBAC y CRUD del alcance comercial mínimo.
5. Backup integral + restore a instalación vacía + RPO/RTO medidos.

**Gate de salida:** perfil `core/production` desde cero, sin PrestaShop/GHL/Chatwoot/Activepieces/FlowWink, sin demo/mocks, con reboot/soak y rollback.

### Fase C — integraciones y operación (2–4 semanas adicionales, condicionadas a sandboxes)

1. Chatwoot visible y handoff real; contratos live de PrestaShop, GHL y proveedor IA.
2. Egress allowlisted, SSRF/fault injection, replay y reconciliación.
3. CI/CD, registry, digests, SBOM, escaneo de secretos/dependencias/imágenes.
4. OTel/Prometheus, dashboards, SLO y alertas ensayadas.
5. Revisión legal de vendor/EE, privacidad, retención y términos comerciales.

### Fase D — plataforma completa (varios incrementos posteriores)

Wiki, SEO, SEO continuo, landing pages, automatizaciones completas y facturación ampliada deben entregarse por dominio, cada uno con modelo, API, portal, permisos, aprobación, auditoría, pruebas y runbook. No deben bloquear la RC core si se eliminan de la promesa comercial hasta estar verificados.

## 7. Criterios mínimos para autorizar producción

No promover hasta que se cumplan todos:

- Release candidata inmutable y trazable; rama sincronizada con remoto.
- Cero P0 y P1 de flujo principal; suite completa, lint, typecheck y audits verdes.
- Migración clean/upgrade/rollback y restore integral verificados en PostgreSQL real.
- Core funcional sin integraciones externas, datos demo ni respuestas simuladas.
- Aislamiento y RBAC por recurso/rol, incluido RAG, archivos y enumeración de IDs.
- Confirmación/idempotencia/concurrencia verificadas con fault injection.
- Finanzas recalculadas exclusivamente en backend determinista.
- Portal probado en navegador, móvil, teclado, claro/oscuro y accesibilidad.
- Runtime production con TLS, digests, non-root/capabilities mínimas, resource limits, readiness/liveness y graceful shutdown.
- Logs/métricas/trazas/alertas externas sin secretos; SLO y runbooks ensayados.
- Backup restaurado, RPO/RTO medidos, rollback de release probado.
- SBOM, licencias, privacidad/retención y revisión legal aprobadas.
- E2E de cada integración incluida en el alcance comercial usando sandbox autorizado.

## 8. Preguntas de producto que deben cerrarse

1. ¿La primera release comercial será un core local o incluirá Chatwoot, PrestaShop y GHL?
2. ¿Qué módulos quedan contractualmente fuera de la primera release: Wiki, SEO, landing, facturación o automatizaciones avanzadas?
3. ¿Qué países y reglas fiscales se soportarán tras revisión profesional?
4. ¿Qué RPO, RTO, SLO, volumen de catálogo, concurrencia y retención se comprometerán?
5. ¿Quién aprueba licencias vendor/EE, DPA/privacidad y política de borrado?

## 9. Caveats y bloqueos

- Docker estaba detenido; no se revalidó runtime, PostgreSQL, Redis, Ollama, perfiles full/production, E2E ni soak.
- No había autorización/credenciales para proveedores externos; sus contratos live siguen bloqueados.
- El host tenía poca memoria libre; no se inició Docker ni un build full para proteger otros proyectos.
- La migración `0006` es un cambio preexistente sin seguimiento y no fue modificada.
- El HTML autocontenido pasó validación de payload y estructura, pero el lector mejorado quedó en estado fallback durante la QA; no se verificaron interacciones, diálogos de fuentes ni viewports. La representación semántica permanece legible.
- Los plazos dependen de limitar el alcance de la primera release; completar las 25 capacidades maestras es un programa de producto, no un único sprint.

## Conclusión

El repositorio ha avanzado mucho desde la auditoría original, pero la remediación no está cerrada y la documentación histórica sobrestima el estado actual. La decisión correcta es mantener `NO-GO`, reparar primero los stop-ship reproducidos, crear una RC core independiente y solo después ampliar integraciones y módulos. La ruta técnica existe; lo que falta es convertir el conjunto de correcciones parciales en una release reproducible, operable y probada de extremo a extremo.
