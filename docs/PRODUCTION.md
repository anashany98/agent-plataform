# Despliegue de producción

## Alcance certificado objetivo

Solo `production`: Bridge, Portal, PostgreSQL, Redis, reverse proxy y TLS. Sin vendors, egress, LLM externo, PrestaShop, GHL o envío de correo. Embeddings/retrieval `local_tfidf`; email en spool manual.

## Precondiciones GO

- Los 30 criterios de [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md) cerrados o limitaciones explícitamente aceptadas.
- Commit/tag limpio, SemVer, images/SBOM/checksums/Trivy y manifest coherentes.
- DNS y certificado leaf público válidos; secrets únicos y rotables.
- Backup de la versión anterior y restore/rollback ensayados.
- Ventana, responsables, observación y criterio de abortar definidos.

## Parámetros de seguridad

Mantener `PILOT_MODE`, demo, mocks, stubs, debug y automatismos en `false`; Redis/outbox/scheduler en `true`; CORS/hosts exactos; `TRUSTED_PROXY_COUNT=2`; providers LLM `none`; embedding `local_tfidf`; email `local`. Habilitar pedidos/facturas únicamente tras UAT y manteniendo automatismos desactivados.

## Comando de despliegue

```powershell
python scripts/production-preflight.py --env-file .env.<cliente> --profile production --mode release

docker compose --env-file .env.<cliente> -p agent-<cliente> `
  -f docker-compose.yml `
  -f infrastructure/compose/docker-compose.prod.example.yml `
  --profile production up -d --no-build --pull never --wait --wait-timeout 600

.\scripts\check-health.ps1 -ClientId <cliente> -Profile production
```

No usar `--build`, `pull` implícito, `latest`, el proyecto `agent-platform` de desarrollo o certificados autofirmados.

## Verificación inmediata

1. `docker compose ps`: seis servicios running/healthy.
2. Solo TLS proxy publica puertos; DB/Redis/API no aparecen en `docker port`.
3. `/live` muestra la versión esperada y `/ready` devuelve 200.
4. Login/cambio/logout y rol viewer/operator/admin.
5. Smoke de cada módulo habilitado; acciones automáticas siguen off.
6. Logs sin secrets/stack traces sensibles; correlation IDs presentes.
7. Backup inicial, checksum/HMAC y copia externa autorizada.

## Activación gradual

1. Lectura/dashboard/RAG.
2. Import y CRM local.
3. Presupuestos.
4. Pedidos manualmente confirmados.
5. Borradores de factura + aprobación.
6. Wiki/landing local + aprobación.
7. Agentes/scheduler con allowlists y presupuesto.

Detener el rollout ante 5xx persistentes, readiness 503, DLQ creciente, error de aislamiento, discrepancia financiera, efecto duplicado o logs con secreto/PII.

## Exclusiones

No activar `full`, egress, servicios externos, SMTP, emisión fiscal o publicación externa dentro de este despliegue. Cada ampliación requiere threat model, secrets, tests contractuales, sandbox, rollback y nueva decisión.
