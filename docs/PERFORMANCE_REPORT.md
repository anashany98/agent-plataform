# Informe de rendimiento y capacidad

**Corte:** 2026-08-15  
**Estado:** `PENDING` para producción; no existe aún un ensayo de carga/soak aceptado sobre la candidata final.

## Conclusión

El código incorpora límites, paginación, búsqueda PostgreSQL, TF-IDF acotado, rate limit Redis, lotes de outbox y recursos máximos por contenedor. Esto reduce fallos no controlados, pero no constituye una cifra de capacidad. No se publican RPS ni latencias SLO como verificadas hasta ejecutar el perfil `production` desde cero con datos representativos.

## Presupuesto de recursos configurado para core

| Servicio | CPU máxima | Memoria máxima | PIDs |
|---|---:|---:|---:|
| TLS proxy | 0,50 | 128 MiB | 64 |
| Reverse proxy | 0,50 | 128 MiB | 64 |
| Portal | 0,50 | 256 MiB | 64 |
| Bridge API | 1,00 | 768 MiB | 128 |
| PostgreSQL Bridge | 1,00 | 512 MiB | 128 |
| Redis Bridge | 0,50 | 128 MiB | 64 |
| **Total de límites** | **4,00 CPU** | **1.920 MiB** | **512** |

Los límites Compose son techos, no reservas ni sizing probado. Docker Compose aplica `deploy.resources` según el motor/modo utilizado; el preflight y el ensayo deben confirmar su enforcement real.

El host auditado dispone de CPU/RAM holgadas, pero solo unos 16,9 GiB libres en `C:`. Está por debajo de los 30 GiB recomendados y muy cerca del bloqueo de 15 GiB; no es margen seguro para build, imágenes, backups y restore simultáneos. Libere espacio o use un volumen dedicado antes del gate final.

## Límites funcionales

| Control | Valor/base | Riesgo controlado |
|---|---|---|
| Rate limit general | 120 req/min por defecto | abuso y saturación básica |
| Login | 8 intentos/900 s por defecto | fuerza bruta |
| Backend de rate limit | Redis, fail-closed en production | consistencia multiworker |
| Outbox | lote 16, máximo 8 intentos | ráfagas y poison messages |
| LLM input/output | 131.072 bytes / 1.024 tokens por defecto | coste/memoria |
| Coste LLM diario | 25 USD por defecto | gasto inesperado |
| Upload RAG | 25 MiB por archivo | memoria/disco |
| TF-IDF local | 5.000 chunks, 20 MiB corpus, 4.096 features | tiempo/memoria |
| Retención lifecycle | 30 días; máximo 365 | crecimiento de datos |
| Tareas programadas | intervalo 60 s–30 días | tormentas de scheduling |

Los valores deben adaptarse al contrato del cliente únicamente después de medir; aumentar un límite no es una corrección de rendimiento.

## Plan de carga obligatorio

### Dataset

- catálogo con volumen y distribución reales;
- clientes/leads/presupuestos representativos;
- documentos pequeños, medianos y de 25 MiB;
- corpus TF-IDF cercano a límites;
- outbox con éxitos, retry y DLQ;
- dos instalaciones para detectar interferencia.

### Escenarios

1. Lecturas mixtas: dashboard, catálogo, clientes, estados y contenido público.
2. Escrituras idempotentes: clientes, leads y presupuestos con 10 % de retries.
3. Confirmación concurrente del mismo presupuesto y aprobación con CAS.
4. Ingesta/consulta RAG concurrente con navegación Portal.
5. Sweep/scheduler/outbox bajo tráfico normal.
6. Backup con quiesce y medición del impacto.
7. Reinicio de API/Redis y recuperación de leases/retries.
8. PostgreSQL indisponible y restaurado; comprobar fail-closed/readiness.
9. Soak mínimo de 4 h, idealmente 24 h para el primer cliente.

### Métricas a capturar

- throughput y concurrencia;
- p50, p95 y p99 por ruta/clase;
- tasa de 2xx, 4xx esperados, 429 y 5xx;
- CPU, RSS, PIDs, disco, I/O y conexiones DB/Redis;
- backlog, edad máxima de outbox y DLQ;
- tiempos de startup, backup, restore y rollback;
- fugas de memoria/FD y crecimiento de volúmenes;
- exactitud: cero duplicados y cero confirmaciones dobles.

## Criterios de aceptación propuestos

El propietario debe fijar SLO contractuales antes del ensayo. Como gate técnico inicial: 0 duplicados/aislamiento, error inesperado <1 %, p95 estable sin degradación creciente, utilización sostenida <70 % de cada límite, backlog recuperado tras la perturbación y ausencia de OOM/restart no planificado. Estos valores son objetivos de aceptación, **no resultados medidos**.

## Evidencia histórica

Existen microbenchmarks antiguos de búsqueda/indexación en documentos de trabajo, pero no corresponden al commit, dataset, contenedor ni host de la candidata. Se conservan como evidencia exploratoria y quedan **SUPERSEDED para decisiones de capacidad**.

El stop-ship SS-06 solo puede cerrarse adjuntando el reporte de la herramienta, configuración, dataset anonimizado, timestamps, commit, imágenes y gráficos/series crudas.
