# Estado autoritativo de preparación para producción

> **Este archivo es la única fuente autoritativa para decidir la preparación para producción del proyecto.** Las decisiones o etiquetas de readiness presentes en auditorías, planes, informes o releases anteriores son fotografías históricas y quedan supersedidas para decisiones actuales por este documento.

## Decisión actual

# NOT PRODUCTION READY — CRITICAL RISK

- **Fecha de evaluación:** 2 de agosto de 2026
- **Fuentes evaluadas:** `agents.md` y `docs/PROJECT_TECHNICAL_AUDIT.md`
- **Rama observada:** `production-remediation`
- **Commit base observado:** `ed77056c9d8084ac7c23b587199938fd4cc346fe`
- **Release candidata evaluada:** ninguna

La decisión está bloqueada por defectos P0 abiertos o no revalidados, confirmación comercial insegura, migración destructiva, datos demo visibles como verificados, ausencia de restore, E2E críticos no ejecutados y build de producción no reproducido. La auditoría de origen registró cinco P0, 21 P1 y cuatro P2. Este documento no presupone que sigan presentes ni que hayan sido corregidos: continúan bloqueando readiness hasta que una prueba actual, reproducible y trazada demuestre lo contrario.

El runtime de la auditoría terminó detenido para proteger el host tras superar el 95 % de RAM durante el build. La recaptura de baseline confirma, mediante consultas de solo lectura, que los 14 contenedores siguen detenidos y los nueve volúmenes permanecen presentes; no se arrancó ningún servicio.

## Escala de estado

Solo se emplean los estados autorizados:

- `VERIFIED`: criterio probado de forma real, actual y reproducible contra la candidata evaluada.
- `FIXED`: corrección implementada, todavía pendiente de verificación suficiente.
- `IN PROGRESS`: verificación o corrección activa.
- `BLOCKED`: el criterio no puede aprobarse por evidencia negativa, insuficiente o por una dependencia no cerrada.
- `TODO`, `DEFERRED` y `NOT APPLICABLE`: únicamente cuando corresponda; un criterio de producción no se considera cumplido con estos estados.

## Matriz de los 30 criterios de producción

