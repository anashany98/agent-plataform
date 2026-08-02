# MISIÓN MAESTRA — REMEDIACIÓN Y CONVERSIÓN A PRODUCCIÓN

Actúa como responsable técnico principal del proyecto, combinando los roles de:

- Arquitecto de software.
- Desarrollador backend senior.
- Desarrollador frontend senior.
- Ingeniero DevOps y SRE.
- Especialista en PostgreSQL y Redis.
- Especialista en seguridad de aplicaciones.
- Responsable de QA y automatización de pruebas.
- Especialista en agentes de IA.
- Especialista en RAG y sistemas documentales.
- Especialista en integraciones empresariales.
- Especialista en SEO técnico y automatización.
- Responsable de producto y preparación comercial.

Trabaja directamente sobre el proyecto existente abierto en este workspace.

No crees un proyecto alternativo separado.
No generes únicamente un informe.
No te limites a explicar cómo debería hacerse.
Debes analizar, diseñar, corregir, implementar, integrar, probar, documentar,
medir y preparar una release candidata a producción.

Tienes autorización para modificar el código, crear archivos, ejecutar
terminal, utilizar Docker, crear migraciones, añadir pruebas, actualizar
dependencias y reorganizar componentes cuando exista una justificación técnica.

No tienes autorización para:

- Eliminar datos reales sin confirmación.
- Conectarte a servicios externos reales sin credenciales y autorización.
- Publicar páginas en dominios públicos.
- Emitir facturas reales.
- Confirmar pedidos reales.
- Enviar correos o mensajes reales.
- Ejecutar migraciones destructivas sobre sistemas externos.
- Exponer secretos en código, logs o documentación.

==================================================
OBJETIVO FINAL
==================================================

Transformar el proyecto en una plataforma empresarial de agentes de IA:

- Estable.
- Segura.
- Modular.
- Escalable.
- Mantenible.
- Observable.
- Documentada.
- Reproducible.
- Preparada para producción.
- Desplegable de forma independiente para diferentes clientes.
- Funcional incluso sin PrestaShop, GHL u otras integraciones externas.

La plataforma debe permitir configurar, ejecutar, supervisar y auditar agentes
especializados en:

1. Chat comercial.
2. Atención al cliente.
3. Soporte técnico.
4. Captación y cualificación de leads.
5. Recomendación de productos.
6. CRM.
7. Presupuestos.
8. Pedidos.
9. Borradores de facturas.
10. Facturación controlada.
11. Wiki empresarial.
12. RAG documental.
13. Base de conocimiento.
14. SEO técnico.
15. SEO de contenidos.
16. SEO continuo.
17. Monitorización periódica de webs.
18. Creación de landing pages.
19. Automatizaciones.
20. Aprobaciones humanas.
21. Tareas programadas.
22. Informes.
23. Costes y consumo de IA.
24. Integraciones externas.
25. Importación y exportación de datos.

==================================================
MODO AUTÓNOMO DE EJECUCIÓN
==================================================

Trabaja de forma autónoma hasta completar todas las fases posibles.

No solicites confirmación para:

- Corregir errores.
- Añadir tests.
- Mejorar tipado.
- Corregir lint.
- Añadir validaciones.
- Endurecer seguridad.
- Crear documentación.
- Añadir migraciones no destructivas.
- Crear adaptadores.
- Añadir proveedores locales.
- Añadir observabilidad.
- Añadir CI/CD.
- Corregir Docker.
- Mejorar UX.
- Refactorizar código inseguro.
- Actualizar dependencias vulnerables compatibles.

Solicita confirmación únicamente antes de:

- Eliminar información.
- Eliminar módulos completos.
- Ejecutar una operación destructiva.
- Acceder a servicios externos reales.
- Publicar contenido real.
- Emitir documentos comerciales reales.
- Cambiar irreversiblemente el formato de datos.
- Realizar una migración que no pueda revertirse.
- Sustituir completamente la arquitectura principal.

Cuando exista un bloqueo externo:

1. Registra el bloqueo.
2. Implementa la interfaz.
3. Implementa un proveedor local real.
4. Añade tests contractuales.
5. Añade configuración.
6. Documenta las credenciales necesarias.
7. Continúa con las demás tareas independientes.

La ausencia de PrestaShop, GHL, Chatwoot externo, proveedores de email u otras
credenciales no debe detener el proyecto.

==================================================
USO DE SUBAGENTES
==================================================

Cuando el entorno permita subagentes, divide el trabajo entre especialistas:

- architecture-agent
- backend-agent
- frontend-agent
- security-agent
- devops-agent
- database-agent
- qa-agent
- ai-agent
- rag-agent
- seo-agent
- business-modules-agent
- documentation-agent

Cada subagente debe:

- Trabajar en un alcance definido.
- Registrar archivos modificados.
- Ejecutar sus tests.
- Entregar evidencias.
- No sobrescribir cambios ajenos.
- Informar de dependencias.
- No declarar VERIFIED sin pruebas.

El agente principal debe revisar e integrar todos los resultados.

No permitas que varios subagentes modifiquen simultáneamente los mismos
archivos sin coordinación.

==================================================
CONTROL DE CONTEXTO
==================================================

Aunque el consumo de tokens no sea una limitación, evita repetir trabajo.

No leas innecesariamente:

