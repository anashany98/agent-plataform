# Instalación

## Prerrequisitos

- Host Linux x86_64 o Windows 11 + Docker Desktop/WSL2.
- Docker Engine y Compose v2 funcionales.
- Git y Python 3 para preflight/scripts; OpenSSL para TLS/backup.
- DNS público para `PORTAL_HOST` y `API_HOST`.
- Certificado leaf público y clave que cubran ambos SAN.
- 30 GiB libres recomendados (el preflight bloquea por debajo de 15 GiB).
- Puertos 80/443 libres o una terminación TLS externa equivalente aprobada.
- Checkout limpio de una release/tag revisado; imágenes release ya construidas/escaneadas.

## Identidad de la instalación

El identificador debe cumplir `^[a-z0-9][a-z0-9-]{1,48}$`. Para `acme`, use:

- proyecto Compose `agent-acme`;
- archivo `.env.acme`;
- `INSTALLATION_ID=acme`;
- manifest `.env.acme.release.json`.

No reutilice ninguno de estos recursos para otro cliente.

## Provisionar de forma canónica

En Windows, desde el checkout dedicado y limpio:

```powershell
.\scripts\provision-client.ps1 `
  -ClientId acme `
  -Domain plataforma.example.com `
  -Profile production `
  -TlsCertificate C:\secure\fullchain.pem `
  -TlsPrivateKey C:\secure\privkey.pem
```

En Linux, el contrato equivalente es:

```bash
./scripts/provision-client.sh acme plataforma.example.com 9000 production \
  /secure/fullchain.pem /secure/privkey.pem
```

El provisionador no sobrescribe `.env.acme`, genera secretos, versión e imágenes, ejecuta preflight bootstrap, build, manifest, arranque sin rebuild y health. Al terminar crea `provision-acme.txt` con la contraseña temporal: muévala al canal seguro, cambie la contraseña y elimine el recibo según la política de secretos.

Después de generar el manifest, el release owner debe ejecutar también el preflight en `--mode release` mostrado abajo y archivar su salida. El preflight `bootstrap` del provisionador no sustituye ese gate final.

El provisionado genera una versión inmutable `0.9.1-<sha12>` a partir de `pyproject.toml`; Compose propaga `APP_VERSION/RELEASE_VERSION`, y tanto preflight como manifiesto rechazan versiones no SemVer o que contengan `dev`. La implementación está cerrada en código, pero la evidencia del runtime candidato sigue formando parte del gate final: no reutilice valores de un stack de desarrollo.

Use `-NoStart` en PowerShell o `NO_START=true` en Linux si el release owner solo debe generar/validar la configuración antes de una ventana. Nunca confirme `.env.acme`, certificados, clave privada, manifest local o recibo de bootstrap.

## Flujo manual del release owner

Si la organización separa generación, build y arranque, parta del `.env.acme` generado con `NoStart`; no copie una plantilla incompleta ni invente secretos. Confirme que `RELEASE_VERSION`, `SOURCE_COMMIT` y las imágenes Bridge/Portal son inmutables antes de continuar.

## Validar sin arrancar

```powershell
python scripts/production-preflight.py `
  --env-file .env.acme `
  --profile production `
  --mode release
```

Debe terminar `preflight=PASS`. Un warning de certificado autofirmado solo es admisible en `bootstrap` aislado y nunca en release.

## Construir y registrar la release

Ejecutar desde el commit limpio que coincide con `SOURCE_COMMIT`:

```powershell
docker compose --env-file .env.acme -p agent-acme `
  -f docker-compose.yml `
  -f infrastructure/compose/docker-compose.prod.example.yml `
  --profile production build --pull

python scripts/create-release-manifest.py --env-file .env.acme
python scripts/production-preflight.py --env-file .env.acme --profile production --mode release
```

El manifest valida image ID, repo digests y labels OCI de Bridge/Portal. No reconstruya después de generarlo.

## Arrancar sin reconstruir ni descargar

```powershell
docker compose --env-file .env.acme -p agent-acme `
  -f docker-compose.yml `
  -f infrastructure/compose/docker-compose.prod.example.yml `
  --profile production up -d --no-build --pull never --wait --wait-timeout 600

.\scripts\check-health.ps1 -ClientId acme -Profile production
```

Compruebe que solo `tls-proxy` publica puertos, Alembic está en head y `/ready` responde por el dominio API.

## Primer acceso

1. Abra `https://<PORTAL_HOST>`.
2. Inicie sesión con el usuario bootstrap por el canal seguro.
3. Cambie inmediatamente la contraseña temporal.
4. Cree una cuenta administrativa nominativa y deshabilite el uso cotidiano del bootstrap.
5. Pruebe logout y que la sesión anterior sea rechazada.

## Gate posterior

No entregue a usuarios hasta completar la matriz E2E, backup+restore, rollback, scans, rendimiento y checklist de onboarding. Consulte [`PRODUCTION.md`](PRODUCTION.md) y [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md).