| ID | Criterio obligatorio | Estado | Evidencia actual | Bloqueo para aprobarlo |
|---:|---|---|---|---|
| PR-01 | Cero defectos P0 abiertos | BLOCKED | El registro de defectos de la auditoría contabiliza cinco P0; además, su tabla maestra clasifica restore y preparación de piloto como P0. | Reproducir, corregir y verificar todos los P0; el registro consolidado debe quedar en cero para la release candidata. |
| PR-02 | P1 críticos del núcleo corregidos | BLOCKED | Se registraron 21 P1, incluidos egress, proxy, Chatwoot, RBAC, integraciones, RAG, dependencias, health y observabilidad. | Cerrar P1 críticos con pruebas de regresión y evidencia runtime; no basta con código o health. |
| PR-03 | Sin mocks en producción | BLOCKED | Los 31 tests usan SQLite, demo, mock LLM, stubs, TF-IDF y rate limit deshabilitado; no existe evidencia de un arranque production fail-closed. | Bloquear mocks/stubs por configuración y probar el perfil production sin ellos. |
| PR-04 | Sin datos demo visibles | BLOCKED | La DB auditada contenía 100 productos `source=demo` y la búsqueda no filtraba el origen. | Segregar seeds, prohibir demo en producción y demostrar con tests/API/UI que no aparece. |
| PR-05 | Aislamiento entre clientes probado | BLOCKED | El aislamiento por DB/red se infirió por proyecto, pero no hay pruebas negativas de IDs, archivos, RAG, exportación o operaciones cruzadas. | Ejecutar matriz de acceso cruzado y enumeración con al menos dos clientes sintéticos, fail-closed. |
| PR-06 | Confirmaciones seguras | BLOCKED | La coincidencia por substring podía interpretar “no acepto” como aceptación y crear pedido, reserva y borrador. | Máquina de estados, token, hash, caducidad, idempotencia y pruebas adversariales/concurrentes. |
| PR-07 | Migraciones no destructivas | BLOCKED | El downgrade auditado ejecutaba `drop_all`. | Sustituirlo por migraciones explícitas y probar instalación, upgrade y rollback preservando fixtures. |
| PR-08 | Cálculos deterministas | BLOCKED | Precio ignoraba variantes, precios específicos e impuesto real; stock y totales no tenían autoridad coherente. | Servicios backend con `Decimal`, moneda, reglas fiscales, redondeo y golden tests contra fuentes autorizadas. |
| PR-09 | Operaciones idempotentes | BLOCKED | GHL no tenía atomicidad/retry; Activepieces podía fabricar un ID; no se probó concurrencia de confirmaciones, reservas o webhooks. | Idempotencia atómica, locks/outbox cuando corresponda y pruebas duplicadas/concurrentes. |
| PR-10 | Permisos efectivos en backend | BLOCKED | Auth fue verificada, pero RBAC quedó solo parcialmente cubierto y no existe matriz completa de rutas, recursos, tenants y carreras. | Probar cada permiso sensible en backend, incluida escalada, enumeración, service accounts y aprobación. |
| PR-11 | Stack production arrancando limpio | BLOCKED | Nginx no creaba workers, Chatwoot reiniciaba y el build limpio se canceló por presión de memoria; el stack terminó detenido. | Build e instalación limpios, perfil production seguro, reinicios repetidos y arranque desde volúmenes nuevos. |
| PR-12 | Servicios esenciales funcionales | BLOCKED | Proxy y Chatwoot estaban rotos; Bridge/Chatwoot/Activepieces carecían de ruta de salida; varias dependencias solo estaban healthy/configuradas. | Definir servicios esenciales y ejecutar smoke funcional, no solo health, con degradación explícita de opcionales. |
| PR-13 | Tests críticos aprobados | BLOCKED | 31 tests pasaron con 67 % global, pero la suite simulada no cubre la ruta crítica real y contiene un falso positivo semántico sobre catálogo. | Suite crítica PostgreSQL/Redis y servicios deterministas sin mocks, con regresiones P0/P1 y cobertura por riesgo. |
| PR-14 | E2E principales aprobados | BLOCKED | No se ejecutaron E2E de chat, comercio, Chatwoot, PrestaShop, GHL, Portal o restore; Playwright quedó bloqueado. | Ejecutar E2E internos y sandboxes autorizados con evidencia visible y estados finales comprobados. |
| PR-15 | Backup restaurado | BLOCKED | Hay scripts de copia, pero el backup nunca se restauró y puede ser incompleto/inconsistente. | Restaurar en instalación vacía, verificar checksums, conteos y flujos, y medir RPO/RTO. |
| PR-16 | Rollback probado | BLOCKED | Los scripts requerían Git, hacían checkout global y el downgrade podía borrar datos. | Probar rollback de aplicación y esquema por cliente sobre una release versionada, preservando datos. |
| PR-17 | Agentes limitados a herramientas autorizadas | BLOCKED | `allowed_tools` estaba inerte y `/agents/run` ejecutaba texto libre sin tool calling o grounding obligatorio. | Policy deny-by-default por tenant/rol/agente, executor controlado y pruebas de tool injection/bypass. |
| PR-18 | Facturación automática desactivada | BLOCKED | No se aportó una prueba production fail-closed ni un E2E que impida emisión sin permiso, aprobación y confirmación explícita. | Configuración segura, controles backend y tests de emisión no autorizada; ninguna factura real durante la prueba. |
| PR-19 | Publicaciones con aprobación | BLOCKED | SEO/landing/publicación no están implementados o verificados y no existe evidencia de bloqueo automático por defecto. | Política común de aprobación y E2E aislado que rechace publicar sin permiso/aprobación. |
| PR-20 | RAG aislado y con citas | BLOCKED | RAG básico y citas pasaron con TF-IDF local, pero había 0 documentos runtime, ACL amplia y defensa de secretos evadible. | Dataset multi-tenant, proveedor real/local contractual, ACL estricta, citas verificables, abstención y evals de inyección. |
| PR-21 | Logs y métricas operativos | BLOCKED | No había logging central, trazas, dashboards, alertas, SLO ni detección automática de fallos comerciales. | Logs JSON correlacionados, métricas/trazas y alertas verificadas mediante fault injection sin exponer secretos/PII. |
| PR-22 | Sin secretos en repositorio | BLOCKED | La auditoría no informó secretos expuestos, pero carecía de Git completo y no existe evidencia de secret scan de la candidata y su historial. | Escaneo de working tree, historial y artefacto final; rotación documentada si aparece cualquier secreto. |
| PR-23 | Licencias revisadas | BLOCKED | Hay rutas EE de Chatwoot/Activepieces, notice contradictorio, falta licencia raíz y no se inventariaron modelos/SBOM. | Matriz, notices, SBOM y revisión legal/comercial de la release concreta. |
| PR-24 | Documentación coherente | BLOCKED | La auditoría identifica documentación contradictoria y promesas de módulos no implementados. | Validar documentación contra código/runtime y marcar material anterior contradictorio como superseded. |
| PR-25 | Instalación limpia reproducible | BLOCKED | El build `--no-cache --pull` se abortó al 95,3 % de RAM; no hay una instalación limpia aprobada. | Build e instalación desde cero en host dimensionado, con comandos, tiempos, hashes y smoke test. |
| PR-26 | Release versionada | BLOCKED | La auditoría no tenía Git; ahora existe rama/commit base, pero no hay candidata SemVer, tag, imágenes inmutables ni manifiesto aprobado. | Generar release candidata trazable, tag, digests, checksums, SBOM y release notes. |
| PR-27 | Sistema funcional sin PrestaShop ni GHL | BLOCKED | El backend local existe, pero productos eran demo y el recorrido comercial interno real no fue E2E. | Proveedores locales funcionales y E2E chat→lead→presupuesto/pedido borrador sin dependencias externas ni demo. |
| PR-28 | Proveedores externos desacoplados | BLOCKED | Hay adaptadores, pero egress estaba roto, faltaban credenciales y resiliencia, y algunos estados configurados se presentaban como funcionales. | Contratos comunes, proveedores locales, timeouts/retries/circuit breaker y tests contractuales de sustitución/degradación. |
| PR-29 | Portal probado visualmente | BLOCKED | Typecheck/build pasaron, pero no hubo prueba visual; cinco enlaces apuntaban a secciones ausentes y no había frontend tests/axe. | E2E visual/funcional en viewports acordados, accesibilidad básica y navegación completa sin funciones fantasma. |
| PR-30 | Límites y alertas configurados | BLOCKED | No había límites de recursos, alertas operativas ni presupuesto de coste efectivo; el host superó 95 % de RAM. | Límites CPU/RAM/colas/coste, umbrales y alertas validados con carga y fault injection. |

**Resultado:** `0/30` criterios `VERIFIED`. Los 30 criterios permanecen `BLOCKED`; por tanto, no existe base técnica para promover, vender o operar la plataforma como producción.

## Stop-ship vigentes

La promoción queda prohibida mientras exista cualquiera de estas condiciones:

1. Datos demo accesibles desde flujos presentados como reales.
2. Negaciones interpretables como confirmación o cualquier operación sensible sin estado, token, idempotencia y auditoría.
3. Cálculos de precio/impuesto/stock sin autoridad y servicios deterministas.
4. Migración destructiva o rollback no probado.
5. Aislamiento, restore, E2E crítico, build reproducible, permisos o licencias sin verificar.

## Condición para cambiar la decisión

La decisión solo puede actualizarse después de evaluar una release candidata identificada por versión y hash. Cada fila debe enlazar evidencia actual de tests y runtime; `FIXED`, documentación, compilación, health checks, tests con mocks o configuración declarativa no sustituyen `VERIFIED`.

Si se detecta un P0, secreto, acceso cruzado, migración destructiva, confirmación insegura, backup no restaurado, permiso insuficiente, E2E crítico pendiente o build no reproducible, la decisión debe permanecer exactamente `NOT PRODUCTION READY — CRITICAL RISK`.
