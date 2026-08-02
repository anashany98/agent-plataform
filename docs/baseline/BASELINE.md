# Baseline técnico de producción

## Alcance y criterio de evidencia

- **Fase:** 0 — Baseline.
- **Captura principal:** 2026-08-02T19:50:14.781+02:00 (Europe/Madrid).
- **Workspace:** `C:\Users\PC\Desktop\PROYECTOS\agent-platform-fixed`.
- **Proyecto Compose:** `agent-platform-fixed`.
- **Método:** consultas de solo lectura sobre host, Git, Docker, Compose y logs de arranque ya existentes.
- **Restricciones aplicadas:** no se arrancó ningún servicio, no se ejecutaron builds ni pruebas pesadas, no se inspeccionaron valores de entorno y no se tocaron redes, contenedores o volúmenes.

`VERIFIED` en este documento solo confirma la observación concreta indicada. No implica que el servicio, el flujo E2E o la plataforma estén operativos.

## Resumen ejecutivo

| Área | Estado | Evidencia y alcance |
|---|---|---|
| Workspace | VERIFIED | `Get-Location` devolvió la ruta esperada. |
| Git | VERIFIED | Rama `production-remediation`, HEAD `ed77056c9d8084ac7c23b587199938fd4cc346fe`. El árbol ya contenía cambios concurrentes antes de crear este documento y se conservaron. |
| Host | VERIFIED | Windows 11 Pro build 26200; CPU, RAM, disco y GPU consultados directamente. |
| Docker Engine | VERIFIED | Cliente y servidor 29.5.3; contexto `desktop-linux`; daemon accesible. |
| Compose estático | VERIFIED | `docker compose --profile '*' config --quiet` terminó con código 0. Esto valida el renderizado, no el arranque. |
| Runtime del proyecto | BLOCKED | Los 14 contenedores del proyecto están detenidos. No se arrancaron por el alcance de esta fase y por la presión de memoria del host. |
| Persistencia Docker | VERIFIED | Se observaron las 9 volumes nombradas del proyecto; no se montaron ni se inspeccionó su contenido. |
| PostgreSQL y Redis | BLOCKED | No hay consulta live. Las versiones se obtuvieron de tags de imagen y líneas de logs de arranques anteriores. |
| Puerto de entrada | BLOCKED | El puerto 9000 está ocupado por el reverse proxy de otro proyecto fuera de alcance. |

## Git y punto de recuperación

| Campo | Valor |
|---|---|
| Git | `git version 2.52.0.windows.1` |
| Rama | `production-remediation` |
| Commit completo | `ed77056c9d8084ac7c23b587199938fd4cc346fe` |
| Commit corto | `ed77056` |
| Fecha del commit | `2026-08-02T19:46:13+02:00` |
| Mensaje | `chore(devops): create pre-remediation recovery baseline` |

Contexto recibido de la coordinación: este repositorio Git se inicializó inmediatamente antes de la remediación; el workspace no contenía `.git` con anterioridad. Esa ausencia histórica no puede demostrarse desde el repositorio recién creado y se conserva como contexto, no como hallazgo reproducido.

El árbol de trabajo no estaba limpio durante la captura. Se observaron cambios concurrentes en documentos de control (`TASKS.md`, `STATUS.md`, `docs/KNOWN_LIMITATIONS.md`, `BLOCKERS.md`, `CHANGELOG.md`, `DECISIONS.md` y `docs/TEST_EVIDENCE.md`). No se descartó ni sobrescribió ninguno.

## Host

### Sistema y capacidad

