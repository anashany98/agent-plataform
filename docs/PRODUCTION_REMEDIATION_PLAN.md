# Plan de remediación y conversión a producción

## 1. Propósito

Este documento define el orden de ejecución, los gates de salida y la evidencia mínima para transformar el workspace existente en una candidata de producción. No declara capacidades disponibles ni preparación para producción. El único estado autoritativo de readiness es [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md).

Fuentes de partida:

- `agents.md`, que establece alcance, invariantes, orden obligatorio y criterios de producción.
- `docs/PROJECT_TECHNICAL_AUDIT.md`, fotografía técnica del 2 de agosto de 2026.
- Repositorio local observado en la rama `production-remediation`, commit base `ed77056c9d8084ac7c23b587199938fd4cc346fe`.

La auditoría anterior es evidencia inicial, no prueba de que los defectos sigan presentes ni de que hayan sido corregidos. Cada hallazgo debe reproducirse de nuevo y cada corrección debe tener una prueba reproducible antes de usar `VERIFIED`.

## 2. Reglas de ejecución

1. El orden de las 24 etapas de la sección 4 es obligatorio.
2. Una etapa no comienza hasta cerrar el gate de la anterior, salvo trabajo de diagnóstico o documentación que no modifique el producto y sea necesario para cerrar el gate vigente.
3. Cada gate exige código, pruebas y documentación coherentes. Compilar, arrancar o responder a un health check no basta para verificar una capacidad.
4. Los P0 y P1 del núcleo se corrigen antes de añadir funciones. Un P0 abierto bloquea cualquier promoción.
5. Todas las pruebas utilizan datos sintéticos controlados. No se contactan servicios reales, no se publican contenidos, no se envían mensajes y no se confirman operaciones reales.
6. Ante una integración externa bloqueada se implementan la interfaz, un proveedor local real, configuración segura y pruebas contractuales; la integración externa permanece `BLOCKED` hasta probarse con autorización.
7. Los cambios de esquema deben ser aditivos o reversibles. Toda operación destructiva requiere confirmación expresa y queda fuera de este plan automático.
8. Cada cambio debe preservar trabajo ajeno, ser pequeño, trazable y tener un punto de recuperación.
9. Solo se usan los estados `TODO`, `IN PROGRESS`, `BLOCKED`, `FIXED`, `VERIFIED`, `DEFERRED` y `NOT APPLICABLE`.

## 3. Gates transversales innegociables

Estos controles aplican desde la primera corrección y no pueden aplazarse a fases posteriores:

- Contexto de cliente obligatorio y fail-closed en repositorios, servicios, archivos, RAG, webhooks y auditoría.
- Datos demo segregados y prohibidos cuando `APP_ENV=production`.
- Confirmación mediante acción pendiente identificada, token de un solo uso, hash, caducidad, idempotencia y auditoría; nunca mediante substrings.
- Cálculos comerciales deterministas con `Decimal`, moneda e impuestos explícitos y recálculo exclusivo en backend.
- Idempotencia atómica para webhooks y operaciones con efecto; sin identificadores de ejecución inventados.
- Herramientas de agentes denegadas por defecto y limitadas por tenant, rol, agente y aprobación.
- Mocks y stubs limitados a tests explícitos; arranque de producción bloqueado si están activos.
- Facturación automática, confirmación automática de pedidos y publicación automática desactivadas por defecto.
- Migraciones no destructivas, sin `drop_all`, con instalación, upgrade y rollback probados sobre fixtures.
- Errores reales con estado de error real; health, readiness y liveness separados.
- Secretos fuera de código, logs, artefactos y documentación.

## 4. Secuencia obligatoria y gates