- node_modules/
- .git/objects/
- dist/
- build/
- coverage/
- backups/
- cachés/
- archivos binarios/
- logs históricos completos/

Para proyectos vendor como FlowWink, Chatwoot o Activepieces:

1. Revisa licencia.
2. Revisa documentación.
3. Revisa Docker y configuración.
4. Revisa las APIs utilizadas.
5. Revisa modificaciones locales.
6. Amplía el análisis solo cuando un problema concreto lo requiera.

Registra cada avance en documentos persistentes.

==================================================
DOCUMENTOS DE CONTROL
==================================================

Crea o actualiza desde el inicio:

- AGENTS.md
- TASKS.md
- STATUS.md
- CHANGELOG.md
- DECISIONS.md
- BLOCKERS.md
- docs/PRODUCTION_REMEDIATION_PLAN.md
- docs/PRODUCTION_READINESS.md
- docs/TEST_EVIDENCE.md
- docs/KNOWN_LIMITATIONS.md
- docs/ARCHITECTURE.md
- docs/SECURITY.md

TASKS.md debe contener:

- ID.
- Fase.
- Prioridad.
- Componente.
- Problema.
- Causa raíz.
- Solución prevista.
- Criterio de aceptación.
- Tests necesarios.
- Estado.
- Evidencia.
- Commit.
- Dependencias.

Estados permitidos:

- TODO
- IN PROGRESS
- BLOCKED
- FIXED
- VERIFIED
- DEFERRED
- NOT APPLICABLE

Prioridades:

- P0: pérdida de datos, acceso cruzado, ejecución no autorizada o riesgo crítico.
- P1: flujo principal roto, inseguro o integración esencial no funcional.
- P2: problema relevante con alternativa temporal.
- P3: mejora, refactorización o problema menor.

No marques VERIFIED únicamente porque:

- Exista código.
- Compile.
- El contenedor arranque.
- El health check responda.
- Exista documentación.
- Un test use mocks.
- La configuración esté presente.

VERIFIED exige prueba real y reproducible.

==================================================
CONTROL DE GIT
==================================================

Antes de modificar nada:

1. Ejecuta `pwd`.
2. Ejecuta `git status`.
3. Registra rama y commit actual.
4. Revisa cambios sin confirmar.
5. No descartes cambios del usuario.
6. Crea una rama:

   production-remediation

7. Crea un punto de recuperación.
8. Realiza commits pequeños y coherentes.
9. Ejecuta tests antes de cada commit.
10. No mezcles cambios no relacionados.

Formato recomendado de commits:

- fix(core):
- fix(security):
- feat(agent):
- feat(seo):
- feat(wiki):
- feat(billing):
- feat(landing):
- feat(automation):
- test:
- docs:
- chore(devops):

==================================================
REGLAS INNEGOCIABLES DE PRODUCCIÓN
==================================================

1. No utilizar datos demo como datos reales.

2. No utilizar mocks o stubs en flujos de producción.

3. Los mocks solo están permitidos en tests explícitamente identificados.

4. Todo acceso debe estar aislado por cliente.

5. El contexto de cliente debe ser obligatorio y fail-closed.

6. Ningún agente puede acceder a herramientas no autorizadas.

7. Ningún agente puede cambiar precios, stock, pedidos, facturas o publicaciones
   sin permisos y validación.

8. El LLM no puede calcular directamente:

   - Precio.
   - Descuento.
   - IVA.
   - Margen.
   - Total.
   - Stock.
   - Numeración.
   - Estados contables.

9. Los cálculos financieros deben usar Decimal.

10. Los cálculos deben ejecutarse en servicios deterministas.

11. Los totales enviados por el frontend nunca son confiables.

12. Presupuestos, pedidos y facturas deben recalcularse en el servidor.

13. Las confirmaciones no pueden depender de coincidencias por substring.

14. “No acepto”, “no confirmo”, “cancelar” o equivalentes nunca pueden aprobar
    una operación.

15. Todo webhook debe ser autenticado e idempotente.

16. Toda acción sensible debe quedar auditada.

17. No utilizar SQLite en producción.

18. No utilizar `latest` en imágenes de producción.

19. No guardar secretos en código, repositorio, logs o informes.

20. No declarar un backup verificado sin restaurarlo.

21. No declarar un flujo E2E verificado sin ejecutarlo.

22. No silenciar excepciones.

23. No convertir un error en una respuesta HTTP exitosa falsa.

24. No realizar publicaciones automáticas por defecto.

25. La facturación automática debe estar desactivada por defecto.

==================================================
FASE 0 — BASELINE
==================================================

Registra:

- Sistema operativo.
- CPU.
- RAM.
- Disco.
- GPU.
- Git.
- Docker.
- Docker Compose.
- Python.
- Node.js.
- npm.
- pnpm.
- PostgreSQL.
- Redis.
- Puertos ocupados.
- Contenedores existentes.
- Redes.
- Volúmenes.

Inspecciona:

- README.
- Docker Compose.
- Dockerfiles.
- `.env.example`.
- Configuraciones.
- Migraciones.
- Tests.
- Informes anteriores.
- Documentación de arquitectura.
- Documentación de seguridad.
- Scripts de backup.
- Scripts de despliegue.
- Dependencias.
- Licencias.

Genera:

docs/baseline/BASELINE.md
docs/baseline/COMPONENT_INVENTORY.md
docs/baseline/DEPENDENCY_MAP.md
docs/baseline/DATA_OWNERSHIP.md

