# Plan de remediación y conversión a producción

## Objetivo y alcance

Preparar una release reproducible del perfil `production`: Bridge, Portal, PostgreSQL, Redis, proxy interno y TLS, desplegados como una instancia independiente por cliente y funcionales sin PrestaShop, GHL o vendors. El estado se decide exclusivamente en [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md).

## Principios de salida

- Ningún estado se marca `VERIFIED` solo porque exista código o un contenedor esté healthy.
- Toda candidata nace de un commit limpio, imágenes inmutables, manifest y configuración propia.
- Ninguna prueba usa secretos/servicios reales sin autorización.
- Pedidos, facturas, publicaciones, activación de agentes y tareas siguen siendo manuales/aprobados.
- Un fallo de DB, Redis, worker o proveedor necesario debe fallar cerrado y ser visible.
- `full` se trata como producto opcional separado, no como dependencia del core.

## Fases y gates

| Fase | Entregable | Gate de salida | Estado al corte |
|---|---|---|---|
| 0. Baseline | Host, componentes, dependencias y ownership | Cuatro documentos en `docs/baseline/` actuales | COMPLETE |
| 1. Reproducción | Defect/risk register y evidencia | P0/P1 reproducidos o descartados con tests | PARTIAL, histórico preservado |
| 2. Núcleo P0/P1 | Aislamiento, confirmación, finanzas, idempotencia, RBAC, migraciones | Corpus crítico + PostgreSQL | PASS de código; candidate PENDING |
| 3. Módulos | Agentes, CRM, comercio, Wiki, RAG, SEO, landing, scheduler | API + Portal + aprobaciones + tests | PASS de componente; E2E PENDING |
| 4. Seguridad | Threat model, preflight, secrets, red, proxy | scans sin crítico/alto injustificado | PENDING scan final |
| 5. Infra/release | Locks, digests, labels OCI, manifest, TLS | build reproducible desde checkout limpio | PENDING |
| 6. Runtime | Stack production aislado | health/readiness/smoke/restart | PENDING |
| 7. E2E | Todos los módulos y roles | matriz E2E PASS | PENDING |
| 8. Recuperación | Backup, restore, rollback | restore vacío + checks + tiempos | PENDING |
| 9. Rendimiento | carga/soak/capacidad | límites y degradación aceptados | PENDING |
| 10. Release | bundle, SBOM, checksums, informes | 30 gates cerrados o limitaciones aprobadas | PENDING |

## Secuencia ejecutable de cierre

### A. Congelar la candidata

1. Revisar `git diff --check` y el alcance de cambios.
2. Ejecutar backend, Portal, quality, migraciones y verificadores infra.
3. Confirmar que no hay secretos, datos reales, backups o logs en Git.
4. Crear un commit coherente y asignar `RELEASE_VERSION` SemVer RC.
5. Generar locks/SBOM desde ese commit; no modificar después sin reiniciar los gates.

### B. Construir y registrar imágenes

```powershell
docker compose --env-file .env.<cliente> --profile production build --pull
python scripts/create-release-manifest.py --env-file .env.<cliente>
python scripts/production-preflight.py --env-file .env.<cliente> --profile production --mode release
```

Condición: checkout limpio, `SOURCE_COMMIT` exacto, etiquetas OCI coincidentes, imágenes locales exactas, imágenes externas por digest, certificado real no autofirmado y al menos 15 GiB libres (30 GiB recomendado).

### C. Desplegar aislado

```powershell
docker compose --env-file .env.<cliente> -p agent-<cliente> `
  -f docker-compose.yml `
  -f infrastructure/compose/docker-compose.prod.example.yml `
  --profile production up -d --no-build --pull never --wait --wait-timeout 600
```

No usar el proyecto de desarrollo `agent-platform`. Verificar que solo `tls-proxy` publica puertos y que Bridge carece de ruta por defecto.

### D. Matriz E2E mínima

1. Login, cambio obligatorio de contraseña, logout y revocación.
2. Roles: viewer, operador y admin; 401/403 y navegación fail-closed.
3. Importación validate → confirm y replay de `Idempotency-Key`.
4. Cliente → presupuesto → confirmación → pedido → borrador → aprobación/rechazo.
5. Concurrencia: dos confirmaciones y dos decisiones simultáneas.
6. Wiki: draft → preview → approval → ruta pública; XSS rechazado/saneado.
7. Landing: draft → preview → approval → ruta pública; sin afirmar publicación externa.
8. SEO: HTML suministrado → medidas/inferencias/recomendaciones → historial.
9. RAG TF-IDF: upload/ingesta → consulta/citas/abstención → ACL y borrado.
10. Agente: tool permitida/denegada, presupuesto y timeout/coste.
11. Scheduler: draft → aprobación → una ejecución idempotente.
12. Email: archivo de spool y estado `queued_for_manual_delivery`, nunca `sent`.
13. Redis caído: readiness 503 y rate limit fail-closed; recuperación tras restart.
14. DB/worker caído: readiness 503; no respuesta 2xx falsa.

### E. Recuperación y rollback

- Backup formato 4 con quiesce, AES-256-CBC/PBKDF2, HMAC y SHA-256.
- Restore en instalación vacía/controlada con misma configuración/manifest.
- Comprobar conteos, login, RAG, publicaciones, spool y transacciones.
- Medir RPO/RTO reales.
- Probar rollback de aplicación a la imagen anterior; conservar backup de seguridad.

### F. Rendimiento y operación

- Smoke y carga de lectura/escritura moderada, sin servicios externos.
- Soak mínimo acordado, restart de contenedores y presión de Redis/DB.
- Registrar p50/p95/p99, error rate, CPU/RAM y tiempos de backup/restore.
- Configurar un receptor de alertas externo y probar al menos una alerta crítica.

## Criterio para el 16 de agosto de 2026

Sin cerrar los stop-ships de readiness, el uso permitido es staging/controlado. Si se suministran DNS, TLS y secretos y todos los gates finales pasan, el responsable puede promover únicamente el core con las limitaciones documentadas. Nunca habilitar `full`, pedidos/facturas automáticos, egress o publicación externa como parte de esa promoción.
