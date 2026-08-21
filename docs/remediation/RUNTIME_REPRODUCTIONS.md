> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# Reproducciones de runtime P1

## Alcance

Este documento contrasta exclusivamente:

- `P1-001`: servicios sin egress útil.
- `P1-002`: Chatwoot Web aborta por `server.pid` obsoleto y reinicia.
- `P1-003`: reverse proxy sin workers funcionales por capabilities incompatibles.

Se aplicó investigación de causa raíz sin implementar correcciones. Todas las consultas fueron de solo lectura sobre `docker-compose.yml`, metadatos de contenedores detenidos, redes Docker y logs históricos filtrados. No se arrancó, recreó, ejecutó, detuvo ni modificó ningún contenedor, red o volumen. No se consultaron ni imprimieron valores de entorno.

## Entorno de reproducción

| Campo | Valor observado |
|---|---|
| Captura | 2026-08-02T20:09:25.019+02:00, Europe/Madrid |
| Workspace | `C:\Users\PC\Desktop\PROYECTOS\agent-platform-fixed` |
| Rama | `production-remediation` |
| HEAD al iniciar | `4d4a6e915916467ca45c76a89af058cf7d219a27` |
| Docker cliente/servidor | 29.5.3 / 29.5.3 |
| Proyecto Compose | `agent-platform-fixed` |
| Estado del proyecto | 14 contenedores `exited` |
| RAM durante la captura | 31.46 GiB total; 4.59 GiB libre; 85.4 % usada |
| Puerto 9000 | Ocupado por `agent-platform-reverse-proxy-1`, proyecto externo `agent-platform` |

El puerto ocupado y la presión de memoria son restricciones adicionales para una prueba live segura. El proyecto externo no se modificó.

## Resumen del contraste

| ID | Configuración/inspección | Logs retenidos | Prueba live actual | Estado final de esta reproducción |
|---|---|---|---|---|
| P1-001 | OBSERVADO: servicios de salida solo en redes `internal` | NO OBSERVADO en los logs Docker actualmente retenidos; existe evidencia secundaria previa del error exacto | BLOCKED: contenedores detenidos | BLOCKED |
| P1-002 | OBSERVADO: PID presente, comando sin limpieza y restart policy activa | OBSERVADO: 56 abortos exactos de Rails | BLOCKED: no se ejecutaron los diez ciclos requeridos | BLOCKED |
| P1-003 | OBSERVADO: `cap_drop=ALL`, sin `CAP_SETUID` | OBSERVADO: 72 errores `setuid` y 72 workers fatales | BLOCKED: no es posible enumerar procesos en un contenedor detenido | BLOCKED |

`BLOCKED` significa que el defecto permanece abierto hasta ejecutar el criterio live indicado. No significa que la evidencia histórica sea inexistente.

---

## P1-001 — Egress ausente

### Hipótesis investigada

Los servicios que necesitan acceso saliente están conectados únicamente a redes Docker marcadas `Internal=true`. La ausencia de una red de egress o gateway autorizado impide alcanzar Ollama externo, APIs cloud, PrestaShop/GHL fuera de las redes Compose y webhooks salientes.

### Hechos observados

1. `docker-compose.yml` declara:
   - red `internal` con `internal: true` en la línea 33;
   - red `data` con `internal: true` en la línea 36;
   - red `public` sin esa restricción.
2. La configuración fuente conecta `bridge-api`, `chatwoot-web`, `chatwoot-worker`, `activepieces-app` y `activepieces-worker` solamente a `internal` y `data`.
3. La inspección de los contenedores existentes coincide con esa asignación:
   - Bridge API: `agent-platform-fixed_data`, `agent-platform-fixed_internal`.
   - Chatwoot Web/Worker: `agent-platform-fixed_data`, `agent-platform-fixed_internal`.
   - Activepieces App/Worker: `agent-platform-fixed_data`, `agent-platform-fixed_internal`.
4. La inspección de redes devuelve:

   | Red | `Internal` | Endpoints running |
   |---|---:|---:|
   | `agent-platform-fixed_data` | true | 0 |
   | `agent-platform-fixed_internal` | true | 0 |
   | `agent-platform-fixed_public` | false | 0 |

5. Los cinco contenedores están detenidos. El intento de consultar `ip route` sin arrancar Bridge devuelve `container ... is not running`, código 1.