==================================================
FASE 1 — REPRODUCCIÓN DE DEFECTOS
==================================================

Reproduce y verifica todos los problemas conocidos.

Comprueba específicamente:

- Productos demo visibles como reales.
- Falta de filtro por origen.
- Falta de aislamiento entre clientes.
- Confirmaciones mediante substrings.
- “No acepto” interpretado como aceptación.
- Precio incorrecto por variantes.
- Precios específicos ignorados.
- IVA fijo o incorrecto.
- Stock local divergente.
- Reservas de stock inconsistentes.
- Migraciones con `drop_all`.
- Nginx sin workers funcionales.
- Chatwoot reiniciando.
- Archivos PID antiguos.
- Workers con errores.
- Servicios healthy que no funcionan.
- Dependencia de mocks.
- LLM simulado.
- Embeddings simulados.
- RAG sin proveedor real.
- Backup nunca restaurado.
- Documentación contradictoria.
- Falta de pruebas E2E.
- Activepieces sin flujos funcionales.
- FlowWink sin backend funcional.
- Webhooks sin autenticación.
- Falta de idempotencia.
- Secretos predeterminados.
- Contenedores ejecutándose como root.
- Puertos innecesariamente públicos.
- Dependencias vulnerables.

No asumas que continúan.
No asumas que están corregidos.
Reproduce cada uno y guarda la evidencia.

Genera:

docs/remediation/DEFECT_REGISTER.md
docs/remediation/RISK_REGISTER.md
docs/remediation/REPRODUCTION_EVIDENCE.md

==================================================
FASE 2 — CORRECCIÓN DE P0 Y P1
==================================================

No desarrolles nuevas funciones hasta corregir los defectos críticos del núcleo.

Implementa:

## Aislamiento

- Contexto obligatorio de cliente.
- Base de datos independiente por instalación.
- Validación `tenant_id` o `client_id`.
- Repositorios con filtros obligatorios.
- Servicios fail-closed.
- Auditoría del tenant.
- Tests de acceso cruzado.
- Tests de enumeración de IDs.
- Tests de archivos y RAG entre clientes.

## Datos demo

- Campo de origen obligatorio.
- Datos demo prohibidos en producción.
- Arranque bloqueado si `ALLOW_DEMO_DATA=true`.
- Separación de seeds.
- Tests que demuestren que no aparecen datos demo.

## Confirmaciones

Implementa una máquina de estados:

- Acción pendiente.
- ID de acción.
- Usuario.
- Cliente.
- Resumen.
- Hash del contenido.
- Fecha de caducidad.
- Token de confirmación.
- Estado.
- Idempotency key.
- Aprobador.
- Registro de auditoría.

Añade pruebas con expresiones negativas.

## Migraciones

- Elimina cualquier `drop_all`.
- Añade migraciones no destructivas.
- Prueba instalación limpia.
- Prueba upgrade.
- Prueba rollback.
- Añade backup previo para cambios sensibles.
- Añade validación del esquema.

## Finanzas

- Decimal.
- Moneda explícita.
- Reglas fiscales configurables.
- Redondeo definido.
- Cálculos en backend.
- Inmutabilidad de documentos emitidos.
- Protección contra manipulación.

## Idempotencia

Aplica idempotencia a:

- Webhooks.
- Leads.
- Presupuestos.
- Pedidos.
- Facturas.
- Reservas.
- Automatizaciones.
- Publicaciones.
- Importaciones.

==================================================
FASE 3 — ARQUITECTURA DE PRODUCCIÓN
==================================================

Mantén como estrategia inicial:

MULTI-INSTANCE SINGLE-TENANT

Cada cliente debe tener:

- Configuración independiente.
- Secretos independientes.
- PostgreSQL independiente.
- Redis independiente o aislamiento demostrado.
- Red independiente.
- Volúmenes independientes.
- Backup independiente.
- Dominio independiente.
- Logs identificables.
- Límites de recursos.
- Actualización independiente.
- Exportación.
- Eliminación segura.

Responsabilidades:

## Bridge API

Fuente de verdad para:

- Clientes.
- Usuarios.
- Roles.
- Agentes.
- Herramientas.
- Catálogo local.
- CRM local.
- Leads.
- Presupuestos.
- Pedidos.
- Facturas.
- Aprobaciones.
- Wiki.
- Documentos.
- SEO.
- Landing pages.
- Automatizaciones.
- Auditoría.
- Costes.

## Portal

- Administración.
- Configuración.
- Operación.
- Supervisión.
- Aprobaciones.
- Informes.
- Integraciones.

## Chatwoot

- Conversaciones.
- Bandejas.
- Agentes humanos.
- Asignaciones.
- Handoff.

## FlowWink

- Diseño de flujos y agentes cuando aporte funcionalidad demostrable.
- Nunca fuente de verdad financiera o transaccional.

## Activepieces

- Automatizaciones externas.
- Bridge debe validar y auditar las operaciones críticas.

## PostgreSQL

- Fuente de verdad transaccional.

## Redis

- Caché.
- Locks.
- Rate limiting.
- Sesiones.
- Colas temporales.

## Almacenamiento de objetos

- Documentos.
- Imágenes.
- Exportaciones.
- Landing pages.
- Backups.

Genera diagramas Mermaid y ADRs de las decisiones.

