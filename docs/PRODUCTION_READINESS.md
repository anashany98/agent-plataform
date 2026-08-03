# Estado autoritativo de preparación para producción

> **Este archivo es la única fuente autoritativa para decidir la preparación para producción del proyecto.** Las decisiones o etiquetas de readiness presentes en auditorías, planes, informes o releases anteriores son fotografías históricas y quedan supersedidas para decisiones actuales por este documento.

## Decisión actual

# NOT PRODUCTION READY — CRITICAL RISK

- **Fecha de evaluación:** 2 de agosto de 2026
- **Fuentes evaluadas:** `agents.md` y `docs/PROJECT_TECHNICAL_AUDIT.md`
- **Rama observada:** `production-remediation`
- **Commit P0 observado:** `de236e9`
- **Release candidata evaluada:** ninguna

Los seis defectos P0 reproducidos están `VERIFIED` en la rama mediante 124 pruebas locales y PostgreSQL efímero real, incluido modo optimizado, concurrencia y ciclos de migración. Esto cierra el bloque P0 de implementación, pero no convierte la rama en candidata: permanecen 25 P1 y 5 P2 abiertos, no existe restore, build limpio/full stack, E2E crítico, validación UI, supply-chain/licencias ni release inmutable. Cuatro P1 nuevos fueron confirmados por revisión adversarial en PrestaShop, webhooks e importación.

