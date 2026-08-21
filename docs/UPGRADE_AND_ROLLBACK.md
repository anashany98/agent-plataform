# Actualización y rollback

## Reglas

- Usar un checkout dedicado por instancia; los scripts hacen checkout detached y no deben ejecutarse en el workspace de desarrollo compartido.
- Nunca actualizar desde un árbol sucio ni reconstruir durante despliegue.
- Conservar las imágenes anteriores exactas y la passphrase del backup.
- Revisar migraciones: los downgrades conservadores pueden no eliminar schema nuevo; el rollback fiable incluye restore de datos.

## Preparación

1. Candidate gates, release notes, SBOM/scans y compatibilidad de schema PASS.
2. Backup+restore de ensayo con datos representativos.
3. Ventana, responsables, smoke y criterio de abortar.
4. `TargetRef`, imágenes y manifest disponibles localmente.
5. Espacio suficiente para dos juegos de imágenes y dos backups.

## Actualizar

```powershell
$env:BACKUP_ENCRYPTION_PASSPHRASE = '<gestor de secretos>'
.\scripts\update-client.ps1 -ClientId <cliente> -TargetRef <tag-o-commit>
Remove-Item Env:BACKUP_ENCRYPTION_PASSPHRASE
```

El script fija image IDs actuales, copia un motor de recuperación, crea backup, cambia al target, ejecuta preflight/migración, arranca sin build/pull y escribe `.env.<cliente>.update-state.json`. Si falla, intenta volver al commit/imágenes anteriores y restaurar el backup.

## Criterio de éxito

- Seis servicios healthy; Alembic head y readiness PASS.
- Versión reportada = release target.
- Login/RBAC, presupuesto y módulos habilitados PASS.
- Sin aumento de 5xx/DLQ/latencia ni pérdida de datos.
- Backup y estado de rollback presentes.

## Rollback manual controlado

```powershell
$env:BACKUP_ENCRYPTION_PASSPHRASE = '<gestor de secretos>'
.\scripts\rollback-client.ps1 -ClientId <cliente>
Remove-Item Env:BACKUP_ENCRYPTION_PASSPHRASE
```

El script exige el state file, motor de recovery, backup e image IDs exactos. Restaura aplicación y datos y ejecuta health. No borre esos artefactos hasta cerrar la ventana.

## Abort conditions

- Migración/head incorrecto.
- Readiness no recupera en 10 minutos.
- Acceso cruzado, discrepancia financiera, aprobación duplicada o secreto en logs.
- Error rate crítico, DLQ creciente o restore/rollback no disponible.

La actualización/rollback final de la candidata no se considera verificada hasta un ensayo completo documentado en [`FINAL_TEST_REPORT.md`](FINAL_TEST_REPORT.md).