==================================================
FASE 4 — FRAMEWORK CENTRAL DE AGENTES
==================================================

Implementa:

- Agent Registry.
- Agent Version Registry.
- Agent Runner.
- Tool Registry.
- Tool Executor.
- Tool Permission Policy.
- Prompt Registry.
- Model Provider Registry.
- Execution Context.
- Tenant Context.
- Approval Policy.
- Cost Tracker.
- Execution History.
- Evaluation Service.
- Scheduler.
- Kill Switch.

Cada agente debe tener:

- ID.
- Cliente.
- Tipo.
- Nombre.
- Descripción.
- Versión.
- Estado.
- Propietario.
- Prompt versionado.
- Modelo.
- Proveedor.
- Parámetros.
- Herramientas permitidas.
- Fuentes autorizadas.
- Permisos.
- Límites de tokens.
- Presupuesto.
- Timeout.
- Reintentos.
- Política de abstención.
- Política de aprobación.
- Configuración de memoria.
- Métricas.
- Historial.
- Auditoría.

Implementa:

- Ejecución síncrona.
- Ejecución asíncrona.
- Cancelación.
- Timeout.
- Retry con backoff.
- Circuit breaker.
- Rate limiting.
- Resultado estructurado.
- Validación de esquemas.
- Registro de tool calls.
- Coste estimado y real.
- Límites diarios y mensuales.
- Evaluación automática.
- Versionado y rollback de prompts.

==================================================
FASE 5 — PROVEEDORES DE IA
==================================================

Crea una interfaz desacoplada:

LLMProvider

Implementaciones preparadas:

- OpenAIProvider.
- OllamaProvider.
- OpenAICompatibleProvider.
- Proveedor local de desarrollo.

Crea:

EmbeddingProvider
RerankerProvider

Requisitos:

- Configuración por agente.
- Timeout.
- Reintentos.
- Fallback configurable.
- Circuit breaker.
- Control de coste.
- Métricas.
- Streaming.
- Respuestas estructuradas.
- Tool calling.
- Validación de salida.
- Política de datos.
- Redacción de información sensible.

No utilices respuestas simuladas en producción.

==================================================
FASE 6 — CHAT Y ATENCIÓN
==================================================

Implementa el flujo real:

Usuario
→ chat
→ webhook autenticado
→ Bridge
→ Agent Runner
→ herramientas
→ respuesta
→ usuario.

Debe funcionar con:

- Chat interno.
- Chatwoot.
- API externa preparada.

Funciones:

- Conversaciones persistentes.
- Mensajes.
- Estados.
- Adjuntos.
- Memoria controlada.
- Resumen.
- Captura progresiva de datos.
- Lead.
- Etiquetas.
- Asignación.
- Transferencia humana.
- Consentimiento.
- Feedback.
- Idioma.
- Reintentos.
- Deduplicación.
- Control de mensajes fuera de orden.
- Webhooks idempotentes.
- Cierre y reapertura.

Añade E2E para el chat interno y Chatwoot cuando esté disponible.

==================================================
FASE 7 — CATÁLOGO
==================================================

Crea:

CatalogProvider

Implementaciones:

- LocalCatalogProvider completamente funcional.
- CsvCatalogProvider.
- XlsxCatalogProvider.
- JsonCatalogProvider.
- PrestashopCatalogProvider.
- Proveedor API genérico.

Funciones:

- Productos.
- Referencias.
- Categorías.
- Variantes.
- Atributos.
- Características.
- Imágenes.
- Documentos.
- Tarifas.
- Precios.
- IVA.
- Stock.
- Disponibilidad.
- Origen.
- Estado.
- Fecha de actualización.
- Versionado.
- Importación.
- Exportación.

PrestaShop debe ser opcional.

Cuando los datos sean locales:

- Mostrar fecha de actualización.
- Indicar que precio y stock pueden requerir confirmación.
- Nunca presentarlos falsamente como tiempo real.

Los PDF pueden alimentar RAG, pero no deben ser la fuente automática de precio,
impuestos o stock.

==================================================
FASE 8 — CRM Y LEADS
==================================================

Crea:

CRMProvider

Implementaciones:

- LocalCRMProvider completamente funcional.
- GHLProvider.
- Adaptador genérico.
- Arquitectura preparada para HubSpot u otros.

Funciones:

- Personas.
- Empresas.
- Leads.
- Oportunidades.
- Pipelines.
- Etapas.
- Notas.
- Actividades.
- Tareas.
- Asignaciones.
- Consentimientos.
- Deduplicación.
- Historial.
- Importación.
- Exportación.
- Webhooks.

El sistema debe ser completamente utilizable sin GHL.

==================================================
FASE 9 — PRESUPUESTOS
==================================================

Implementa:

- Clientes.
- Direcciones.
- Numeración.
- Series.
- Versiones.
- Estados.
- Líneas.
- Cantidades.
- Unidades.
- Precios.
- Descuentos.
- Impuestos.
- Retenciones configurables.
- Totales.
- Validez.
- Notas.
- Condiciones.
- Documentos.
- PDF.
- Envío preparado.
- Aceptación segura.
- Rechazo.
- Historial.
- Auditoría.
- Conversión a pedido.

Los agentes pueden preparar borradores.

Todos los cálculos deben realizarse mediante servicios deterministas.

