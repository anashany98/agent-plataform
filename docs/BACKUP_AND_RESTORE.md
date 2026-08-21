# Backup y restore

## Contrato del formato 4

El script `scripts/backup-restore-integral.py` captura, por cliente/perfil:

- dumps PostgreSQL en formato custom;
- `bridge_uploads` y `bridge_automation_email`;
- `.env.<cliente>` dentro del paquete cifrado;
- release manifest en production;
- manifest y checksums internos.

Usa quiesce de writers por defecto, AES-256-CBC con PBKDF2 (200.000 iteraciones), HMAC-SHA256 del ciphertext y checksum SHA-256 externo. El restore rechaza traversal, tipos/archivos no permitidos, cliente/proyecto/perfil/config/manifest distintos y dumps que no restauren en una DB de verificación.

## Crear backup

```powershell
$env:BACKUP_ENCRYPTION_PASSPHRASE = '<obtener del gestor de secretos>'
python scripts/backup-restore-integral.py backup <cliente> --profile production
Remove-Item Env:BACKUP_ENCRYPTION_PASSPHRASE
```

Conservar juntos `.tar.gz.enc`, `.hmac` y `.sha256`, pero custodiar la passphrase por un canal distinto. Copiar a storage externo inmutable/configurado y registrar tamaño, checksum, fecha, release, cliente y resultado; nunca el secreto.

## Restore controlado

`restore` es destructivo para los datos actuales del proyecto destino después de validar el paquete y crear un backup de seguridad. Ejecútelo solo en una instalación vacía/de recuperación o con cambio aprobado.

```powershell
$env:BACKUP_ENCRYPTION_PASSPHRASE = '<obtener del gestor de secretos>'
python scripts/backup-restore-integral.py restore <cliente> `
  infrastructure/backups/<cliente>/<archivo>.tar.gz.enc `
  --profile production
Remove-Item Env:BACKUP_ENCRYPTION_PASSPHRASE
```

El `.env.<cliente>` y release manifest actuales deben coincidir byte a byte con el backup. El script verifica cada dump en una DB temporal, crea un safety backup, detiene writers, restaura DB/volúmenes y arranca con `--no-build --pull never`.

## Validación posterior

- Todos los servicios healthy, migraciones head y `/ready` 200.
- Login y revocación.
- Conteos y muestras de clientes, catálogo, transacciones y auditoría.
- RAG: documento/chunks/cita; uploads presentes.
- Wiki/landing: estados y ruta pública solo aprobada.
- Scheduler/outbox/spool: estados y archivos consistentes.
- `installation_id`, release y manifest correctos.

Medir RTO desde inicio del restore hasta smoke PASS. RPO es la distancia entre el último dato confirmado y el backup restaurado. No declarar objetivos hasta obtener medición con volumen representativo.

## Retención propuesta

Diario 7 días, semanal 5 semanas y mensual 12 meses, sujeto a contrato/privacidad/capacidad. Probar restore al menos trimestralmente y después de cambios de formato/migración. Esta política debe aprobarla el dueño de datos.

## Estado actual

El formato/verificador está en PASS, pero el restore integral de la candidata final sigue `PENDING`; por tanto, el criterio de producción 15 permanece abierto.
