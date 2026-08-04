# Registro de decisiones técnicas

## D-001 — Estrategia de tenancy

**Estado:** ACCEPTED
**Decisión:** Mantener `MULTI-INSTANCE SINGLE-TENANT` como primera arquitectura de producción. Cada cliente tendrá configuración, secretos, DB, redes, volúmenes, backup, dominio y ciclo de release independientes.

## D-002 — Core funcional sin integraciones externas

**Estado:** ACCEPTED
**Decisión:** PrestaShop, GHL, Chatwoot, Activepieces y proveedores cloud son adaptadores opcionales. Deben existir proveedores locales funcionales y contract tests comunes; la ausencia de credenciales debe fallar explícitamente, no simular éxito.

## D-003 — Integridad comercial determinista

**Estado:** ACCEPTED
**Decisión:** El LLM no calcula precios, impuestos, stock, totales, numeración ni estados financieros. Estos valores usan `Decimal`, contratos deterministas, snapshots de procedencia y validación del servidor.

## D-004 — Confirmación y aprobación

**Estado:** ACCEPTED
**Decisión:** Sustituir coincidencias de texto por una máquina de estados con acción pendiente, hash, token explícito, caducidad, idempotencia y auditoría. Facturación, pedidos y publicaciones automáticas permanecen desactivadas por defecto.

## D-005 — Control de cambios

**Estado:** ACCEPTED
**Decisión:** Inicializar Git local porque la entrega carecía de metadata. `ed77056` es el recovery point. Vendor y artefactos generados permanecen excluidos localmente hasta definir procedencia/submódulos y política de release.

## D-006 — Restricción de infraestructura

**Estado:** ACCEPTED
**Decisión:** No introducir Kubernetes sin evidencia de necesidad. Primero estabilizar Compose con perfiles, límites, health/readiness reales, egress allowlisted y despliegues por cliente.

## D-007 — Ruta de remediación A (candidata core)

**Estado:** APPROVED
**Fecha:** 2026-08-03
**Decisión:** El propietario aprueba la Ruta A: completar la Fase 2 restante, estabilizar el core, framework de agentes con proveedores locales reales, E2E chat→lead→presupuesto/pedido borrador sin dependencias externas, backup/restore y release candidata. SEO, SEO continuo, landing pages, automatizaciones y wiki quedan fuera de la primera candidata y se documentarán como limitación. La decisión final podrá ser `PRODUCTION READY WITH DOCUMENTED LIMITATIONS` solo si todos los gates del core se cumplen con evidencia.

## D-008 — Parada del stack antiguo

**Estado:** APPROVED
**Fecha:** 2026-08-03
**Decisión:** El propietario autoriza detener los compose projects `agent-platform`, `agent-piloto-rc1` y `agent-cliente-demo-es-staging` del workspace antiguo `C:\Users\PC\Desktop\PROYECTOS\automatiazcion\agent-platform` para liberar RAM y el puerto 9000. Ejecutado el 2026-08-03 con `docker compose down` sin `-v`: los volúmenes y datos se conservan; solo se retiraron contenedores y redes.

## D-009 — Idempotencia GHL por reconciliación, no por claves de proveedor

**Estado:** ACCEPTED
**Fecha:** 2026-08-03
**Decisión:** La API de GHL no acepta claves de idempotencia en la creación de contactos, oportunidades ni notas (y B-004 impide verificarlo live), así que la garantía de "como mucho un efecto externo" se implementa con reconciliación previa al efecto: antes de crear una oportunidad se busca por referencia externa determinista (custom field `external_reference` = `external_id`) y antes de crear una nota se busca por cuerpo exacto. Si la búsqueda falla no se crea a ciegas (fail-closed: reintento transitorio); un lead sin referencia externa es permanente y va a DLQ. La reconciliación se aplica en el dispatcher del outbox y en `/integrations/ghl/leads` (`ce2723c`, D-010). Residual documentado: el contrato live del endpoint de búsqueda queda pendiente de sandbox GHL.

## D-010 — Ciclo de vida: el AuditLog y los usuarios sobreviven al erase

**Estado:** ACCEPTED
**Fecha:** 2026-08-03
**Decisión:** El borrado de una instalación (`LifecycleService.request_erase`, D-029, `ff0eed8`) elimina únicamente los datos operativos (clientes, catálogo, presupuestos, pedidos, facturas, conversaciones, aprobaciones, RAG, idempotencia y outbox) en orden FK y limpia los archivos RAG dentro del directorio de subidas. El `AuditLog` y los usuarios nunca se borran: el registro de cumplimiento y las cuentas de acceso sobreviven al erase para preservar la trazabilidad legal. El borrado inmediato solo se ejecuta con `retention_days=0`; con retención positiva los datos sobreviven hasta el vencimiento y `process_due_erases` completa el borrado. El legal hold bloquea tanto la solicitud como el procesamiento de borrados vencidos mientras esté activo. El export nunca incluye `users` (credenciales) ni `audit_logs`. Residual documentado: la política de retención requiere revisión legal (B-008) y la inclusión de backups en el borrado queda para D-015.

## D-011 — Observabilidad: redacción determinista antes de emitir

**Estado:** ACCEPTED
**Fecha:** 2026-08-03
**Decisión:** Todo log estructurado pasa por `redact_for_log` antes de emitirse (D-028, `af53b8b`): las claves sensibles (password/secret/token/bearer/private_key/api_key/...) se sustituyen por `[REDACTED]` por coincidencia parcial de nombre, y los valores se redactan por patrón (JWT, claves `sk_live`, tarjetas con Luhn, bloques `BEGIN PRIVATE KEY`, claves AWS). El middleware de acceso emite correlation_id/request_id/tenant_id/user_id/route/method/status/latency_ms y las alertas in-memory (`circuit_breaker_open`, `outbox_dead_letter_growth`, `rag_abstention_rate`, `dlp_findings`) se exponen en `/metrics`. Residual documentado: OTel/Prometheus scrape y SLO formales quedan para la Fase 25.

## D-012 — FlowWink: extraer automatizaciones al Bridge, sin Supabase

**Estado:** APPROVED
**Fecha:** 2026-08-04
**Decisión:** El propietario rechaza trabajar con Supabase y selecciona extraer las automatizaciones de FlowWink (licencia MIT, repo público `magnusfroste/flowwink` v3.0.0, ya vendorizado y al día) reimplementando su lógica de negocio sobre el motor del Bridge (PostgreSQL + Redis + outbox + scheduler pull + aprobaciones), con proveedores locales y contratos donde un efecto externo requiera SaaS. Dominios seleccionados por el propietario: Finanzas y facturación, Presupuestos y contratos, Automatizaciones y eventos, Comunicaciones, Agentes e IA, y Contenido y SEO. No se levanta Supabase ni se integra FlowWink como plataforma paralela (evita un segundo silo de datos). Cada port entra como tarea con sus gates (idempotencia, aprobación humana para efectos financieros, auditoría, Decimal) y su test; se registra con atribución MIT. Orden de ejecución: primero lo que encaja sin SaaS externo (recordatorios de expiración de quotes, dunning, router de email con proveedor local, sweep de automatizaciones, PDF de factura, webhook saliente); Agentes/IA y Contenido/SEO quedan para lotes posteriores por depender de proveedor LLM (B-006) y de la Fase SEO diferida.
