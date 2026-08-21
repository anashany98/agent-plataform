> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# Contraste estático de operaciones — Fase 1

## Alcance y método

Contraste de los defectos `D-009`, `D-015`, `D-016`, `D-018`, `D-022`, `D-023`, `D-025` y `D-028` contra el estado actual del workspace.

- Captura: 2026-08-02T20:14:50.158+02:00, Europe/Madrid.
- Workspace: `C:\Users\PC\Desktop\PROYECTOS\agent-platform-fixed`.
- Rama: `production-remediation`.
- HEAD: `4d4a6e915916467ca45c76a89af058cf7d219a27`.
- Método: archivos fuente, scripts completos, proyección limitada de Compose y metadatos Docker no sensibles.
- Restricciones: no se arrancó ni modificó Docker, no se ejecutaron backup/restore/update/rollback, no se leyó `.env`, no se inspeccionó `.Config.Env`, no se accedió a red externa y no se inspeccionó el contenido de backups.

Los términos se usan así:

- **OBSERVADO:** demostrado en código, configuración o metadatos actuales.
- **NO OBSERVADO:** la afirmación anterior no aparece en la evidencia actual consultada.
- **BLOCKED:** exige runtime, operación destructiva controlada, credenciales, red externa o validación legal fuera de este alcance.

## Resumen

| Defecto | Parte observada | Parte corregida o matizada | Parte bloqueada | Estado del defecto |
|---|---|---|---|---|
| D-009 | Puerto 9000 ocupado por otro proyecto; no hay listener de este proyecto | Compose ya publica el proxy y acepta puerto por cliente | Provision real, red efectiva y HTTP | BLOCKED |
| D-015 | Cobertura incompleta y snapshot no coordinado | Script cifra, firma hashes, identifica cliente y contiene restore | Restore aislado, integridad funcional, RPO/RTO | BLOCKED |
| D-016 | Checkout Git global, builds mutables y ausencia de test | `.git`, rama y commits ya existen; estado/Compose se separan por cliente | Upgrade y rollback reproducibles | BLOCKED |
| D-018 | Compose solo despliega SPA Nginx y no despliega Supabase | El vendor no está vacío: contiene esquema, migraciones y funciones | Configuración real y recorrido funcional | BLOCKED |
| D-022 | Defaults/template siguen en development y demo | Provisioning genera staging y staging activa guardas | Entorno runtime actual y arranque negativo | BLOCKED |
| D-023 | EE presente, notice contradictorio, sin LICENSE raíz ni SBOM final | Licencias vendor locales están presentes | Aprobación legal y artefacto depurado | BLOCKED |
| D-025 | 14/14 servicios sin CPU/RAM/PID limits | Rotación de logs 10 MiB × 5 está configurada | Loop, idle y soak medidos | BLOCKED |
| D-028 | Sin collector, trazas, dashboards ni alertas; coste estimado siempre cero | Health, readiness, audit correlation parcial y rotación existen | Fault injection y entrega de alertas | BLOCKED |

---

## D-009 — Colisión y publicación del puerto

### OBSERVADO

1. `docker-compose.yml` publica `${PROXY_PORT:-9000}:8080` para `reverse-proxy`.
2. El contenedor detenido de este proyecto conserva `8080/tcp -> host 9000` en `HostConfig.PortBindings`.
3. El contenedor detenido solo conserva la red `agent-platform-fixed_internal`, aunque la fuente Compose actual declara `public` e `internal`. La instancia existente y la configuración fuente no coinciden por completo.
4. El puerto host 9000 está publicado actualmente por:

   ```text
   agent-platform-reverse-proxy-1 | project=agent-platform | 0.0.0.0:9000->80/tcp, [::]:9000->80/tcp
   ```

   Ese contenedor pertenece a otro proyecto y no se modificó.
5. `scripts/provision-client.ps1` y `.sh` aceptan un puerto por cliente, con default 9000.
6. Ningún script de provisioning comprueba si el puerto ya está escuchando antes de crear configuración, construir imágenes y ejecutar `compose up`.

