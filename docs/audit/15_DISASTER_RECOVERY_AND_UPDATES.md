> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# 15 - Recuperación, backup y actualizaciones

## Clasificación

| Capacidad | Estado | Razón |
|---|---|---|
| Backup script | IMPLEMENTED BUT NOT TESTED | Código integral parcial; no ejecución válida |
| Restore | BLOCKED | Sin backup auditado/passphrase/entorno seguro |
| RPO | BLOCKED | No hay scheduling ni medición; no inventar |
| RTO | BLOCKED | Nunca se restauró; no inventar |
| Update | BROKEN | Falta `.git`; checkout global |
| Rollback | BROKEN | Depende de Git y restore no verificado |

## Qué incluye el script nuevo

- Dumps custom de Bridge, Chatwoot y Activepieces PostgreSQL.
- Volúmenes `bridge_uploads` y `chatwoot_storage_data`.
- Manifiesto con cliente/proyecto/commit/formato.
- SHA-256 interno y externo.
- Tar cifrado AES-256-CBC con PBKDF2 200.000 iteraciones.
- Restore con `pg_restore --clean --if-exists`, limpieza/relleno de volúmenes y wait healthy.

## Omisiones y consistencia

- No incluye `.env`, configuración cliente, certificados, proxy, recibo de provisión ni manifiesto de imágenes/digests.
- Omite Redis de Bridge/Chatwoot/Activepieces y `activepieces_cache`; pueden contener jobs, sesiones o paquetes necesarios.
- No cubre datos Supabase de FlowWink ni servicios externos PrestaShop/GHL.
- Dumps y tar de uploads se toman con aplicaciones activas: no hay snapshot coordinado entre tres DB y archivos.
- CBC no ofrece autenticación integrada; checksums ayudan tras descifrar, pero la gestión de su archivo/clave no está definida.
- Sin retención, rotación, copia offsite, prueba periódica, monitor/alerta, borrado legal ni inventario de backups.
- La instalación activa usa `.env`/proyecto `agent-platform-fixed`; scripts exigen `.env.<cliente>`/`agent-<cliente>`.

## Restore y seguridad operacional

- Restore borra contenido de volúmenes destino con `find ... -delete`: correcto solo con objetivo validado y ventana aprobada.
- No crea un entorno aislado de validación ni compara invariantes de negocio/post-restore.
- `Wait-Healthy` considera servicios sin health como aceptables y exige 14 IDs; health defectuoso puede dar falso éxito o timeout.
- No existe restore point para el propio código/config si el Git/registry no está disponible.

## Migraciones y compatibilidad

- Alembic `0001` refleja el modelo actual mediante `create_all`; no versiona cambios columna a columna.
- Su downgrade `drop_all` destruye todas las tablas.
- No hay matriz app↔schema↔vendor, forward compatibility, expand/contract ni backup pre-migration verificado.
- Imágenes por tag y Chatwoot `.git_sha` temporal impiden rollback determinista.

## Update/rollback

- Los scripts hacen backup, `git checkout --detach`, build/up y health; en error intentan volver y restaurar.
- El workspace auditado no tiene `.git`: fallan antes de actualizar.
- Un checkout del workspace es global, por lo que no representa actualizaciones independientes de clientes simultáneos.
- No existe registry de releases firmadas, digest por cliente, canary, maintenance mode o bloqueo de writes.

## Criterio de verificación requerido

1. Fixture ficticio en las tres DB y uploads/cache.
2. Backup con apps quiesced/snapshot consistente.
3. Restore en proyecto aislado nuevo.
4. Checksums, conteos, archivos, migración, login, chat y jobs comparados.
5. Medir RPO/RTO y documentar intervención.
6. Repetir actualización/rollback con release inmutable.

## Archivos revisados, riesgos y pendiente

Scripts Bash/PowerShell, Compose/volúmenes, migración y docs anteriores. Riesgo P1: una copia no restaurada no es protección. La prueba destructiva controlada queda BLOCKED por recursos y convención de instalación.
