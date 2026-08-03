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