### Parte corregida o matizada

- **OBSERVADO:** ya existe una publicación de puerto declarativa en Compose.
- **OBSERVADO:** ya existe parametrización por cliente mediante `PROXY_PORT`.
- La afirmación antigua “sin bind configurado” ya no describe la fuente actual. El proyecto sigue sin publicación efectiva porque sus contenedores están detenidos y el puerto elegido colisiona.

### BLOCKED

- No se recreó el proxy, por lo que no se verificó que adquiera las redes `public` e `internal` actuales.
- No se comprobó HTTP/health a través de un puerto alternativo.
- No se ejecutó el provisioning con colisión para confirmar fail-fast; estáticamente no existe preflight.

### Criterio posterior

1. Añadir preflight atómico de puerto antes de escribir artefactos o construir.
2. Aprovisionar dos clientes con puertos distintos en proyectos Compose separados.
3. Verificar listener, red pública, health y routing de cada cliente.
4. Probar que un puerto ocupado aborta sin crear una instalación parcial.

---

## D-015 — Backup incompleto y restore no demostrado

### OBSERVADO: mejoras presentes

Los scripts PowerShell y Bash actuales incluyen:

- dumps PostgreSQL en formato custom para Bridge, Chatwoot y Activepieces;
- archivos de los volúmenes `bridge_uploads` y `chatwoot_storage_data`;
- manifiesto con `client_id`, proyecto, timestamp, commit y versión de formato;
- SHA-256 de los componentes y del archivo cifrado;
- cifrado AES-256-CBC con PBKDF2;
- validación de que el backup pertenece al cliente indicado;
- restore de las tres bases y los dos volúmenes;
- parada previa de servicios de aplicación/workers;
- espera de health posterior.

Esto corrige la afirmación amplia de que solo existía un script nominal sin verificaciones internas.

### OBSERVADO: brechas que permanecen

1. El backup contiene exactamente tres dumps y dos volúmenes. No incluye:
   - tres volúmenes Redis;
   - `activepieces_cache`;
   - configuración/secrets por cliente;
   - certificados/TLS;
   - datos de un Supabase/FlowWink externo;
   - una copia externa u objeto remoto configurable.
2. Los tres dumps y dos archivos de volumen se capturan secuencialmente mientras las aplicaciones siguen en ejecución. No hay barrera transaccional común ni parada previa en la rama `backup`; el snapshot intercomponente puede representar instantes distintos.
3. El restore usa `pg_restore --clean --if-exists` y vacía cada volumen mediante `find /data -mindepth 1 -delete`. Es destructivo sobre el destino y solo debe probarse en una instalación aislada.
4. La ruta de salida es local: `infrastructure/backups/<client-id>`.
5. No hay retención, copia offsite, scheduler, alerta de fallo ni prueba periódica en estos scripts.
6. Existe `infrastructure/backups/`, pero no se inspeccionó su contenido y su mera existencia no prueba backup válido ni restore.

### NO OBSERVADO

No se encontró una evidencia actual reproducible —ligada al HEAD actual, fixture, hashes, conteos y salida de test— de un restore completo en una instalación vacía.

Existen informes históricos bajo `docs/archive/unverified-original/` que dicen `VERIFIED` o `PASSED`. Su propia ubicación los clasifica como no verificados y no contienen la cadena de evidencia necesaria para elevar el estado actual.

### BLOCKED

- Restore aislado y comparación de datos/objetos.
- RPO y RTO medidos.
- Verificación funcional después de restaurar.
- Compatibilidad del restore entre versiones.

### Criterio posterior

1. Crear fixture por cliente con datos en las tres bases y los volúmenes persistentes relevantes.
2. Coordinar un snapshot consistente o registrar explícitamente sus límites de consistencia.
3. Restaurar en un proyecto nuevo y vacío, nunca sobre esta instalación.
4. Validar hashes, conteos, relaciones, documentos y flujos funcionales.
5. Medir RPO/RTO y conservar un recibo firmado por commit y versión de esquema.