| Orden | Etapa | Estado inicial | Trabajo mínimo | Gate de salida obligatorio |
|---:|---|---|---|---|
| 1 | Baseline | IN PROGRESS | Capturar entorno, Git, cambios existentes, componentes, dependencias, ownership de datos, puertos, contenedores, redes, volúmenes, configuraciones, migraciones, tests, scripts y licencias. Crear los cuatro documentos de `docs/baseline/`. | **G01:** baseline fechada y reproducible; inventario, mapa de dependencias y ownership completos; cambios del usuario identificados y preservados; rama y commit registrados; bloqueos documentados. |
| 2 | Reproducción | BLOCKED | Reejecutar uno por uno los hallazgos conocidos con datos sintéticos: demo, aislamiento, confirmación negativa, precios, IVA, stock, migraciones, proxy, Chatwoot, workers, mocks, RAG, webhooks, idempotencia, seguridad, dependencias y E2E. | **G02:** cada hallazgo tiene comando o caso de prueba, resultado observado/no observado/no ejecutable, entorno y evidencia sanitizada; no se infiere corrección. |
| 3 | Registro de defectos | BLOCKED | Consolidar defectos sin duplicados con prioridad, causa raíz, impacto, owner, solución, aceptación, tests, dependencias y evidencia. | **G03:** todos los P0/P1 conocidos están trazados a evidencia y a un test de regresión previsto; el orden de corrección está aprobado técnicamente. |
| 4 | Corrección P0 | BLOCKED | Corregir aislamiento, demo, confirmaciones, migraciones destructivas, finanzas e idempotencia crítica antes de ampliar funciones. | **G04:** cero P0 abiertos; pruebas negativas de acceso cruzado y consentimiento; instalación/upgrade/rollback preservan datos; concurrencia e idempotencia pasan en PostgreSQL; revisión de seguridad completada. |
| 5 | Corrección P1 | BLOCKED | Corregir flujos principales, proxy, red, health, Chatwoot, integraciones esenciales, RBAC, RAG crítico, dependencias y falsos éxitos. | **G05:** P1 críticos del núcleo `VERIFIED`; fallos de terceros degradan de forma explícita; no hay mocks/stubs en rutas de producción; regresión completa aprobada. |
| 6 | Estabilización del core | BLOCKED | Asegurar que Bridge, Portal, PostgreSQL y Redis operen como perfil `core` sin FlowWink, Chatwoot, Activepieces, PrestaShop ni GHL. Añadir límites, shutdown y checks correctos. | **G06:** instalación limpia y reinicios repetibles; smoke y soak del core aprobados; recursos dentro de presupuesto medido; sin datos demo ni configuración insegura. |
| 7 | Framework de agentes | BLOCKED | Implementar registros, runner, contexto, política de herramientas y aprobaciones, historial, costes, evaluación, scheduler y kill switch de forma incremental. | **G07:** ejecución síncrona/asíncrona, cancelación, timeout, retry, circuit breaker y schemas probados; tool calls no autorizadas denegadas y auditadas; límites de coste efectivos. |
| 8 | Proveedores locales | BLOCKED | Crear contratos desacoplados y proveedores locales funcionales para LLM de desarrollo, embeddings, catálogo, CRM y almacenamiento; preparar adaptadores externos sin usarlos. | **G08:** tests contractuales pasan para cada proveedor; sustitución por configuración sin cambiar dominio; producción rechaza el proveedor simulado y credenciales inválidas. |
| 9 | Chat y CRM | BLOCKED | Persistir conversaciones y mensajes; deduplicar y ordenar webhooks; captura progresiva, consentimiento, lead, asignación y handoff; CRM local utilizable. | **G09:** E2E de chat interno y CRM local aprobado; duplicados y mensajes fuera de orden controlados; Chatwoot queda `BLOCKED` hasta su E2E autorizado. |
| 10 | Módulos empresariales | BLOCKED | Catálogo, presupuestos, pedidos, reservas, facturas borrador y aprobaciones comunes con servicios deterministas. | **G10:** contratos y E2E locales prueban recálculo servidor, manipulación de precio/impuesto, concurrencia de stock, numeración, caducidad, cancelación, inmutabilidad y aprobación; no se emite una factura real. |
| 11 | Wiki y RAG | BLOCKED | Versionar wiki; ingesta segura, ACL, chunking, embeddings, recuperación, reranking, citas, abstención y eliminación coherente del índice. | **G11:** aislamiento por cliente/documento, MIME/tamaño/sanitización, prompt-injection y borrado probados; respuestas de evaluación incluyen citas verificables o abstención. |
| 12 | SEO y SEO continuo | BLOCKED | Modelo de proyectos/auditorías y crawler programado con medición diferenciada de inferencia; locks, límites, historial y alertas. | **G12:** crawl sintético reproducible, robots y rate limits respetados, ejecuciones deduplicadas/cancelables y recomendaciones no publicadas automáticamente. |
| 13 | Landing pages | BLOCKED | Borradores, versiones, preview, formularios, SEO, responsive, consentimiento y publicación controlada. | **G13:** sanitización, CSP, XSS, CSRF, antispam y validación probados; publicación y rollback requieren permiso y aprobación en entorno aislado. |
| 14 | Automatizaciones | BLOCKED | Triggers, acciones, condiciones, cron, retry, DLQ, cancelación, versionado y aprobación, manteniendo reglas críticas en Bridge. | **G14:** duplicación, timeout, retry, DLQ y cancelación probados; una automatización no puede saltarse RBAC, tenant, aprobación ni reglas de negocio. |
| 15 | Portal | BLOCKED | Exponer únicamente módulos reales; completar navegación, permisos, estados, validación, tablas, filtros, responsive, temas y accesibilidad. | **G15:** pruebas de componentes y E2E en viewports acordados; axe básico sin defectos bloqueantes; cada enlace funciona y ningún dato simulado se presenta como real. |
| 16 | Seguridad | BLOCKED | Threat model y corrección de auth, sesiones, HMAC/replay, uploads, CORS/CSP, SSRF, inyecciones, rate limit, secretos, escalada, RAG/tool injection y cadena de suministro. | **G16:** suite de seguridad y permisos aprobada, secret scan limpio, audit log protegido y revisión manual de hallazgos; sin P0/P1 de seguridad abiertos. |
| 17 | Infraestructura | BLOCKED | Endurecer imágenes/Compose, usuarios, capabilities, puertos, redes, egress, TLS, volúmenes, límites, health/readiness/liveness, logs y perfiles. | **G17:** build limpio reproducible, imágenes inmutables sin `latest`, escaneo/SBOM sin riesgos no aceptados, perfiles `core` y `production` arrancan desde cero y sobreviven reinicios. |
| 18 | Tests | BLOCKED | Completar unitarios, integración PostgreSQL/Redis, contrato, E2E, seguridad, concurrencia, migración, UI, accesibilidad y rendimiento. | **G18:** matriz obligatoria de `agents.md` aprobada; tests críticos sin mocks; cobertura por riesgo documentada; fallos reproducibles y CI verde. |
| 19 | Backup y restore | BLOCKED | Copiar por cliente DB, configuración, objetos y metadatos con cifrado, checksums, retención y restore en instalación vacía. | **G19:** restore completo ejecutado con fixture; hashes, conteos y flujos validados; RPO/RTO medidos; informe de restauración conservado. |
| 20 | Rendimiento | BLOCKED | Medir arranque, idle, API, chat, RAG, agentes, workers, DB, Redis, importaciones, crawls, builds, backup y restore. | **G20:** baseline y límites para 1 cliente; estimaciones para 5/10/25/50 claramente separadas de mediciones; cuellos de botella y presupuesto de recursos aceptados. |
| 21 | Licencias | BLOCKED | Inventariar código, vendor, dependencias, modelos y assets; delimitar EE, redistribución y componentes reemplazables. | **G21:** matriz, notices y SBOM coherentes; licencia del código propio definida; revisión legal/comercial registra restricciones y aceptación, sin afirmar derechos no comprobados. |
| 22 | Documentación | BLOCKED | Actualizar instalación, desarrollo, producción, seguridad, operaciones, API, webhooks, RBAC, integraciones, módulos, administración y troubleshooting. | **G22:** documentación ejecutada por un operador distinto; enlaces y comandos validados; contradicciones marcadas como `SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES`; readiness única y coherente. |
| 23 | Release | BLOCKED | Preparar `release/production-candidate/` sin secretos/datos/logs/cachés, con código, configuración, migraciones, tests, docs, SBOM, checksums y procedimientos. | **G23:** versión SemVer y artefactos inmutables; manifiesto/checksums verificados; instalación, smoke, upgrade y rollback de la candidata aprobados en staging aislado. |
| 24 | Auditoría final | BLOCKED | Reevaluar los 30 criterios de producción exclusivamente contra evidencia de la release candidata. | **G24:** los 30 criterios tienen evidencia reproducible; cero stop-ship; decisión exacta registrada únicamente en `docs/PRODUCTION_READINESS.md`. |

