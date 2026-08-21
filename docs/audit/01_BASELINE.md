> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# 01 - Baseline de auditoría

**Fecha de captura:** 2026-08-02  
**Workspace:** `C:\Users\PC\Desktop\PROYECTOS\agent-platform-fixed`  
**Alcance:** código propio y recursos Docker del proyecto `agent-platform-fixed`; vendor limitado a manifiestos y rutas referenciadas.

## Clasificación del baseline

| Elemento | Estado | Evidencia |
|---|---|---|
| Identidad Git del código entregado | BLOCKED | El workspace no contiene `.git`; `git status`, rama, commit, tags, log y submódulos devuelven “not a git repository”. |
| Toolchain local | VERIFIED | Comandos de versión ejecutados correctamente. |
| Docker Engine | VERIFIED | Engine 29.5.3 operativo sobre Docker Desktop; driver `overlayfs`. |
| Sintaxis Compose, perfil `full` | VERIFIED | `docker compose --profile full config --quiet` terminó con código 0 y declaró 14 servicios. |
| Stack completo arrancado | BROKEN | 12 servicios reportan `healthy`, `chatwoot-web` está reiniciándose y `reverse-proxy` está `unhealthy`. |
| Integraciones externas | BLOCKED | PrestaShop, GHL, Chatwoot API, Activepieces API y proveedores externos carecen de credenciales/configuración completa en el entorno auditado. |
| Datos de ejecución | PARTIALLY VERIFIED | Hay volúmenes persistentes y base Bridge accesible, pero todavía no se han validado efectos funcionales ni aislamiento. |

## Estructura principal

- `bridge-api/`: backend propio FastAPI/Python.
- `portal/`: frontend propio React/TypeScript.
- `infrastructure/`: proxy y variantes Compose.
- `scripts/`: aprovisionamiento, salud, backup/restore, update y rollback.
- `tests/`: pruebas de integración del backend.
- `client-onboarding/` y `clients/`: plantillas y datos por instalación.
- `vendor/flowwink`, `vendor/chatwoot`, `vendor/activepieces`: repositorios de terceros sin metadatos Git visibles en el workspace.
- `docs/`: documentación actual y archivo explícitamente no verificado.
- `release/`: artefactos de entregas anteriores.

Se inventariaron 138 archivos propios fuera de vendor, dependencias, builds, cobertura, backups y release. Vendor ocupa aproximadamente 358,7 MiB y más de 35.000 archivos; no se leyó de forma exhaustiva.

## Entorno

| Recurso | Valor observado |
|---|---|
| SO | Windows 11 Pro 64 bits, build 26200 |
| CPU | Intel Core Ultra 9 275HX, 24 núcleos/lógicos |
| RAM host | 31,46 GiB totales; 4,36 GiB libres en la captura (aprox. 86,1 % usada) |
| Disco C: | 925,14 GiB; 161,38 GiB libres |
| GPU | Intel Graphics y NVIDIA GeForce RTX 5070 Laptop GPU |
| Docker | 29.5.3; 24 CPU; 15,35 GiB asignados a Docker Desktop |
| Docker Compose | v5.1.4 |
| Git | 2.52.0.windows.1 |
| Python | 3.11.7 |
| Node.js | v24.13.0 |
| npm | 11.6.2 |
| pnpm | 10.33.2 |

El inventario del host mostró numerosos puertos ocupados por varios stacks, pero no se atribuyen al proyecto auditado. La comprobación específica posterior confirmó que `localhost:9000` pertenece a otro proyecto fuera de alcance y que el contenedor `agent-platform-fixed-reverse-proxy-1` no tiene publicación efectiva, aunque Compose declara `9000:8080`. No se inspeccionó ni alteró el stack ajeno.

## Compose y runtime del proyecto

**Servicios declarados:** `activepieces-db`, `activepieces-redis`, `activepieces-app`, `activepieces-worker`, `chatwoot-db`, `chatwoot-redis`, `chatwoot-web`, `bridge-db`, `bridge-redis`, `bridge-api`, `chatwoot-worker`, `flowwink-app`, `portal`, `reverse-proxy`.

**Redes declaradas:** `public`, `internal` y `data`; `internal` y `data` están marcadas como internas.  
**Volúmenes declarados:** nueve, para las tres bases, los tres Redis/caché y almacenamiento de Chatwoot/Bridge.  
**Exposición declarada:** solo `reverse-proxy`, puerto host 9000 a contenedor 8080.

### Defectos de ejecución encontrados en baseline