---

## D-016 — Update/rollback compartido

### Parte resuelta: OBSERVADO

- El workspace ahora es un repositorio Git.
- Existe la rama `production-remediation` y un historial con commits.
- Los scripts validan que no haya cambios tracked sin confirmar antes de operar.
- La referencia objetivo se resuelve a commit antes del checkout.
- Cada cliente utiliza:
  - proyecto Compose `agent-<client-id>`;
  - archivo de configuración separado;
  - backup previo separado;
  - estado `infrastructure/update-state/<client-id>.json`.
- Update intenta rollback automático y los scripts verifican health después del cambio.

La subcausa “no existe `.git`” está corregida en el entorno actual.

### OBSERVADO: causa que permanece

1. `git checkout --detach <commit>` se ejecuta sobre el único working tree compartido.
2. Update y rollback reconstruyen desde ese checkout global; no usan artefactos o imágenes inmutables por digest.
3. No existe lock de workspace para impedir dos updates de clientes simultáneos.
4. Un rollback de un cliente cambia también el checkout desde el que se construirían los demás clientes.
5. No hay validación de SemVer, firma, digest, compatibilidad de esquema o matriz de migraciones en los scripts.
6. El repositorio actual tiene cero remotes y cero tags. Solo pueden usarse commits/referencias ya presentes localmente.
7. El worktree actual contiene archivos untracked de remediación. El preflight usa `git diff --quiet` y `git diff --cached --quiet`, que no detectan untracked; por tanto, esos archivos no impedirían el checkout y podrían acompañar accidentalmente un build/contexto.

### NO OBSERVADO

- No se encontró test automatizado de upgrade/rollback por cliente.
- No hay evidencia actual de dos clientes actualizados a versiones distintas desde el mismo workspace.
- No hay artefacto firmado o imagen fijada por digest.

### BLOCKED

Update y rollback reales requieren backup/restore, builds, arranque y una operación potencialmente destructiva; no se ejecutaron.

### Criterio posterior

1. Preparar dos proyectos de cliente con datos fixture y versiones diferentes.
2. Actualizar uno sin cambiar código, imágenes ni estado del otro.
3. Probar migración forward y compatibilidad N/N-1.
4. Hacer rollback del primero y comparar datos/health/flujo.
5. Ejecutar updates concurrentes para demostrar ausencia de carrera o fail-fast por lock.
6. Usar release/tag firmado e imágenes inmutables por digest.

---

## D-018 — FlowWink y Supabase

### Parte matizada: OBSERVADO

El vendor FlowWink no es un repositorio vacío ni solo una maqueta trivial. La inspección limitada encontró:

- aplicación React amplia;
- cliente `@supabase/supabase-js`;
- `supabase/schema.sql` y `supabase/config.toml`;
- 283 migraciones SQL;
- 78 directorios de Edge Functions;
- tests y scripts de provisioning/deployment propios del vendor.

Por tanto, “sin backend en el código vendor” sería incorrecto.

### OBSERVADO: defecto del despliegue actual

1. El Dockerfile construye una SPA Vite y la sirve con `nginx:1.27-alpine`.
2. La imagen final no contiene ni inicia PostgreSQL, Supabase Auth, PostgREST, Realtime o Edge Runtime.
3. El propio Dockerfile indica que las migraciones se aplican por separado y que el prebuild se omite si no hay Supabase CLI.
4. Compose declara un único servicio `flowwink-app` y cero servicios cuyo nombre sea Supabase.
5. El contenedor existente es Nginx estático, sin mounts y solo en la red `internal`.
6. Los tres parámetros Supabase están cableados como build args/runtime values, pero su default estático en Compose es vacío.
7. El cliente frontend llama directamente al proveedor Supabase configurado; sin proveedor funcional, gran parte del producto no tiene plano de datos.