### No observado en la retención actual

Se buscaron de forma exacta y sanitizada los patrones `Network is unreachable`, `Errno 101`, `ENETUNREACH`, `EHOSTUNREACH`, `No route to host`, fallos de resolución y `ENOTFOUND` en los logs actualmente retenidos de Bridge, Chatwoot Web/Worker y Activepieces App/Worker. El resultado fue cero coincidencias en los cinco contenedores.

Esto impide presentar el error de red como reproducido desde los logs Docker actuales.

### Evidencia secundaria existente

El artefacto anterior `docs/audit/evidence/RUNTIME_LOG_EXCERPTS.md` conserva el extracto sanitizado:

```text
httpx.ConnectError: [Errno 101] Network is unreachable
```

`docs/audit/07_BUILD_AND_RUNTIME_REPORT.md` registra que apareció durante una llamada desde Bridge a Ollama y que las rutas observadas se limitaban a `172.21.0.0/16` y `172.22.0.0/16`. El comando original, timestamp y salida completa no se conservaron en esos artefactos; por ello se tratan como evidencia histórica secundaria, no como nueva reproducción independiente.

### Causa probable separada del hecho

**Causa probable, confianza alta:** topología internal-only sin ruta de egress autorizada. La configuración observada es suficiente para explicar el error histórico y afecta a todos los servicios con la misma asignación de redes.

**Aún no demostrado live:** tabla de rutas efectiva, resolución DNS, conectividad TLS a un destino sandbox autorizado y denegación de destinos no autorizados tras aplicar una solución. Las credenciales ausentes son un bloqueo distinto y no explican un error de capa de red `Errno 101`.

### Criterio de reproducción/verificación live posterior

1. Liberar una ventana de capacidad sin tocar otros proyectos.
2. Levantar únicamente el perfil mínimo necesario en una red de prueba aislada.
3. Capturar `ip route` y resolución DNS desde Bridge, Chatwoot y Activepieces.
4. Usar un endpoint sandbox controlado, sin credenciales reales, para comprobar DNS y TLS saliente.
5. Demostrar que un destino explícitamente autorizado es accesible.
6. Demostrar que destinos no autorizados, metadata cloud y rangos bloqueados siguen inaccesibles.
7. Ejecutar la misma prueba dos veces y conservar comando, timestamp, exit code y correlation ID.
8. No marcar `VERIFIED` hasta obtener resultados positivos y negativos reproducibles mediante la política de allowlist.

---

## P1-002 — Chatwoot Web y PID obsoleto

### Hipótesis investigada

Rails encuentra `/app/tmp/pids/server.pid` de una ejecución anterior. El comando de arranque no valida ni elimina ese PID, Rails aborta y `restart: unless-stopped` vuelve a ejecutar el mismo comando contra la misma capa escribible.

### Hechos observados

1. El contenedor `agent-platform-fixed-chatwoot-web-1` está `exited`, con:
   - último exit code: 137;
   - `RestartCount`: 6;
   - health histórico: `unhealthy`;
   - restart policy: `unless-stopped`.
2. El comando instanciado es:

   ```text
   sh -c bundle exec rails db:chatwoot_prepare && bundle exec rails s -p 3000 -b 0.0.0.0
   ```

   No contiene validación o retirada de `tmp/pids/server.pid`.
3. `docker diff` confirma estas entradas añadidas en la capa escribible del contenedor:

   ```text
   A /app/tmp/pids
   A /app/tmp/pids/server.pid
   ```

4. El log retenido contiene **56** coincidencias exactas de:

   ```text
   A server is already running (pid: 1, file: /app/tmp/pids/server.pid).
   ```

5. Ventana observada:
   - primera coincidencia: `2026-08-02T14:04:59.430928341Z`;
   - última coincidencia: `2026-08-02T15:03:22.591414596Z`.

El contador `RestartCount=6` es el metadato actual de Docker y no se equipara a las 56 líneas históricas. Tampoco se atribuye automáticamente el exit 137 a OOM: solo demuestra que la última terminación no fue una salida normal de Rails.

### No observado / bloqueado

- No se leyó el contenido del PID ni se comprobó si correspondía a un proceso válido en cada intento.
- No puede consultarse el proceso PID 1 actual porque el contenedor está detenido.
- No se ejecutaron recreaciones, reboots o ciclos de restart.
- No se ha demostrado todavía que una corrección sobreviva diez ciclos limpios.