==================================================
FASE 10 — PEDIDOS
==================================================

Implementa:

- Estados.
- Líneas.
- Validaciones.
- Confirmación segura.
- Idempotencia.
- Stock.
- Reservas.
- Caducidad.
- Liberación.
- Cancelación.
- Historial.
- Aprobación.
- Auditoría.
- Conversión desde presupuesto.

No permitir confirmación automática por defecto.

==================================================
FASE 11 — FACTURACIÓN
==================================================

Implementa:

- Borradores.
- Series.
- Numeración segura.
- Estados.
- Líneas.
- Impuestos.
- Descuentos.
- Totales.
- Vencimientos.
- Inmutabilidad después de emisión.
- Rectificativas.
- PDF.
- Exportación.
- Auditoría.
- Aprobación.
- Preparación para integración contable.

Los agentes solo pueden preparar borradores.

La emisión requiere:

- Permiso.
- Aprobación.
- Confirmación explícita.
- Auditoría.
- Idempotencia.

No afirmes cumplimiento fiscal completo sin revisión profesional específica por
país.

==================================================
FASE 12 — WIKI
==================================================

Implementa:

- Espacios.
- Colecciones.
- Categorías.
- Páginas.
- Bloques.
- Borradores.
- Publicación.
- Versiones.
- Historial.
- Comparación.
- Restauración.
- Etiquetas.
- Búsqueda.
- Permisos.
- Adjuntos.
- Importación.
- Exportación.
- Enlaces internos.

Los agentes pueden:

- Crear borradores.
- Resumir.
- Clasificar.
- Detectar información obsoleta.
- Proponer actualizaciones.

Publicar modificaciones sensibles debe requerir aprobación.

==================================================
FASE 13 — RAG
==================================================

Implementa:

- Ingesta.
- Extracción.
- OCR preparado.
- Limpieza.
- Chunking.
- Metadatos.
- Embeddings.
- Vector store.
- Recuperación.
- Reranking.
- Filtros.
- Citas.
- Abstención.
- Evaluación.
- Reindexación.
- Versionado.
- Eliminación.
- Estado de ingesta.

Seguridad:

- Aislamiento por cliente.
- Permisos por documento.
- No ejecutar instrucciones contenidas en documentos.
- Protección contra prompt injection.
- Validación MIME.
- Límites de tamaño.
- Sanitización.
- Registro de evidencias.
- Eliminación correcta del índice al borrar documentos.

Las respuestas documentales deben aportar referencias verificables.

==================================================
FASE 14 — SEO
==================================================

Implementa:

- Proyectos.
- Dominios.
- URLs.
- Keywords.
- Competidores.
- Auditorías.
- Problemas.
- Prioridades.
- Recomendaciones.
- Tareas.
- Estados.
- Historial.
- Métricas.
- Informes.

Capacidades:

- Titles.
- Meta descriptions.
- H1-H6.
- Canonicals.
- Robots.
- Sitemap.
- Open Graph.
- Twitter Cards.
- Schema.
- Alt text.
- Enlaces internos.
- Enlaces rotos.
- Redirecciones.
- Contenido duplicado.
- Thin content.
- Páginas huérfanas.
- Canibalización.
- Intención de búsqueda.
- Datos estructurados.
- Rendimiento técnico importado.
- Recomendaciones de contenido.

Diferencia:

- Dato medido.
- Dato importado.
- Inferencia.
- Recomendación generada por IA.

No publicar automáticamente.

==================================================
FASE 15 — SEO CONTINUO
==================================================

Implementa un scheduler para:

- Crawls periódicos.
- Comparación de versiones.
- Nuevas páginas.
- Páginas eliminadas.
- Errores HTTP.
- Cambios de metadata.
- Enlaces rotos.
- Cambios en robots.
- Cambios en sitemap.
- Indexabilidad.
- Páginas huérfanas.
- Contenido deteriorado.
- Alertas.
- Informes periódicos.
- Tareas priorizadas.

Añade:

- Locks distribuidos.
- Prevención de duplicados.
- Rate limiting.
- Reintentos.
- Cancelación.
- Presupuesto.
- Historial.
- Métricas.
- Notificaciones.
- Ventanas de ejecución.
- Respeto a robots y límites configurables.

==================================================
FASE 16 — LANDING PAGES
==================================================

Implementa:

- Proyectos.
- Sitios.
- Plantillas.
- Secciones.
- Componentes.
- Formularios.
- Temas.
- SEO.
- Responsive.
- Preview.
- Borradores.
- Versiones.
- Publicación.
- Rollback.
- Dominios.
- Analytics.
- Leads.
- Consentimiento.

Los agentes pueden generar:

- Estructura.
- Copy.
- Titulares.
- CTA.
- FAQ.
- Metadatos.
- Schema.
- Variantes.
- Imágenes propuestas.

Seguridad:

- Sanitización.
- CSP.
- Protección XSS.
- Formularios validados.
- Rate limiting.
- Antispam.
- Protección CSRF.
- Aprobación antes de publicar.

==================================================
FASE 17 — AUTOMATIZACIONES
==================================================

Implementa:

- Triggers.
- Acciones.
- Condiciones.
- Ramas.
- Delays.
- Webhooks.
- Cron.
- Reintentos.
- Dead-letter queue.
- Idempotencia.
- Logs.
- Cancelación.
- Aprobación.
- Versionado.
- Activación.
- Desactivación.
- Historial.

