> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# 07 - Build y ejecución

## Resumen

| Actividad | Estado | Evidencia |
|---|---|---|
| `docker compose --profile full config --quiet` | VERIFIED | Código 0; 14 servicios, 3 redes y 9 volúmenes |
| Runtime heredado | BROKEN | 12 healthy, Chatwoot reiniciando, proxy unhealthy |
| Build `--no-cache --pull` | BLOCKED | Cancelado al alcanzar 95,3 % RAM y 1,49 GiB libres |
| `up/start` posterior | BLOCKED | Imágenes anteriores arrancaron; Chatwoot volvió a unhealthy y RAM subió a 95,8 %, por lo que no era seguro continuar |
| Estado al cerrar pruebas Docker | BLOCKED | Stack `agent-platform-fixed` detenido deliberadamente; volúmenes intactos |

No se declara tiempo de build ni imagen nueva porque BuildKit no terminó. El bloqueo es de recursos del host, no prueba de compilación fallida.

## Servicios observados antes del cierre

| Servicio | Runtime observado | Estado | Evidencia funcional |
|---|---|---|---|
| reverse-proxy | Running/unhealthy; solo master, sin workers | BROKEN | No atiende tráfico útil |
| portal | Healthy | PARTIALLY VERIFIED | Upstream estático y build; UX dinámica bloqueada |
| bridge-api | Healthy | PARTIALLY VERIFIED | `/health`, `/ready`, login y dashboard respondieron |
| bridge-db | Healthy | VERIFIED | Consultas reales y recuentos reproducidos |
| bridge-redis | Healthy | CONFIGURED ONLY | Sin flujo funcional verificado |
| flowwink-app | Healthy Nginx | BROKEN | SPA servida, pero Supabase está vacío |
| chatwoot-web | Restarting/unhealthy; 43 reinicios en última captura | BROKEN | PID obsoleto impide Rails |
| chatwoot-worker | Healthy en baseline | PARTIALLY VERIFIED | Arranque observado, sin conversación e2e |
| chatwoot-db | Healthy; DB vacía | VERIFIED | Esquema y recuentos consultados |
| chatwoot-redis | Healthy | CONFIGURED ONLY | Sin flujo funcional verificado |
| activepieces-app | Healthy | CONFIGURED ONLY | Sin proyectos ni flujos |
| activepieces-worker | Healthy con errores de polling previos | BROKEN | Sin ejecución real y con errores RPC/polling |
| activepieces-db | Healthy; DB vacía | VERIFIED | 79 tablas y cero filas consultadas |
| activepieces-redis | Healthy | CONFIGURED ONLY | Sin flujo funcional verificado |

## Causas raíz confirmadas

### Reverse proxy

- Compose: `cap_drop: ALL`, `cap_add: [CHOWN, SETGID]`.
- Nginx: `user nginx`; logs: `setuid(101) failed (1: Operation not permitted)`.
- Solo existe el proceso master. Cada health check deja procesos `wget` esperando; se observaron decenas.
- Aunque Compose declara red `public` y puerto `9000:8080`, el contenedor observado solo estaba unido a `internal` y sin binding. El 9000 pertenece a otro stack fuera de alcance.

### Chatwoot Web

- Tras un reinicio de Docker queda `/app/tmp/pids/server.pid` con PID 1.
- Rails aborta: `A server is already running (pid: 1, file: /app/tmp/pids/server.pid)`.
- El comando de arranque no valida/elimina el PID obsoleto.

### Egress

`bridge-api`, Chatwoot y Activepieces solo tienen rutas a `172.21.0.0/16` y `172.22.0.0/16`, sin default gateway. Una llamada desde Bridge a Ollama produjo `httpx.ConnectError: [Errno 101] Network is unreachable`. Esto afecta también APIs cloud, PrestaShop/GHL fuera de esas redes, webhooks salientes y conectores.

## Recursos medidos

Instantánea antes de detener el stack:

- Activepieces app: 50,55 % CPU, 945,8 MiB; tráfico acumulado 1,56 GB/14,4 GB.
- Activepieces Redis: 37,08 % CPU; tráfico inverso 14,4 GB/1,56 GB.
- Chatwoot worker: 38,74 % CPU, 499,6 MiB.
- Bridge: 221 MiB; Activepieces worker: 157,2 MiB.
- No se interpreta como consumo estable por cliente: la captura coincide con errores/reconexiones.
- Ningún servicio tenía límite CPU, memoria o PID.

El build elevó el host de 81,2 % a 95,3 % de RAM usada. Un intento de restaurar el stack alcanzó 95,8 %. Se detuvo según la regla de auditoría. No se ejecutó carga.

## Imágenes existentes

| Imagen | Tamaño observado | Usuario |
|---|---:|---|
| Chatwoot local | 685,5 MiB | root |
| Activepieces 0.86.3 | 369,3 MiB | root |
| Bridge | 207,1 MiB | app |
| pgvector (14/15/16) | 146,1–148,9 MiB | root |
| FlowWink | 40,3 MiB | root |
| Portal | 19,6 MiB | root |
| Nginx proxy | 19,5 MiB | root |
| Redis | 15,5 MiB | root |

## Datos reales de runtime

- Bridge DB: 1 usuario, 25 clientes demo, 100 productos demo; 0 presupuestos, pedidos, reservas, facturas, aprobaciones, documentos, chunks, auditorías e idempotencias.
- Chatwoot: 19 MB, 98 tablas, 0 filas estimadas.
- Activepieces: 13 MB, 79 tablas, 0 filas estimadas.
- Dashboard Bridge: PrestaShop/GHL/Chatwoot `not_configured`; Activepieces `configured` de forma incorrecta pese a API key vacía y DB sin flujos.

## Archivos/logs revisados

Compose/config efectiva, inspect/stats/ps, rutas, tablas y conteos, logs focalizados de proxy, Chatwoot y Activepieces. No se copiaron logs completos.

## Trabajo pendiente

1. Liberar RAM o usar host limpio y puerto no ocupado.
2. Corregir proxy/PID/egress y añadir límites.
3. Repetir build limpio completo, registrar tiempos y hashes.
4. Ejecutar `up`, health/readiness, logs y escaneo de imágenes.
5. No reabrir el stack hasta controlar el consumo y la colisión de puerto.