### Causa probable separada del hecho

**Causa probable, confianza alta:** archivo PID conservado en la capa escribible más comando de arranque sin manejo de PID obsoleto. La restart policy amplifica el fallo al repetir la misma precondición.

**Posible disparador, no demostrado:** una terminación no graceful pudo dejar el archivo. El exit 137 actual es compatible con esa clase de terminación, pero no prueba cuál fue el disparador original.

### Criterio de reproducción/verificación live posterior

1. Preparar una prueba aislada con DB/Redis de Chatwoot disponibles y sin datos reales.
2. Arrancar Chatwoot Web y esperar health/readiness funcional.
3. Ejecutar al menos diez ciclos combinados de stop/start y recreate.
4. Incluir un ciclo de terminación no graceful controlada para comprobar recuperación.
5. Tras cada ciclo, verificar:
   - un único servidor Rails activo;
   - PID file coherente con el proceso;
   - ausencia del mensaje `A server is already running`;
   - restart count estable tras alcanzar estado sano;
   - endpoint funcional, no solo proceso presente.
6. Verificar graceful shutdown y que un PID legítimo no se elimina mientras el proceso correspondiente sigue vivo.
7. Conservar logs, exit codes, tiempos de arranque y estado de health de cada ciclo.

---

## P1-003 — Nginx sin workers funcionales

### Hipótesis investigada

El proxy elimina todas las Linux capabilities y devuelve solo `CHOWN` y `SETGID`. Nginx arranca con master privilegiado, intenta cambiar sus workers al UID 101 y falla porque `CAP_SETUID` no está disponible.

### Hechos observados

1. `docker-compose.yml` declara para `reverse-proxy`:

   ```yaml
   cap_add:
     - CHOWN
     - SETGID
   cap_drop:
     - ALL
   ```

2. La instancia detenida coincide:
   - `CapAdd`: `CAP_CHOWN`, `CAP_SETGID`;
   - `CapDrop`: `ALL`;
   - `CAP_SETUID`: ausente;
   - `Config.User`: vacío, por lo que la imagen usa su usuario predeterminado;
   - comando: `nginx -g daemon off;`.
3. El log retenido contiene:
   - **72** errores exactos `setuid(101) failed (1: Operation not permitted)`;
   - **72** salidas `worker process ... exited with fatal code 2 and cannot be respawned`;
   - 75 líneas de intento de arranque de workers.
4. Ventana de errores `setuid` observada:
   - primera: `2026-07-31T12:51:28.012329272Z`;
   - última: `2026-08-02T15:02:46.563088405Z`.
5. El último worker registrado fue el PID 58 y terminó con código fatal 2 sin posibilidad de respawn.
6. El health check instanciado es:

   ```text
   wget -q -O - http://127.0.0.1:8080/healthz || exit 1
   ```

   El último estado conservado es `unhealthy`, failing streak 2 y timeout de 5 segundos.
7. El contenedor está detenido con exit code 0. `docker top` devuelve código 1 porque el contenedor no está running.

### No observado / bloqueado

- No se puede enumerar ahora el master y sus workers.
- No se puede demostrar el número estable de workers tras varios health intervals.
- No se comprobó HTTP a través del proxy ni routing hacia upstreams.
- No se comprobó acumulación de procesos `wget` en esta captura detenida.
- El puerto configurado 9000 está ocupado por otro proyecto y no puede usarse para una prueba live sin coordinación o puerto alternativo.

### Causa probable separada del hecho

**Causa probable, confianza muy alta:** ausencia de `CAP_SETUID` después de `cap_drop: ALL`. El error EPERM se produce exactamente durante `setuid(101)` y las salidas fatales de workers están emparejadas en los logs.

La solución concreta aún debe probarse de manera aislada. Añadir capabilities no es la única opción: también puede validarse una imagen/configuración Nginx realmente unprivileged. Este documento no selecciona ni aplica una corrección.

### Criterio de reproducción/verificación live posterior

