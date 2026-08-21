# Operaciones

## Chequeo diario

```powershell
.\scripts\check-health.ps1 -ClientId <cliente> -Profile production
```

Revisar health de seis servicios, Alembic head, readiness, espacio de disco, uso CPU/RAM/PID, expiración TLS, outbox/DLQ, scheduler, errores 4xx/5xx, rate limit y último backup. No confundir `healthy` con flujo funcional: ejecutar un smoke de lectura y una operación idempotente controlada.

## Endpoints

| Endpoint | Acceso | Uso |
|---|---|---|
| `/live` | Público | Liveness y versión, sin dependencias |
| `/health` | Público | Estado agregado DB/workers sin detalles sensibles |
| `/ready` | Público | 200 solo con DB, Redis y workers listos |
| `/health/details` | Admin | Instalación/entorno y estado detallado de workers |
| `/metrics` | Admin | Contadores, outbox, breakers y alertas internas |

Las rutas llegan externamente por `https://<API_HOST>/...`; el proxy puede exponer el API bajo `/api/bridge` para el Portal.

## Logs

```powershell
docker compose --env-file .env.<cliente> -p agent-<cliente> `
  -f docker-compose.yml -f infrastructure/compose/docker-compose.prod.example.yml `
  --profile production logs --since 15m bridge-api
```

Buscar `correlation_id`, `request_id`, ruta, status y latency. No compartir logs sin revisar redacción. Docker rota a 10 MiB × 5 archivos por servicio; exportación central y retención externa son pendientes operativos.

## Umbrales iniciales

| Señal | Warning | Crítico/acción |
|---|---|---|
| Disco libre | <30 GiB | <15 GiB: bloquear release/backup y liberar de forma controlada |
| Readiness | una caída transitoria | >2 checks: retirar tráfico e investigar |
| 5xx | >1 % en 5 min | >5 % o flujo crítico: rollback/incident |
| p95 API core | >500 ms sostenido | >2 s o timeout: reducir carga/investigar |
| Outbox dead | >0 | incidente SEV-2; no reintentar ciegamente |
| Breaker open | cualquier proveedor requerido | incidente; confirmar degradación segura |
| Backup | supera ventana | fallo o checksum/HMAC inválido: SEV-2 |
| TLS | <30 días | <7 días: escalar renovación |

Son valores iniciales, no SLO medidos; deben recalibrarse con el informe de rendimiento final.

## Trabajos programados

- Worker interno ejecuta solo tareas `automation_sweep` activas y aprobadas.
- El email local queda en `/data/emails` con estado `queued_for_manual_delivery`; un operador/relay autorizado debe entregarlo y registrar el resultado fuera del core actual.
- PrestaShop incremental es opcional y externo al production core; no configurar tarea del host sin certificación/credenciales.
- Programar backup cifrado por cliente y prueba periódica de restore.

## Mantenimiento

- Renovar TLS/secrets antes de caducar.
- Aplicar updates solo mediante [`UPGRADE_AND_ROLLBACK.md`](UPGRADE_AND_ROLLBACK.md).
- No ejecutar prune global, `down -v`, delete masivo o restore sin ventana y target comprobado.
- Revisar audit, usuarios, roles, integraciones deshabilitadas y límites mensualmente.
- Ensayar incidente/restore trimestralmente o según contrato.