1. **BL-01 - Chatwoot no sobrevive al reinicio del host (P1).** `chatwoot-web` tiene 24 reinicios y sale con código 1. Tras haber funcionado y respondido `/health` el 31/07, al reiniciarse Docker el 02/08 Rails rechaza el arranque: `A server is already running (pid: 1, file: /app/tmp/pids/server.pid)`. El comando de arranque no elimina ni valida el PID obsoleto.
2. **BL-02 - Proxy sin workers (P1).** `reverse-proxy` permanece en ejecución pero `unhealthy` con 54 fallos consecutivos. Nginx registra repetidamente `setuid(101) failed (1: Operation not permitted)`: Compose elimina todas las capabilities y no devuelve `SETUID`, aunque Nginx intenta bajar privilegios. El proceso maestro vivo crea un falso estado “running”.
3. **BL-03 - Nombre duplicado en el vhost del portal (P3).** Con `PORTAL_HOST=localhost`, la plantilla genera `server_name localhost localhost 127.0.0.1`; Nginx avisa `conflicting server name "localhost" ... ignored`. Los otros vhosts (`api.localhost`, `chat.localhost`, `agents.localhost`, `automation.localhost`) sí son distintos.
4. **BL-04 - Activepieces Worker no conecta de forma estable (P1/P2 por confirmar).** Registra errores Socket.IO y `RPC [poll] failed (timeout: 60000ms)`. La app y Redis mostraron en una instantánea 49,53 % y 36,94 % de CPU respectivamente, con 5,69 GiB de tráfico Redis-app en unos 16 minutos de uptime visible. No se atribuye causalidad todavía.
5. **BL-05 - Sin límites de recursos Compose (P2).** No se declaran límites de CPU o memoria. Con solo 4,36 GiB libres en el host no es seguro iniciar carga ni un build completo paralelo sin reducir consumo y volver a medir.

## Configuración observada sin exponer secretos

- `.env` existe, está ignorado por `.gitignore` y contiene secretos configurados; sus valores no se leyeron en la salida de auditoría.
- `ENVIRONMENT=development`, `PILOT_MODE=true` y `AUTO_SEED_DEMO_DATA=true` en la instalación activa.
- `ALLOW_MOCK_LLM=false` y `ALLOW_INTEGRATION_STUBS=false`.
- Están vacíos los parámetros necesarios para PrestaShop, GHL, Chatwoot API/webhook operativo, Activepieces API y proveedores externos OpenAI/Anthropic.
- Ollama y embeddings apuntan a un endpoint local configurado, pero todavía no se ha probado disponibilidad ni un flujo real.

## Informes previos revisados y fiabilidad inicial

Se revisaron `README.md`, `TASKS.md`, `STATUS.md`, `VERSIONS.md`, `THIRD_PARTY_NOTICES.md`, `docs/ARCHITECTURE.md`, `docs/AUDIT.md`, `docs/MASTER_PLATFORM_REPORT.md`, `docs/FINAL_REPORT.md`, `docs/REMEDIATION_REPORT.md`, `docs/SECURITY.md`, `docs/BACKUP_RESTORE.md`, `docs/INSTALLATION.md`, `docs/KNOWN_LIMITATIONS.md`, `docs/RISKS.md`, `docs/UX_AUDIT.md`, `docs/COMMERCIAL_READINESS_REPORT.md`, `docs/LIVE_VALIDATION_CHECKLIST.md`, `docs/DEPLOYMENT_MANIFEST.md`, `docs/DATA_OWNERSHIP.md` y `docs/DECISIONS.md`.

Hallazgos de coherencia:

- El NO-GO previo para cliente real es prudente, pero la declaración “GO para staging” queda refutada por los fallos actuales de Chatwoot y proxy.
- `docs/DATA_OWNERSHIP.md` declara FlowWink fuente maestra de catálogo, stock, precios y transacciones, mientras README/remediación asignan PrestaShop como fuente oficial y Bridge como núcleo transaccional. La fuente de verdad no está documentada de forma coherente.
- `docs/BACKUP_RESTORE.md` describe solo un dump SQL sin cifrado, mientras el informe de remediación afirma una copia integral cifrada de tres bases y archivos. Debe verificarse contra scripts y mediante restauración.
- `VERSIONS.md` y los avisos atribuyen commits concretos a vendor, pero no pueden confirmarse mediante Git porque se entregaron sin `.git`.
- Los resultados heredados de 31 tests y 67 % de cobertura no se consideran evidencia hasta volver a ejecutarlos.

## Riesgos

- El runtime actual no ofrece una ruta de acceso funcional por proxy ni Chatwoot operativo.
- La instalación activa carga datos demo automáticamente; cualquier dato mostrado debe marcarse como simulado hasta confirmar su origen.
- La falta de procedencia Git impide reproducibilidad, release signing, diff contra vendor y verificación de modificaciones locales.
- La memoria disponible y los síntomas de Activepieces hacen insegura una carga no limitada.
- Documentación contradictoria puede inducir decisiones comerciales o de recuperación erróneas.

## Trabajo pendiente tras esta fase

- Verificar vendor por manifiestos, licencias, hashes de archivos y rutas usadas.
- Inspeccionar código propio, tests, scripts y migraciones.
- Reejecutar análisis estático, tests, cobertura y builds.
- Probar endpoints y efectos reales con datos ficticios.
- Diagnosticar en detalle Activepieces y medir recursos en reposo estable.
- No ejecutar carga hasta que RAM permanezca por debajo del umbral seguro y los bucles/reinicios estén controlados.
