# Respuesta a incidentes

## Objetivo

Contener, preservar evidencia y recuperar una instancia sin agravar el daño. No borrar datos/logs, no rotar ciegamente y no restaurar sobre producción sin autorización del responsable de incidente.

## Severidades

| Nivel | Ejemplos | Respuesta inicial objetivo |
|---|---|---|
| SEV-1 | Acceso cruzado, secreto activo expuesto, pedido/factura/publicación no autorizada, pérdida de datos | Inmediata; detener tráfico/efectos |
| SEV-2 | Auth/RBAC degradado, DB/Redis caído, DLQ creciente, restore fallido | ≤30 min |
| SEV-3 | Módulo no crítico, latencia elevada, integración opcional caída | ≤4 h |
| SEV-4 | Defecto menor/documentación | Siguiente ciclo |

Los objetivos requieren una guardia y canales reales; hoy son operativos propuestos, no SLA contractual.

## Primeros 15 minutos

1. Nombrar incident commander y secretario; abrir cronología UTC.
2. Identificar `client_id`, instalación, versión, commit, image IDs y alcance.
3. Si hay riesgo de efecto externo, deshabilitar integración/egress o retirar el borde, sin destruir datos.
4. Capturar `docker compose ps`, eventos, health, logs redactados, métricas, estado de outbox/DLQ y checksums.
5. Preservar `.env`/secrets sin copiarlos al ticket/chat; registrar solo identificadores/versiones.
6. Si hay pérdida/corrupción, pausar writers y crear backup de seguridad antes de restaurar.

## Playbooks

### Secreto expuesto

- Revocar en el proveedor; rotar en orden: DB/Redis, auth/HMAC/API, TLS según alcance.
- Incrementar/revocar sesiones; recrear solo los servicios consumidores.
- Buscar uso anómalo y exposición en Git, artefactos, imágenes, logs y backups.
- No considerar cerrado hasta verificar credenciales antiguas rechazadas.

### Acceso cruzado

- Retirar la instancia del tráfico y congelar writes.
- Preservar logs/auditoría/DB; identificar instalación origen/destino y filas/archivos.
- No corregir datos manualmente antes de una copia forense.
- Notificar a responsables legal/privacidad; seguir obligaciones aplicables.

### Pedido/factura/publicación no autorizada

- Deshabilitar flags/integración y worker relacionado.
- Identificar approval, idempotency key, actor, versión del recurso y efectos externos.
- Nunca borrar la auditoría; compensar mediante proceso humano/contable autorizado.

### DB/Redis/worker caído

- Confirmar que `/ready` devuelve 503 y el borde retira tráfico.
- Revisar recursos, disco, credenciales y logs; no activar fail-open.
- Recuperar el componente y verificar outbox/locks/leases antes de reabrir.

### Ransomware/corrupción

- Aislar host/red, preservar evidencia y no montar backups en el host comprometido.
- Verificar HMAC/checksums y restaurar en infraestructura limpia.
- Rotar todos los secrets que existían en el host.

## Comandos de recogida segura

```powershell
docker compose --env-file .env.<cliente> -p agent-<cliente> `
  -f docker-compose.yml -f infrastructure/compose/docker-compose.prod.example.yml `
  --profile production ps
docker compose --env-file .env.<cliente> -p agent-<cliente> `
  -f docker-compose.yml -f infrastructure/compose/docker-compose.prod.example.yml `
  --profile production logs --since 30m --no-color > incident-logs.txt
docker image inspect <imagen-versionada>
```

Revisar/redactar el archivo antes de compartirlo. No ejecutar `docker compose down -v`, prune ni delete durante contención.

## Recuperación y cierre

- Restaurar/rollback solo con aprobación, backup verificado y plan de reversión.
- Ejecutar smoke de identidad, aislamiento, transacción, RAG, publicaciones y workers.
- Rotar secretos y cerrar sesiones si hubo compromiso.
- Documentar línea temporal, causa raíz, blast radius, datos afectados, decisiones y acciones.
- Añadir test preventivo y propietario/fecha; validar que la alerta habría detectado el evento.
