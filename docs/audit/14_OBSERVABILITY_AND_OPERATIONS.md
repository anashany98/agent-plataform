> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# 14 - Observabilidad y operación

## Veredicto

La observabilidad es **NOT IMPLEMENTED** como sistema. Hay health checks y registros puntuales, pero no collector, dashboards, alertas, tracing, SLO ni runbooks operativos probados.

## Inventario

| Control | Estado | Evidencia/gap |
|---|---|---|
| Logs de aplicación | PARTIALLY VERIFIED | stdout de Uvicorn/Rails/Node; no formato uniforme ni centralización |
| Auditoría Bridge | PARTIALLY VERIFIED | Tabla `audit_logs`, hoy 0 filas; mutable/sin retención/redacción |
| Correlation ID | CONFIGURED ONLY | Algunos flujos lo guardan; no propagación vendor |
| Métricas | CONFIGURED ONLY | Endpoint auth con contadores; no formato/scrape/dashboard |
| Tracing | NOT IMPLEMENTED | Sin OpenTelemetry ni spans |
| Health | BROKEN | Proxy/CW; Bridge `/health` 200 degradado |
| Readiness | PARTIALLY VERIFIED | `/ready` correcto, pero Compose no lo usa |
| Dashboards | NOT IMPLEMENTED | Portal no sustituye dashboard técnico |
| Alertas | NOT IMPLEMENTED | Ningún canal/regla |
| Costes | BROKEN | Estimador 0 y budget inerte |
| Runbooks | CONFIGURED ONLY | Docs/scripts sin ensayo |

## Detectabilidad de incidentes

| Evento | ¿Detectable hoy? | Estado |
|---|---|---|
| Chat sin respuesta | Solo revisión manual de logs | BROKEN |
| Pedido duplicado/incorrecto | Query manual posterior | BROKEN |
| Modelo no disponible | Error de request/log | PARTIALLY VERIFIED |
| Webhook fallido | Logs dispersos, sin retry/alerta | BROKEN |
| Worker detenido | Docker health/ps manual | PARTIALLY VERIFIED |
| DB lenta | No métricas de query/pool | NOT IMPLEMENTED |
| Redis caído | Health Docker, sin alerta | PARTIALLY VERIFIED |
| Backup fallido | Exit code manual | CONFIGURED ONLY |
| Coste anómalo | No; todos los costes son 0 | BROKEN |
| RAG sin evidencia | Respuesta contiene abstención, sin agregado | PARTIALLY VERIFIED |
| Acceso no autorizado | 401/audit parcial, sin SIEM | PARTIALLY VERIFIED |
| Certificado/disco | No monitor | NOT IMPLEMENTED |

## Health-check defects

- Nginx master vivo sin workers figura `running`; health genera procesos huérfanos.
- Chatwoot PID stale no tiene autocorrección.
- Bridge marca container healthy con `/health` aunque una DB fallida produciría body degradado/HTTP 200.
- Activepieces health no detecta loop Socket.IO/tráfico Redis.
- No se monitoriza profundidad de cola, edad de job, tasa de retry, frescura catálogo, reserva expirada ni respuesta Chatwoot.

## Baseline recomendada para piloto

1. Logs JSON con timestamp UTC, level, installation, request/correlation/delivery ID; redacción de tokens/PII.
2. Métricas RED/USE: requests, errores, latencia, CPU/RAM/PID, DB pool/query, Redis, colas y egress.
3. Métricas negocio: consulta→respuesta, quote→confirm, deduplicación, frescura precio/stock, handoff y abstención.
4. Coste real por proveedor/modelo y límites duros.
5. Alertas P1: proxy/Chatwoot/worker, webhook backlog, error proveedor, backup, disco/certificado y coste.
6. Dashboard por cliente sin centralizar contenido privado.
7. Runbooks probados para reinicio, proveedor caído, restore, rollback y kill switch.

## Archivos revisados, riesgos y pendiente

Health checks, logs focalizados, audit/cost code, scripts y documentación. Sin observabilidad, soporte no puede prometer SLA ni detectar el flujo roto actual. Implementación y soak test quedan pendientes.
