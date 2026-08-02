# Manifiesto de despliegue actual

**Estado:** plantilla sin release comercial firmada.

## Modelo

- Una instalación aislada por cliente.
- Proyecto Compose: `agent-<client-id>`.
- Archivo de entorno: `.env.<client-id>`.
- Único puerto público: proxy inverso.
- Servicios internos: Bridge API, bases de datos, Redis, workers, portal, Chatwoot, Activepieces y FlowWink.

## Release

No existe todavía un tag comercial verificado. Antes de publicar una release deben registrarse:

- commit exacto;
- tag firmado o protegido;
- digests de imágenes;
- SBOM;
- migraciones;
- resultados Docker/E2E;
- limitaciones;
- procedimiento de rollback probado.

## Comando base

```bash
./scripts/provision-client.sh <client-id> <dominio> <puerto-proxy>
```

La salida debe validarse con `scripts/check-health.sh` y `docs/LIVE_VALIDATION_CHECKLIST.md`.