| Recurso | Valor observado | Estado |
|---|---|---|
| Sistema operativo | Microsoft Windows 11 Pro, versión 10.0.26200, build 26200, 64 bits | VERIFIED |
| Último arranque reportado | 2026-07-16T07:26:57.5+02:00 | VERIFIED |
| CPU | Intel Core Ultra 9 275HX | VERIFIED |
| CPU lógica/física reportada | 24 núcleos / 24 procesadores lógicos | VERIFIED |
| RAM física total | 31.46 GiB | VERIFIED |
| RAM libre durante la captura | 3.88 GiB | VERIFIED |
| RAM usada durante la captura | 87.7 % | VERIFIED |
| Disco `C:` | 925.14 GiB totales; 130.02 GiB libres; 85.9 % usado | VERIFIED |
| GPU integrada | Intel Graphics, driver 32.0.101.8509 | VERIFIED |
| GPU dedicada | NVIDIA GeForce RTX 5070 Laptop GPU | VERIFIED |
| VRAM NVIDIA | 8151 MiB, obtenidos con `nvidia-smi` | VERIFIED |
| Driver NVIDIA | 610.47, obtenido con `nvidia-smi` | VERIFIED |

La memoria es una medida puntual y puede variar. Su nivel durante la captura desaconseja builds completos o el arranque del stack full sin liberar capacidad primero.

### Toolchain disponible en `PATH`

| Herramienta | Versión observada | Estado |
|---|---|---|
| Git | 2.52.0.windows.1 | VERIFIED |
| Docker CLI | 29.5.3, build d1c06ef | VERIFIED |
| Docker Compose | v5.1.4 | VERIFIED |
| Python | 3.11.7 | VERIFIED |
| Node.js | v24.13.0 | VERIFIED |
| npm | 11.6.2 | VERIFIED |
| pnpm | 10.33.2 | VERIFIED |
| `psql` | No encontrado en el host | BLOCKED |
| `redis-server` | No encontrado en el host | BLOCKED |
| `redis-cli` | No encontrado en el host | BLOCKED |

El `python` resuelto por `PATH` pertenece al entorno Hermes (`...\hermes-agent\venv\Scripts\python.exe`); no se interpreta como runtime fijado por el proyecto.

## Docker Engine

| Campo | Valor observado |
|---|---|
| Cliente | 29.5.3 |
| Servidor | 29.5.3 |
| Contexto | `desktop-linux` |
| Nombre del daemon | `docker-desktop` |
| SO/arquitectura del daemon | Docker Desktop, Linux, x86_64 |
| Storage driver | `overlayfs` |
| Cgroup driver | `cgroupfs` |
| CPU asignada | 24 |
| Memoria asignada | 15.35 GiB |
| Contenedores globales | 81 totales; 57 running; 24 stopped; 0 paused |

Los 57 contenedores activos pertenecen a varios proyectos del host. No se detuvo, reinició ni inspeccionó internamente ninguno de esos proyectos.

## Docker Compose

### Validación y topología renderizada

- `docker compose --profile '*' config --quiet`: **VERIFIED**, código 0.
- Perfiles definidos actualmente: `core`, `full`.
- Servicios renderizados con todos los perfiles: 14.
- Redes declaradas: 3.
- Volúmenes nombrados declarados: 9.
- Único puerto publicado declarado: `9000` del host hacia `8080/tcp` de `reverse-proxy`.

La validación se ejecutó con `--profile '*'` porque todos los servicios están condicionados por perfiles. No se imprimió la configuración resuelta ni sus variables de entorno.

### Servicios