Activepieces puede utilizarse como motor externo.

Bridge debe conservar:

- Autorización.
- Validación.
- Estado.
- Auditoría.
- Límites.
- Aprobaciones.
- Reglas de negocio críticas.

==================================================
FASE 18 — APROBACIONES
==================================================

Crea un motor común de aprobaciones.

Debe soportar:

- Tipo de acción.
- Solicitante.
- Aprobador.
- Cliente.
- Recurso.
- Resumen.
- Datos antes y después.
- Riesgo.
- Caducidad.
- Estados.
- Comentarios.
- Rechazo.
- Revocación.
- Historial.
- Auditoría.
- Notificaciones.
- Políticas configurables.

Aplicar a:

- Pedidos.
- Facturas.
- Precios.
- Publicaciones SEO.
- Landing pages.
- Automatizaciones sensibles.
- Envíos masivos.
- Eliminaciones.
- Cambios de permisos.

==================================================
FASE 19 — PORTAL
==================================================

Construye un portal profesional con:

- Dashboard.
- Clientes.
- Usuarios.
- Roles.
- Agentes.
- Chat.
- Leads.
- CRM.
- Catálogo.
- Documentos.
- Wiki.
- Presupuestos.
- Pedidos.
- Facturas.
- SEO.
- SEO continuo.
- Landing pages.
- Automatizaciones.
- Aprobaciones.
- Integraciones.
- Modelos.
- Costes.
- Logs.
- Auditoría.
- Backups.
- Configuración.

Requisitos:

- Español consistente.
- Diseño profesional.
- Responsive.
- Modo claro.
- Modo oscuro.
- Accesibilidad.
- Navegación coherente.
- Estados vacíos.
- Skeletons o estados de carga.
- Errores claros.
- Formularios validados.
- Tablas.
- Búsqueda.
- Filtros.
- Ordenación.
- Paginación.
- Confirmaciones seguras.
- Permisos reales en backend.
- Sin datos simulados presentados como reales.

==================================================
FASE 20 — AUTENTICACIÓN Y RBAC
==================================================

Implementa:

- Usuarios.
- Organizaciones.
- Roles.
- Permisos granulares.
- Sesiones seguras.
- Recuperación.
- Cambio de contraseña.
- Revocación.
- MFA preparada.
- Tokens de servicio.
- Rotación.
- Bloqueo.
- Rate limiting.
- Auditoría.

Roles iniciales:

- Platform Owner.
- Client Administrator.
- Manager.
- Sales.
- Support.
- Marketing.
- SEO Specialist.
- Finance.
- Approver.
- Viewer.
- Service Account.

Aplica permisos en backend y frontend.

No confíes en ocultar botones.

==================================================
FASE 21 — SEGURIDAD
==================================================

Revisa y corrige:

- SQL injection.
- XSS.
- CSRF.
- SSRF.
- Command injection.
- Path traversal.
- Uploads.
- MIME spoofing.
- CORS.
- CSP.
- Cookies.
- Tokens.
- Sesiones.
- Webhooks.
- HMAC.
- Replay.
- Rate limiting.
- Brute force.
- Secretos.
- Dependencias.
- Contenedores root.
- Capabilities.
- Puertos.
- Redes.
- Prompt injection.
- Tool injection.
- RAG injection.
- Exfiltración.
- Acceso entre clientes.
- Bypass de aprobación.
- Manipulación de precio.
- Duplicación de operaciones.
- Escalada de privilegios.

Crea:

- docs/THREAT_MODEL.md
- docs/SECURITY.md
- docs/INCIDENT_RESPONSE.md
- docs/SECRET_MANAGEMENT.md
- Tests de seguridad.
- Audit log protegido.

No declares certificaciones formales.

==================================================
FASE 22 — OBSERVABILIDAD
==================================================

Implementa:

- Logs JSON.
- Correlation ID.
- Request ID.
- Tenant ID.
- User ID.
- Conversation ID.
- Agent Execution ID.
- Tool Call ID.
- Métricas.
- Trazas.
- Health.
- Readiness.
- Liveness.
- Estado de workers.
- Estado de colas.
- Estado de integraciones.
- Estado de modelos.
- Costes.
- Latencias.
- Errores.
- Alertas.
- Dashboards.

No registrar:

- Contraseñas.
- Tokens.
- Secretos.
- Documentos completos.
- Datos personales innecesarios.
- Datos financieros innecesarios.

==================================================
FASE 23 — DOCKER E INFRAESTRUCTURA
==================================================

Corrige:

- Dockerfiles.
- Docker Compose.
- Health checks.
- Dependencias de arranque.
- Usuarios no root.
- Límites CPU.
- Límites RAM.
- Restart policies.
- Redes internas.
- Puertos públicos.
- Volúmenes.
- Secrets.
- Logs.
- Graceful shutdown.
- Init.
- TLS.
- Reverse proxy.
- Certificados.
- Persistencia.
- Read-only filesystem cuando sea viable.
- Capabilities.

Crea perfiles:

- core
- chat
- automation
- full
- development
- testing
- staging
- production

El perfil `core` debe funcionar sin:

- FlowWink.
- Chatwoot.
- Activepieces.
- PrestaShop.
- GHL.

==================================================
FASE 24 — BACKUP Y RECUPERACIÓN
==================================================

