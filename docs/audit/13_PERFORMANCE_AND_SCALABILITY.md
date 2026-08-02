# 13 - Rendimiento y escalabilidad

## Alcance medido

No se ejecutó carga. El precheck detectó consumo anómalo y el build llevó la RAM del host por encima del 90 %, por lo que una prueba de volumen habría violado el protocolo. Todo dato distinto de las instantáneas siguientes es análisis, no benchmark.

### Instantánea observada

- Host: 31,46 GiB; 5,91 GiB libres antes del build (81,2 % usado).
- Docker Desktop: 24 CPU y 15,35 GiB.
- Activepieces app: 50,55 % CPU/945,8 MiB; Redis: 37,08 % CPU; Chatwoot worker: 38,74 %/499,6 MiB.
- Bridge: 221 MiB; Activepieces worker: 157,2 MiB.
- Tráfico acumulado Activepieces↔Redis: aproximadamente 14,4 GB en una dirección y 1,56 GB en la otra durante el uptime visible.
- Build limpio: cancelado a 95,3 % RAM/1,49 GiB libre. Arranque posterior: 95,8 %.

Estas cifras coinciden con loops/reconexiones y no representan idle estable.

## Cuellos de botella de código

| Área | Evidencia | Impacto |
|---|---|---|
| RAG | Carga todos los chunks; N+1 de documentos; TF-IDF recalculado | Crece con corpus y bloquea worker |
| PrestaShop sync | Enriquecimiento secuencial por producto/variante/precio/stock | Latencia y rate limits |
| Import | Queries de existencia por fila, hasta 10.000 | N+1 y transacción larga |
| Costes | Carga todos los AuditLog | Memoria/latencia creciente |
| Bridge | Un proceso Uvicorn, agentes en memoria | Sin HA; estado inconsistente con réplicas |
| Rate limit | Diccionario en memoria | No escala horizontalmente |
| DB | Sin pool tuning ni pgbouncer | Riesgo por múltiples instancias |
| Reservas/aprobación | Locks parciales o ausentes | Contención/races |
| Logs/retención | Sin políticas | Disco/DB sin límite |

## Capacidad por número de clientes

| Instalaciones | Evidencia | Evaluación honesta |
|---:|---|---|
| 1 | Runtime actual de 14 servicios | BROKEN; ni una instalación completa es estable/funcional |
| 5 | Extrapolación arquitectónica, no medida | BLOCKED/alto riesgo en un solo host; 70 servicios y vendor pesado |
| 10 | No medida | NOT FEASIBLE con operación manual/host actual |
| 25 | No medida | Requiere orquestación, observabilidad, capacity plan y servicios compartidos/gestionados selectivos |
| 50 | No medida | Requiere plataforma operativa dedicada, automatización y HA |
| 100 | No medida | No justificable con arquitectura/negocio actuales; evaluar SaaS o clusters regionales solo con demanda |

No se estiman RPS, conversaciones/segundo, RPO/RTO ni coste monetario sin medición y precios operativos.

## Recomendaciones escalonadas

| Cuándo | Recomendación | Problema | Prioridad | Coste relativo | Riesgo/alternativa sencilla |
|---|---|---|---|---|---|
| Ahora | Retirar FlowWink/AP del camino MVP | Consumo y complejidad sin valor | P0/P1 | S | Mantener jobs Bridge explícitos |
| Ahora | Límites CPU/RAM/PID y health correctos | Agotamiento host | P1 | S | Hosts separados si vendor no cabe |
| Ahora | Batch/cache con TTL y frescura | N+1/stock stale | P1 | M | Consulta directa solo para cotización |
| 1–5 clientes | Redis distribuido para rate/idempotencia/colas | Multiworker | P1 | M | Un Bridge worker mientras piloto |
| 1–5 | Métricas de latencia/cola/coste | Capacity desconocida | P1 | M | OpenTelemetry mínimo + Prometheus |
| 5–10 | DB gestionada o PGBouncer, object storage | Backups/pool/uploads | P2 | M/L | DB por host si compliance exige aislamiento |
| 10–25 | Orquestador y releases inmutables | Operación manual | P2 | L | VM por cliente automatizada |
| 25+ | Réplicas, HA, CDN, regionalización | Disponibilidad/latencia | P2 | L/XL | Solo tras SLO y demanda demostrados |
| 50–100 | Evaluar control plane/SaaS compartido | Coste operativo | P2 | XL | Mantener data plane single-tenant |

## Pruebas requeridas

- Idle estable 60 min sin reconexiones; arranque en frío y reinicio host.
- Conversación e2e con límites y percentiles; fallo de modelo/proveedor.
- Import 1k/10k, sync catálogo, RAG por tamaños y backup/restore.
- Soak 24 h con alertas, pérdida de conexión y crecimiento de DB/logs.
- Solo después, carga incremental con stop CPU 95 %/RAM 90 %.

## Archivos revisados, riesgos y pendiente

Código de queries, adapters, workers, Compose/stats/DB. El riesgo es escalar una topología inestable multiplicando coste y fallos. Benchmarks quedan BLOCKED hasta estabilizar y aislar recursos.