1. Resolver el puerto 9000 sin detener el proyecto externo, o usar un puerto de prueba alternativo.
2. Arrancar únicamente las dependencias mínimas del proxy en un entorno aislado.
3. Verificar capabilities efectivas y usuario mediante inspección segura.
4. Enumerar procesos después de varios health intervals y demostrar master/workers estables conforme al diseño elegido.
5. Exigir cero errores `setuid`, cero workers con fatal code 2 y cero respawns inesperados.
6. Verificar `/healthz` y una ruta real a upstream con HTTP esperado.
7. Confirmar health `healthy`, restart count estable y ausencia de procesos de health huérfanos durante un soak mínimo de diez minutos.
8. Repetir recreate/restart al menos diez veces y conservar evidencia de cada ciclo.

---

## Comandos reproducibles y sanitizados

Los siguientes comandos proyectan exclusivamente metadatos necesarios. No muestran `.Config.Env`, `.env` ni la salida completa de `docker inspect`.

### Contexto

```powershell
Get-Location
git status --short --branch
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
docker version --format 'Client={{.Client.Version}};Server={{.Server.Version}}'
docker ps -a --filter 'label=com.docker.compose.project=agent-platform-fixed' `
  --format '{{.Names}}|{{.Status}}'
```

### P1-001

```powershell
docker network inspect `
  --format 'Name={{.Name}} Internal={{.Internal}} Driver={{.Driver}}' `
  agent-platform-fixed_data agent-platform-fixed_internal agent-platform-fixed_public

docker inspect `
  --format 'Name={{.Name}} Status={{.State.Status}} Networks={{range $n, $_ := .NetworkSettings.Networks}}{{$n}},{{end}}' `
  agent-platform-fixed-bridge-api-1 `
  agent-platform-fixed-chatwoot-web-1 `
  agent-platform-fixed-chatwoot-worker-1 `
  agent-platform-fixed-activepieces-app-1 `
  agent-platform-fixed-activepieces-worker-1

$patterns = 'Network is unreachable|Errno 101|ENETUNREACH|EHOSTUNREACH|No route to host|ENOTFOUND'
docker logs --timestamps agent-platform-fixed-bridge-api-1 2>&1 |
  Select-String -Pattern $patterns

Select-String -Path docs/audit/evidence/RUNTIME_LOG_EXCERPTS.md `
  -Pattern 'Network is unreachable'
```

### P1-002

```powershell
docker inspect `
  --format 'Status={{.State.Status}} Exit={{.State.ExitCode}} RestartCount={{.RestartCount}} RestartPolicy={{.HostConfig.RestartPolicy.Name}} Cmd={{json .Config.Cmd}}' `
  agent-platform-fixed-chatwoot-web-1

docker diff agent-platform-fixed-chatwoot-web-1 2>&1 |
  Select-String -Pattern '/app/tmp/pids|server\.pid'

$pidLines = @(docker logs --timestamps agent-platform-fixed-chatwoot-web-1 2>&1 |
  Select-String -Pattern 'A server is already running \(pid: 1, file: /app/tmp/pids/server\.pid\)')
$pidLines.Count
$pidLines | Select-Object -First 1
$pidLines | Select-Object -Last 1
```

### P1-003

```powershell
docker inspect `
  --format 'Status={{.State.Status}} CapsAdd={{json .HostConfig.CapAdd}} CapsDrop={{json .HostConfig.CapDrop}} User={{json .Config.User}} Cmd={{json .Config.Cmd}} Health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' `
  agent-platform-fixed-reverse-proxy-1

$proxyLog = @(docker logs --timestamps agent-platform-fixed-reverse-proxy-1 2>&1)
@($proxyLog | Select-String -Pattern 'setuid\(101\) failed \(1: Operation not permitted\)').Count
@($proxyLog | Select-String -Pattern 'worker process [0-9]+ exited with fatal code 2 and cannot be respawned').Count

docker top agent-platform-fixed-reverse-proxy-1
docker ps --filter 'publish=9000' `
  --format '{{.Names}}|{{.Label "com.docker.compose.project"}}|{{.Ports}}'
```

## Conclusión

Los tres P1 permanecen abiertos. P1-002 y P1-003 tienen reproducción histórica directa y causas altamente respaldadas por estado más logs. P1-001 conserva una topología que explica el defecto y evidencia secundaria del error, pero la retención Docker actual ya no contiene la línea y la prueba live está bloqueada. Ningún caso cumple todavía el criterio de aceptación de `TASKS.md` ni puede marcarse `VERIFIED`.