Implementa backups por cliente de:

- PostgreSQL.
- Configuración.
- Documentos.
- Objetos.
- Prompts.
- Agentes.
- Automatizaciones.
- Metadatos.
- Landing pages.
- Wiki.

Añade:

- Cifrado.
- Checksums.
- Retención.
- Copia externa configurable.
- Restauración.
- Verificación.
- Informes.
- RPO.
- RTO.
- Alertas.
- Prueba periódica.

Restaura una copia en una instalación vacía.

No declares VERIFIED antes del restore.

==================================================
FASE 25 — CI/CD
==================================================

Crea pipeline con:

- Lint.
- Formato.
- Typecheck.
- Tests unitarios.
- Tests de integración.
- Tests E2E.
- Coverage.
- Build.
- Migraciones.
- Análisis de secretos.
- Auditoría de dependencias.
- Escaneo de imágenes.
- SBOM.
- Artefactos.
- Versionado.
- Release notes.
- Smoke tests.

Implementa:

- SemVer.
- Tags.
- Imágenes inmutables.
- Backup previo.
- Validación de migraciones.
- Staging.
- Aprobación.
- Producción.
- Rollback.

==================================================
FASE 26 — TESTS
==================================================

Crea o completa:

- Unitarios.
- Integración.
- Contrato.
- End-to-end.
- Seguridad.
- Permisos.
- Aislamiento.
- Idempotencia.
- Concurrencia.
- Migraciones.
- Backup.
- Restore.
- Actualización.
- Rollback.
- Chat.
- RAG.
- Agentes.
- Herramientas.
- Presupuestos.
- Pedidos.
- Facturas.
- SEO.
- SEO continuo.
- Landing pages.
- Automatizaciones.
- Interfaz.
- Accesibilidad básica.
- Rendimiento.

Casos obligatorios:

- “No acepto”.
- “No quiero confirmar”.
- “Cancela”.
- Webhook duplicado.
- Pedido duplicado.
- Dos confirmaciones simultáneas.
- Precio alterado.
- Impuesto alterado.
- Producto inexistente.
- Stock obsoleto.
- Documento malicioso.
- Prompt injection.
- Tool injection.
- Usuario sin permiso.
- Acceso a otro cliente.
- Integración caída.
- Modelo caído.
- Timeout.
- Reintento.
- Circuit breaker.
- Restore.
- Rollback.
- Publicación sin aprobación.

==================================================
FASE 27 — RENDIMIENTO
==================================================

Mide:

- Arranque.
- Consumo en reposo.
- Latencia API.
- Latencia del chat.
- Tiempo RAG.
- Tiempo de agentes.
- Consumo por worker.
- PostgreSQL.
- Redis.
- Colas.
- Importaciones.
- Crawls SEO.
- Landing builds.
- Backups.
- Restore.

Prepara capacidad para:

- 1 cliente.
- 5 clientes.
- 10 clientes.
- 25 clientes.
- 50 clientes.

Diferencia resultados medidos de estimaciones.

No introduzcas Kubernetes salvo necesidad demostrada.

Prioriza:

- Índices.
- Optimización de consultas.
- Paginación.
- Caché.
- Pooling.
- Workers.
- Colas.
- Límites.
- Almacenamiento de objetos.
- Separación de tareas pesadas.

==================================================
FASE 28 — LICENCIAS
==================================================

Revisa:

- Código propio.
- FlowWink.
- Chatwoot.
- Activepieces.
- Dependencias.
- Modelos.
- Embeddings.
- OCR.
- Rerankers.
- Imágenes.
- Fuentes.
- Iconos.
- Assets.

Crea:

- THIRD_PARTY_NOTICES.md
- docs/LICENSE_MATRIX.md
- Lista de restricciones comerciales.
- Lista de funciones Enterprise no incluidas.
- Lista de componentes sustituibles.

No declares redistribución permitida sin comprobar la licencia.

==================================================
FASE 29 — DOCUMENTACIÓN
==================================================

Crea o actualiza:

- README.md
- docs/ARCHITECTURE.md
- docs/INSTALLATION.md
- docs/DEVELOPMENT.md
- docs/PRODUCTION.md
- docs/SECURITY.md
- docs/OPERATIONS.md
- docs/BACKUP_AND_RESTORE.md
- docs/UPGRADE_AND_ROLLBACK.md
- docs/AGENT_PLATFORM.md
- docs/BUSINESS_MODULES.md
- docs/INTEGRATIONS.md
- docs/API.md
- docs/WEBHOOKS.md
- docs/RBAC.md
- docs/TEST_REPORT.md
- docs/PERFORMANCE_REPORT.md
- docs/LICENSE_MATRIX.md
- docs/ADMIN_MANUAL.md
- docs/USER_MANUAL.md
- docs/TROUBLESHOOTING.md
- docs/CLIENT_ONBOARDING.md

Marca informes contradictorios como:

SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES

Debe existir un único estado autoritativo:

docs/PRODUCTION_READINESS.md

==================================================
CONFIGURACIÓN SEGURA
==================================================

Crea `.env.example` completo.

Valores seguros:

APP_ENV=production
DEBUG=false
PILOT_MODE=false

ALLOW_DEMO_DATA=false
ALLOW_MOCK_LLM=false
ALLOW_INTEGRATION_STUBS=false

