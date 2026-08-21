> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Documento histórico; sus estados, rutas o contratos pueden no corresponder al árbol actual. Consulte `docs/PRODUCTION_READINESS.md` y la documentación canónica homónima de 2026-08-15.

# Backup & Restore Procedures

## Database Backup
To create a SQL dump of `bridge-db`:
```bash
make backup
```
The dump file is stored in `infrastructure/backups/bridge_db_YYYYMMDD_HHMMSS.sql`.

## Database Restore
To restore from a SQL dump:
```bash
cat infrastructure/backups/bridge_db_YYYYMMDD_HHMMSS.sql | docker exec -i bridge-db psql -U bridge_user bridge_db
```