### NO OBSERVADO

No se afirma que el `.env` actual tenga valores vacíos: ese archivo no se leyó. Tampoco se afirma que no exista un Supabase externo fuera del workspace.

### BLOCKED

- Configuración runtime real.
- Migraciones aplicadas a un proyecto autorizado.
- Auth, RLS, funciones y recorridos funcionales E2E.
- Backup/exportación del backend externo.

### Resultado

El calificativo “shell vacío” se mantiene solo para la instalación Compose autónoma actual: despliega el frontend pero no el backend requerido. Se descarta como descripción del código vendor completo.

### Criterio posterior

O bien retirar FlowWink del perfil soportado, o provisionar un backend local/externo autorizado y demostrar auth, RLS, una operación útil, migraciones, backup y restore. Un health de Nginx no satisface el criterio.

---

## D-022 — Development defaults y guardas staging

### OBSERVADO: defaults inseguros para despliegue

- `Settings.ENVIRONMENT` usa `development` por defecto.
- `Settings.PILOT_MODE` usa `true` por defecto.
- `.env.example` declara `ENVIRONMENT=development`, `PILOT_MODE=true` y `AUTO_SEED_DEMO_DATA=true`.
- `validate_runtime_security()` retorna sin validar cuando el entorno no es production-like.

El template general sigue siendo de desarrollo y puede inducir un arranque no endurecido si se reutiliza como configuración de despliegue.

### Parte corregida: OBSERVADO

1. `is_production_like` incluye explícitamente `production` y `staging`.
2. `settings.validate_runtime_security()` se ejecuta al importar la aplicación.
3. En staging/production, la guarda rechaza secretos débiles, mocks/stubs y `AUTO_CREATE_SCHEMA`.
4. Ambos scripts `provision-client` generan `ENVIRONMENT=staging`, demo seed desactivado y mocks/stubs desactivados, con secretos aleatorios.

La afirmación “staging no activa las guardas” ya no es válida en el código actual.

### Brechas estáticas observadas

- La guarda no rechaza `AUTO_SEED_DEMO_DATA=true`.
- La guarda no valida por sí sola SQLite, CORS abierto, imágenes flotantes, migraciones pendientes o disponibilidad de claves opcionales por capacidad.
- No se encontraron tests específicos de `validate_runtime_security` para matriz development/staging/production.

### NO OBSERVADO / BLOCKED

El `.env` real y `.Config.Env` no se leyeron. Por ello no se reproduce la afirmación “el piloto actual ejecuta development”. El entorno efectivo, el resultado del preflight y los casos de arranque negativo permanecen **BLOCKED**.

### Criterio posterior

Ejecutar una matriz aislada que demuestre que staging/production fallan con cada configuración insegura y arrancan con configuración segura, incluyendo demo seed, SQLite, CORS, secrets, mocks y migraciones. Development debe permanecer claramente separado y no publicable.

---

## D-023 — Licencias, notices y código Enterprise

### OBSERVADO

1. No existe `LICENSE`, `LICENSE.md` o `LICENSE.txt` en la raíz para el código propio.
2. Sí existen licencias locales de FlowWink, Chatwoot, Chatwoot Enterprise, Activepieces y Activepieces Enterprise.
3. `vendor/chatwoot/enterprise` contiene 483 archivos.
4. `vendor/activepieces/packages/ee` contiene 10 archivos; también existe `packages/server/api/src/app/ee`.
5. `THIRD_PARTY_NOTICES.md` declara “Enterprise plugins excluded” para Chatwoot.
6. La raíz de Chatwoot se usa como build context, `.dockerignore` no excluye `enterprise` y `docker/Dockerfile` ejecuta `COPY . /app`.
7. Activepieces no se construye desde el vendor local en Compose; se usa una imagen publicada. La presencia del árbol EE local sigue afectando al source/release si se empaqueta sin exclusión.
8. El notice titula su contenido como SBOM, pero no existe un SBOM CycloneDX/SPDX final; solo existe un documento de estado en `docs/audit/evidence/SBOM_STATUS.md`.
9. El notice hace una declaración global de cumplimiento y propiedad del código propio que no está respaldada por una licencia raíz ni aprobación legal registrada.