| Servicio | Perfiles | Imagen o build | Redes | Estado instanciado | Último exit code |
|---|---|---|---|---|---:|
| `bridge-api` | core, full | build `bridge-api/Dockerfile` | data, internal | exited | 0 |
| `bridge-db` | core, full | `pgvector/pgvector:pg15` | data | exited | 0 |
| `bridge-redis` | core, full | `redis:7-alpine` | data | exited | 0 |
| `flowwink-app` | core, full | build `vendor/flowwink/Dockerfile` | internal | exited | 0 |
| `portal` | core, full | build `portal/Dockerfile` | internal | exited | 0 |
| `reverse-proxy` | core, full | `nginx:1.25-alpine` | internal, public | exited | 0 |
| `chatwoot-db` | full | `pgvector/pgvector:pg16` | data | exited | 0 |
| `chatwoot-redis` | full | `redis:7-alpine` | data | exited | 0 |
| `chatwoot-web` | full | `agent-platform-fixed-chatwoot:b05f22da` | data, internal | exited | 137 |
| `chatwoot-worker` | full | `agent-platform-fixed-chatwoot:b05f22da` | data, internal | exited | 137 |
| `activepieces-app` | full | `ghcr.io/activepieces/activepieces:0.86.3` | data, internal | exited | 137 |
| `activepieces-db` | full | `pgvector/pgvector:0.8.0-pg14` | data | exited | 0 |
| `activepieces-redis` | full | `redis:7-alpine` | data | exited | 0 |
| `activepieces-worker` | full | `ghcr.io/activepieces/activepieces:0.86.3` | data, internal | exited | 137 |

Los cuatro códigos 137 proceden del último estado conservado y son compatibles con terminación forzada, incluida posible presión de memoria, pero esta fase no reproduce ni atribuye la causa. Los estados de health conservados figuran como `unhealthy` aun estando los contenedores detenidos; son datos históricos/stale y no una prueba live.

### Redes

| Red | Driver | Internal | Attachable | Subred observada | Endpoints running |
|---|---|---:|---:|---|---:|
| `agent-platform-fixed_public` | bridge | no | no | 172.20.0.0/16 | 0 |
| `agent-platform-fixed_internal` | bridge | sí | no | 172.21.0.0/16 | 0 |
| `agent-platform-fixed_data` | bridge | sí | no | 172.22.0.0/16 | 0 |

El Compose renderizado conecta actualmente `reverse-proxy` a `internal` y `public`. El contenedor detenido existente conserva solo `internal` en su inspección, por lo que la topología renderizada y la instancia anterior no coinciden por completo. Se requiere recreación controlada para verificar el estado efectivo, pero no se realizó en esta fase.

### Volúmenes persistentes observados

Todos usan driver local y conservan la etiqueta del proyecto:

1. `agent-platform-fixed_bridge_db_data`
2. `agent-platform-fixed_bridge_redis_data`
3. `agent-platform-fixed_bridge_uploads`
4. `agent-platform-fixed_chatwoot_db_data`
5. `agent-platform-fixed_chatwoot_redis_data`
6. `agent-platform-fixed_chatwoot_storage_data`
7. `agent-platform-fixed_activepieces_db_data`
8. `agent-platform-fixed_activepieces_redis_data`
9. `agent-platform-fixed_activepieces_cache`

La existencia de un volumen no verifica integridad, completitud, backup ni capacidad de restauración. No se montó ni se leyó ningún volumen.

## PostgreSQL y Redis

No existen clientes `psql` o `redis-cli` en el host y los contenedores están detenidos. Para evitar arrancarlos, se extrajo únicamente la última línea de versión de sus logs de arranque ya existentes.

| Componente | Imagen configurada | Versión registrada en logs | Estado de la evidencia |
|---|---|---|---|
| Bridge PostgreSQL | `pgvector/pgvector:pg15` | PostgreSQL 15.18 | VERIFIED |
| Chatwoot PostgreSQL | `pgvector/pgvector:pg16` | PostgreSQL 16.14 | VERIFIED |
| Activepieces PostgreSQL | `pgvector/pgvector:0.8.0-pg14` | PostgreSQL 14.19 | VERIFIED |
| Bridge Redis | `redis:7-alpine` | Redis 7.4.9, 64 bits | VERIFIED |
| Chatwoot Redis | `redis:7-alpine` | Redis 7.4.9, 64 bits | VERIFIED |
| Activepieces Redis | `redis:7-alpine` | Redis 7.4.9, 64 bits | VERIFIED |