CATALOG_PROVIDER=local
CRM_PROVIDER=local
STORAGE_PROVIDER=local

ENABLE_QUOTES=true
ENABLE_ORDERS=false
ENABLE_INVOICES=false

ENABLE_AUTOMATIC_ORDER_CONFIRMATION=false
ENABLE_AUTOMATIC_INVOICE_ISSUANCE=false
ENABLE_AUTOMATIC_PUBLISHING=false

Bloquea el arranque en producción si detectas:

- Contraseñas predeterminadas.
- Secretos débiles.
- Mocks.
- Datos demo.
- SQLite.
- DEBUG.
- CORS abierto.
- Claves obligatorias ausentes.
- Migraciones críticas pendientes.
- Configuración insegura.
- Tokens de ejemplo.
- Imágenes `latest`.

==================================================
CRITERIOS DE PRODUCCIÓN
==================================================

No declares la plataforma lista hasta cumplir:

1. Cero defectos P0 abiertos.
2. P1 críticos del núcleo corregidos.
3. Sin mocks en producción.
4. Sin datos demo visibles.
5. Aislamiento entre clientes probado.
6. Confirmaciones seguras.
7. Migraciones no destructivas.
8. Cálculos deterministas.
9. Operaciones idempotentes.
10. Permisos efectivos en backend.
11. Stack production arrancando limpio.
12. Servicios esenciales funcionales.
13. Tests críticos aprobados.
14. E2E principales aprobados.
15. Backup restaurado.
16. Rollback probado.
17. Agentes limitados a herramientas autorizadas.
18. Facturación automática desactivada.
19. Publicaciones con aprobación.
20. RAG aislado y con citas.
21. Logs y métricas operativos.
22. Sin secretos en repositorio.
23. Licencias revisadas.
24. Documentación coherente.
25. Instalación limpia reproducible.
26. Release versionada.
27. Sistema funcional sin PrestaShop ni GHL.
28. Proveedores externos desacoplados.
29. Portal probado visualmente.
30. Límites y alertas configurados.

==================================================
RELEASE FINAL
==================================================

Genera:

release/production-candidate/

Incluye:

- Código fuente.
- Configuración de ejemplo.
- Migraciones.
- Docker Compose.
- Scripts.
- Tests.
- Documentación.
- SBOM.
- Checksums.
- Release notes.
- Instrucciones de instalación.
- Instrucciones de actualización.
- Instrucciones de rollback.
- Instrucciones de backup y restore.

No incluyas:

- .git/
- node_modules/
- Cachés.
- Secretos.
- Tokens.
- Datos reales.
- Backups reales.
- Logs sensibles.

Genera también:

- docs/FINAL_PRODUCTION_READINESS_REPORT.md
- docs/FINAL_PRODUCTION_READINESS_REPORT.html
- docs/FINAL_PRODUCTION_READINESS_REPORT.pdf
- docs/FINAL_TEST_REPORT.md
- docs/FINAL_SECURITY_REPORT.md
- docs/FINAL_PERFORMANCE_REPORT.md
- docs/FINAL_RELEASE_MANIFEST.md

==================================================
DECISIÓN FINAL
==================================================

La decisión debe ser exactamente una:

- PRODUCTION READY
- PRODUCTION READY WITH DOCUMENTED LIMITATIONS
- NOT PRODUCTION READY — REMEDIATION INCOMPLETE
- NOT PRODUCTION READY — CRITICAL RISK

No uses PRODUCTION READY cuando exista:

- Función crítica simulada.
- P0 abierto.
- Acceso cruzado.
- Migración destructiva.
- Backup no restaurado.
- Confirmación insegura.
- Facturación no controlada.
- Permisos insuficientes.
- E2E crítico no ejecutado.
- Secreto expuesto.
- Build production no reproducible.

==================================================
FORMA DE EJECUCIÓN
==================================================

Empieza ahora por la FASE 0.

Orden obligatorio:

1. Baseline.
2. Reproducción.
3. Registro de defectos.
4. Corrección P0.
5. Corrección P1.
6. Estabilización del core.
7. Framework de agentes.
8. Proveedores locales.
9. Chat y CRM.
10. Módulos empresariales.
11. Wiki y RAG.
12. SEO y SEO continuo.
13. Landing pages.
14. Automatizaciones.
15. Portal.
16. Seguridad.
17. Infraestructura.
18. Tests.
19. Backup y restore.
20. Rendimiento.
21. Licencias.
22. Documentación.
23. Release.
24. Auditoría final.

Completa, prueba y documenta una fase antes de avanzar.

Después de cada fase:

1. Actualiza TASKS.md.
2. Actualiza STATUS.md.
3. Actualiza CHANGELOG.md.
4. Actualiza docs/TEST_EVIDENCE.md.
5. Registra defectos pendientes.
6. Crea un commit estable.
7. Continúa automáticamente con la siguiente fase.

No te detengas únicamente para mostrar un resumen.

Continúa trabajando mientras exista una tarea segura y no bloqueada.

Cuando termines todas las tareas posibles, muestra:

- Estado general.
- Fases completadas.
- Fases bloqueadas.
- Defectos P0/P1 pendientes.
- Tests ejecutados.
- Cobertura.
- Estado del build.
- Estado de Docker.
- Estado del backup y restore.
- Cinco riesgos principales.
- Decisión final.
- Commits creados.
- Rutas de la release y los informes.