### Contradicción demostrada

La frase “Enterprise plugins excluded” no coincide con el árbol fuente ni con el contexto de build Chatwoot actual. Presencia no demuestra activación funcional, pero sí invalida la afirmación de exclusión del artefacto fuente/build context.

### BLOCKED

- Derechos de producción/redistribución de rutas EE.
- Revisión de la imagen Activepieces publicada y sus contenidos.
- Política de exclusión en la release final.
- Licencia elegida para código propio.
- Aprobación profesional legal.

### Criterio posterior

1. Definir licencia/propiedad del código propio.
2. Excluir físicamente rutas EE no autorizadas de contextos y release, o documentar licencia válida.
3. Generar SBOM final por artefacto e imagen.
4. Regenerar NOTICE desde el artefacto efectivo.
5. Obtener aprobación legal documentada antes de comercializar o redistribuir.

---

## D-025 — Límites y loops de recursos

### OBSERVADO

La inspección de los 14 contenedores del proyecto devuelve en todos:

- `Memory=0` y `MemorySwap=0`;
- `NanoCpus=0` y `CpuQuota=0`;
- `PidsLimit=null`;
- restart policy `unless-stopped`.

No se encontraron `mem_limit`, límites CPU, `pids_limit`, `deploy.resources`, reservas o `ulimits` en `docker-compose.yml`.

Metadatos adicionales:

- Chatwoot Web conserva `RestartCount=6`.
- Chatwoot Web/Worker y Activepieces App/Worker conservan último exit code 137.
- Los cuatro exit codes son hechos; no se atribuyen a OOM sin `OOMKilled`, eventos o medición correlacionada.

### Parte corregida: OBSERVADO

Compose define `json-file` con `max-size=10m` y `max-file=5`, aplicado a los 14 servicios. La ausencia total de rotación de logs ya no describe el estado actual.

### NO OBSERVADO / BLOCKED

- Los contenedores están detenidos, por lo que no se reprodujo consumo idle, CPU/tráfico de Activepieces/Redis ni crecimiento de procesos.
- No se heredó como medida actual el 95.3 % de RAM del build previo.
- No se ejecutó soak de 60 minutos ni capacity gate.

### Causa probable separada del hecho

La ausencia de límites aumenta el blast radius y `unless-stopped` puede amplificar un crash loop, pero no demuestra por sí sola la causa de los loops históricos.

### Criterio posterior

Definir budgets por servicio, validar que Compose los aplica, medir idle/carga/soak durante 60 minutos, provocar un límite controlado y confirmar degradación/alerta sin afectar otros proyectos.

---

## D-028 — Observabilidad y alertas

### Parte existente: OBSERVADO

- Bridge expone `/health` y `/ready`.
- Existe `/metrics`, protegido por rol administrativo.
- Los audit logs contienen `correlation_id` para varias operaciones.
- El router LLM registra tokens, latencia, proveedor/modelo y resultado.
- `prometheus-client` figura como dependencia.
- Compose rota logs localmente (`10m`, cinco archivos).

### Limitaciones observadas

1. `/metrics` devuelve JSON con tres conteos de base de datos; no usa formato Prometheus.
2. No hay imports/uso de `prometheus_client` en la aplicación pese a la dependencia.
3. No hay middleware general de request ID/correlation ID propagado a logs HTTP y llamadas salientes.
4. No hay collector, OpenTelemetry, trazas, Prometheus, Grafana, Loki, Tempo o Alertmanager en Compose.
5. No se encontraron dashboards ni reglas de alerta operativas fuera de vendor.
6. No hay pipeline centralizado ni destino externo de logs.
7. `_estimate_cost()` retorna siempre `0.0`; el presupuesto diario basado en esa suma no puede activarse con ejecuciones reales.
8. Health/readiness cubren principalmente DB; no exponen workers, colas, egress, modelos o integraciones.
9. No existe `.github` ni pipeline que valide reglas/alertas mediante fault injection.