`BLOCKED` en las etapas 2–24 indica bloqueo deliberado por secuencia: todavía no se ha cerrado el gate precedente. No implica que todo el trabajo técnico de esas etapas sea imposible, sino que no puede declararse iniciado ni aceptado fuera de orden.

## 5. Criterio de evidencia por fase

Para cerrar cualquier gate debe quedar registrado:

- Commit y archivos modificados.
- Entorno, configuración no secreta y datos de prueba utilizados.
- Comandos exactos, resultado, duración y código de salida.
- Tests nuevos y de regresión; cobertura relevante por riesgo.
- Evidencia runtime cuando el criterio sea operativo o E2E.
- Riesgos residuales, bloqueos externos y alternativa local.
- Documentación y runbook actualizados.
- Revisión independiente de seguridad para P0/P1 y cambios financieros.

Los resultados con mocks solo verifican unidades aisladas. Las integraciones se mantienen `BLOCKED` hasta ejecutar contratos y E2E contra un sandbox autorizado. Los backups permanecen `BLOCKED` hasta restaurarlos.

## 6. Ruta crítica inmediata

La ejecución inmediata se limita a cerrar **G01**, después **G02** y **G03**. La primera modificación funcional autorizada por la secuencia será la corrección de P0 de **G04**. La auditoría anterior prioriza para reproducción, sin prejuzgar su estado actual:

1. Segregación de productos demo y arranque fail-closed.
2. Confirmaciones negativas y máquina de estados.
3. Precios, variantes, impuestos y stock con autoridad explícita.
4. Downgrade destructivo y preservación de datos.
5. Restore completo, aislamiento de cliente e idempotencia/concurrencia.

No se inicia el framework de agentes ni ningún módulo nuevo antes de cerrar P0, P1 y estabilización del core.

## 7. Control de cambios del plan

Este plan puede detallarse sin alterar el orden. Cambiar la estrategia `MULTI-INSTANCE SINGLE-TENANT`, introducir una operación irreversible o sustituir la arquitectura principal requiere una decisión explícita en un ADR y la autorización correspondiente. Todo cambio de gate debe conservar o elevar su nivel de evidencia; nunca rebajarlo para promover una release.