**Actualización 2026-08-03:** re-verificación en vivo del corpus; D-032 (harness no hermético) quedó `VERIFIED` en `4afd0c7` — el corpus combinado pasa 159/159 en ambos órdenes de colección con entorno limpio. Conteo actual: seis P0, siete P1 y dos P2 verificados; 22 defectos abiertos (19 P1, 3 P2). Stack antiguo del propietario detenido con volúmenes intactos (`DECISIONS.md` D-007/D-008); margen de RAM pendiente de medición (B-001 mitigado). La decisión no cambia.

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
| PR-01 | Cero defectos P0 abiertos | BLOCKED | Los seis P0 están `VERIFIED` en `de236e9`; no existe todavía una release candidata sobre la que cerrar el criterio. | Revalidar el registro en la candidata identificada y mantener cero regresiones P0 durante los gates restantes. |
| PR-02 | P1 críticos del núcleo corregidos | BLOCKED | Permanecen 25 P1 abiertos, incluidos egress, proxy, Chatwoot, idempotencia, PrestaShop, RAG, dependencias, restore y observabilidad. | Cerrar P1 críticos con pruebas de regresión y evidencia runtime; no basta con código o health. |
| PR-03 | Sin mocks en producción | BLOCKED | Stubs/mocks y demo están prohibidos por flags en production-like, pero no existe arranque completo del perfil production sin ellos. | Probar build/arranque production y proveedores locales reales sin fallback sintético. |
| PR-04 | Sin datos demo visibles | BLOCKED | Whitelist de procedencia, seed opt-in y startup fail-closed pasan unit/integración; falta candidata y verificación API/chat/UI runtime. | Revalidar rutas cliente en build production y candidata sin datos heredados demo. |
| PR-05 | Aislamiento entre clientes probado | BLOCKED | 14 modelos, ORM y 12 FKs compuestas pasan matriz cruzada y PostgreSQL; archivos, RAG, exportación y E2E completo siguen abiertos. | Completar matriz de todos los recursos y canales en la candidata, incluida exfiltración RAG. |
| PR-06 | Confirmaciones seguras | BLOCKED | Token/hash/caducidad/actor/replay y concurrencia PostgreSQL están verificados; el lease de inbox/webhook y E2E de chat siguen abiertos. | Cerrar D-035 y ejecutar chat→quote→confirmación visible sobre la candidata. |
| PR-07 | Migraciones no destructivas | BLOCKED | Alembic explícito pasó clean, histórica, downgrade/reupgrade y reserva activa en PostgreSQL; falta rollback de release con backup/restore. | Probar migración y rollback de una candidata versionada junto con restore completo. |
| PR-08 | Cálculos deterministas | BLOCKED | Contratos cubren variante, scopes, precedencia segura, fiscalidad, redondeo, envío y stock; faltan sandbox autorizado, paginación >500 y producto oculto/no vendible. | Cerrar D-033/D-034 y contrastar golden cases con una fuente autorizada. |
| PR-09 | Operaciones idempotentes | BLOCKED | Confirmación/reservas son idempotentes bajo PostgreSQL; GHL, Activepieces, webhook lease e importación aún pueden perder/duplicar efectos. | Inbox/outbox, CAS, locks y replay con fault injection para todos los efectos externos/sensibles. |
| PR-10 | Permisos efectivos en backend | BLOCKED | Auth fue verificada, pero RBAC quedó solo parcialmente cubierto y no existe matriz completa de rutas, recursos, tenants y carreras. | Probar cada permiso sensible en backend, incluida escalada, enumeración, service accounts y aprobación. |
| PR-11 | Stack production arrancando limpio | BLOCKED | Nginx no creaba workers, Chatwoot reiniciaba y el build limpio se canceló por presión de memoria; el stack terminó detenido. | Build e instalación limpios, perfil production seguro, reinicios repetidos y arranque desde volúmenes nuevos. |
| PR-12 | Servicios esenciales funcionales | BLOCKED | Proxy y Chatwoot estaban rotos; Bridge/Chatwoot/Activepieces carecían de ruta de salida; varias dependencias solo estaban healthy/configuradas. | Definir servicios esenciales y ejecutar smoke funcional, no solo health, con degradación explícita de opcionales. |
| PR-13 | Tests críticos aprobados | BLOCKED | El bloque P0 suma 101 pruebas funcionales/aislamiento y 23 de migración más PostgreSQL real; P1, Redis, runtime, UI y E2E aún no están aprobados. | Completar suite crítica P1 y E2E de candidata sin dobles del componente objetivo. |
| PR-14 | E2E principales aprobados | BLOCKED | No se ejecutaron E2E de chat, comercio, Chatwoot, PrestaShop, GHL, Portal o restore; Playwright quedó bloqueado. | Ejecutar E2E internos y sandboxes autorizados con evidencia visible y estados finales comprobados. |
| PR-15 | Backup restaurado | BLOCKED | Hay scripts de copia, pero el backup nunca se restauró y puede ser incompleto/inconsistente. | Restaurar en instalación vacía, verificar checksums, conteos y flujos, y medir RPO/RTO. |
| PR-16 | Rollback probado | BLOCKED | Los scripts requerían Git, hacían checkout global y el downgrade podía borrar datos. | Probar rollback de aplicación y esquema por cliente sobre una release versionada, preservando datos. |
| PR-17 | Agentes limitados a herramientas autorizadas | BLOCKED | `allowed_tools` estaba inerte y `/agents/run` ejecutaba texto libre sin tool calling o grounding obligatorio. | Policy deny-by-default por tenant/rol/agente, executor controlado y pruebas de tool injection/bypass. |
| PR-18 | Facturación automática desactivada | BLOCKED | No se aportó una prueba production fail-closed ni un E2E que impida emisión sin permiso, aprobación y confirmación explícita. | Configuración segura, controles backend y tests de emisión no autorizada; ninguna factura real durante la prueba. |
| PR-19 | Publicaciones con aprobación | BLOCKED | SEO/landing/publicación no están implementados o verificados y no existe evidencia de bloqueo automático por defecto. | Política común de aprobación y E2E aislado que rechace publicar sin permiso/aprobación. |
| PR-20 | RAG aislado y con citas | BLOCKED | RAG básico y citas pasaron con TF-IDF local, pero había 0 documentos runtime, ACL amplia y defensa de secretos evadible. | Dataset multi-tenant, proveedor real/local contractual, ACL estricta, citas verificables, abstención y evals de inyección. |
| PR-21 | Logs y métricas operativos | BLOCKED | No había logging central, trazas, dashboards, alertas, SLO ni detección automática de fallos comerciales. | Logs JSON correlacionados, métricas/trazas y alertas verificadas mediante fault injection sin exponer secretos/PII. |
| PR-22 | Sin secretos en repositorio | BLOCKED | `.env` está ignorado/no trazado y el working tree P0 no contiene patrones de alta señal; faltan historial completo original, candidata y artefactos. | Escaneo de working tree, historial disponible y artefacto final; rotación documentada si aparece cualquier secreto. |
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

1. Cualquier regresión P0 en demo, confirmación, precio/impuesto/stock, migración o aislamiento.
2. Operaciones sensibles/externas sin inbox/outbox, lease, idempotencia y auditoría atómica.
3. RAG sin ACL deny-by-default o productos/precios ocultos expuestos por rutas cliente.
4. Restore y rollback de release no probados.
5. Egress/ingress, E2E crítico, build reproducible, permisos, dependencias o licencias sin verificar.

## Condición para cambiar la decisión

La decisión solo puede actualizarse después de evaluar una release candidata identificada por versión y hash. Cada fila debe enlazar evidencia actual de tests y runtime; `FIXED`, documentación, compilación, health checks, tests con mocks o configuración declarativa no sustituyen `VERIFIED`.

Si se detecta un P0, secreto, acceso cruzado, migración destructiva, confirmación insegura, backup no restaurado, permiso insuficiente, E2E crítico pendiente o build no reproducible, la decisión debe permanecer exactamente `NOT PRODUCTION READY — CRITICAL RISK`.