### Parte matizada

“Sin métricas” es demasiado absoluto: existe un endpoint llamado `/metrics` y audit telemetry parcial. “Sin observabilidad operativa y alertas verificadas” sí permanece demostrado.

### NO OBSERVADO / BLOCKED

- No se observó una alerta real entregada.
- No se midió latencia/error rate ni se trazó una petición entre componentes.
- No se ejecutó fault injection.
- No se verificó redacción de PII/secrets en un pipeline central porque ese pipeline no existe.

### Criterio posterior

Instrumentar RED/USE y flujos de negocio, propagar IDs, exportar métricas/trazas/logs sanitizados, definir SLI/SLO y alertas, y demostrar mediante fault injection que una caída de DB, worker, integración, coste o backup genera una alerta accionable dentro del umbral.

---

## Comandos reproducibles de solo lectura

Los comandos siguientes no consultan `.env` ni `.Config.Env`.

```powershell
# Contexto
Get-Location
git status --short --branch
git rev-parse HEAD
git remote -v
git tag --list

# Puerto y metadatos seguros
docker ps --filter 'publish=9000' `
  --format '{{.Names}}|{{.Label "com.docker.compose.project"}}|{{.Ports}}'
docker inspect `
  --format 'Status={{.State.Status}} PortBindings={{json .HostConfig.PortBindings}} Networks={{range $n, $_ := .NetworkSettings.Networks}}{{$n}},{{end}}' `
  agent-platform-fixed-reverse-proxy-1

# Servicios Compose, sin configuración resuelta
docker compose --profile '*' config --services

# Recursos efectivos, uno por contenedor
$ids = @(docker ps -aq --filter 'label=com.docker.compose.project=agent-platform-fixed')
foreach ($id in $ids) {
  docker inspect `
    --format 'Memory={{.HostConfig.Memory}} NanoCpus={{.HostConfig.NanoCpus}} CpuQuota={{.HostConfig.CpuQuota}} Pids={{.HostConfig.PidsLimit}} Restart={{.HostConfig.RestartPolicy.Name}} Log={{json .HostConfig.LogConfig}}' `
    $id
}

# Evidencia estática focalizada
rg -n 'PROXY_PORT|ports:|9000' docker-compose.yml scripts/provision-client.ps1 scripts/provision-client.sh
rg -n 'Backup-Database|Backup-Volume|Restore-Database|Restore-Volume|SHA256SUMS|openssl enc' scripts/backup-restore-integral.ps1 scripts/backup-restore-integral.sh
rg -n 'git checkout|--detach|previous_commit|update-state' scripts/update-client.ps1 scripts/update-client.sh scripts/rollback-client.ps1 scripts/rollback-client.sh
rg -n 'ENVIRONMENT|is_production_like|validate_runtime_security|AUTO_SEED_DEMO_DATA' bridge-api/app/config.py bridge-api/app/main.py .env.example scripts/provision-client.ps1 scripts/provision-client.sh
rg -n 'COPY \. /app|enterprise' vendor/chatwoot/docker/Dockerfile vendor/chatwoot/.dockerignore THIRD_PARTY_NOTICES.md
rg -n '@app.get\("/(health|ready|metrics)|def _estimate_cost|return 0\.0' bridge-api/app
```

## Conclusión

Ninguno de los ocho defectos puede cerrarse con la evidencia actual. Sí se han producido mejoras estáticas importantes desde la auditoría original: Git existe, staging activa guardas, provisioning separa proyecto/puerto por cliente, backup cifra y valida hashes, y Compose rota logs. Las condiciones de aceptación que dependen de restore, rollback, E2E FlowWink, runtime seguro, exclusión legal, soak o alertas permanecen **BLOCKED**.