Estas versiones están verificadas como evidencia histórica del último arranque observado. La disponibilidad actual, consistencia de datos, extensiones PostgreSQL y conectividad siguen **BLOCKED** hasta una prueba live controlada.

## Puertos

El Compose del proyecto declara el puerto host `9000` para `reverse-proxy`. Durante la captura existían listeners en `::1:9000` y `:::9000`, gestionados por `wslrelay` y `com.docker.backend`.

Docker atribuye la publicación activa a:

| Contenedor | Proyecto Compose | Servicio | Publicación |
|---|---|---|---|
| `agent-platform-reverse-proxy-1` | `agent-platform` | `reverse-proxy` | `0.0.0.0:9000->80/tcp` y `[::]:9000->80/tcp` |

Ese contenedor pertenece a otro workspace y queda fuera de alcance. El proyecto `agent-platform-fixed` no publica puertos actualmente porque está detenido, pero su configuración colisionaría con el puerto ocupado al intentar arrancar `reverse-proxy`. No se modificó el proyecto que mantiene el listener.

## Entradas inspeccionadas

Se comprobó la presencia de los artefactos raíz relevantes sin leer secretos:

- `README.md`
- `docker-compose.yml`
- `.env.example`
- `.dockerignore`
- `bridge-api/Dockerfile` y `bridge-api/.dockerignore`
- `portal/Dockerfile` y `portal/.dockerignore`
- `vendor/flowwink/Dockerfile`
- `vendor/chatwoot/docker/Dockerfile`
- `scripts/`
- auditoría previa bajo `docs/audit/`
- documentación activa de arquitectura y seguridad bajo `docs/`

El inventario detallado, mapa de dependencias y propiedad de datos se registran en sus documentos específicos de Fase 0 y no se duplican aquí.

## Evidencia reproducible

Comandos de solo lectura utilizados:

```powershell
Get-Location
git status --short --branch
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
git log -1 --format='%h|%cI|%s'

Get-CimInstance Win32_OperatingSystem
Get-CimInstance Win32_ComputerSystem
Get-CimInstance Win32_Processor
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3"
Get-CimInstance Win32_VideoController
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits

docker version
docker info
docker context show
docker compose ls --all --format json
docker compose --profile '*' config --quiet
docker compose --profile '*' config --format json
docker ps -a --filter label=com.docker.compose.project=agent-platform-fixed
docker inspect <ids-del-proyecto>
docker network inspect <redes-del-proyecto>
docker volume inspect <volumenes-del-proyecto>
docker ps --filter publish=9000
Get-NetTCPConnection -State Listen -LocalPort 9000
docker logs <contenedor-db-o-redis> | Select-String <solo-patron-de-version>
```

La salida JSON de Compose se proyectó en memoria para obtener únicamente nombres, imágenes, perfiles, redes, health checks y puertos. No se persistieron ni mostraron variables de entorno.

## Bloqueos y siguientes comprobaciones

1. **BLOCKED — runtime:** los 14 contenedores están detenidos. Debe elegirse una ventana con memoria suficiente y sin interferir con los 57 contenedores activos de otros proyectos.
2. **BLOCKED — puerto 9000:** otro proyecto lo publica activamente. Se necesita coordinar un puerto alternativo para esta instalación o una ventana autorizada sobre el otro proyecto.
3. **BLOCKED — bases de datos live:** no se verificaron readiness, esquema, extensiones, datos, autenticación ni aislamiento.
4. **BLOCKED — Redis live:** no se verificaron persistencia, namespaces, ACL, conectividad ni locks.
5. **BLOCKED — health y E2E:** los estados históricos `unhealthy` no permiten concluir el estado actual; se requiere arranque controlado y pruebas reproducibles.
6. **BLOCKED — capacidad:** con 87.7 % de RAM host usada y solo 3.88 GiB libres, un build o perfil full no es seguro dentro del alcance actual.

No se ejecutó ninguna operación destructiva y los volúmenes del proyecto permanecen intactos.
