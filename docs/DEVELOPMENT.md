# Desarrollo

## Preparación backend

Use Python 3.12 para aproximarse a la imagen runtime:

```powershell
py -3.12 -m venv .venv-dev
.\.venv-dev\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --require-hashes -r bridge-api\requirements-dev.lock
$env:PYTHONPATH = "bridge-api"
```

Los tests fijan SQLite/entorno hermético desde `tests/conftest.py`; no deben heredar credenciales PrestaShop/GHL del operador ni tocar red.

```powershell
pytest tests bridge-api\tests -q
python scripts\quality_gates.py
```

Para PostgreSQL use exclusivamente una DB desechable ligada al `P0_VERIFY_RUN_ID` y el acknowledgement exigido por `verify_p0_postgres.py`; el verificador rechaza nombres que no coinciden. Nunca lo apunte a una instancia real.

## Portal

```powershell
Set-Location portal
npm ci --include=optional
npm run format:check
npm run typecheck
npm test
npm run build
npm audit --audit-level=high
```

No use datos demo como si fueran negocio real. Los tests pueden usar fixtures explícitas; el Portal filtra identificadores demo de manera defensiva, pero la autoridad es el backend.

## Compose local

El perfil `core` sirve para integración local ligada a loopback. Use un nombre de proyecto y puerto exclusivos:

```powershell
.\bootstrap.ps1 -ClientId dev-local -Domain dev-local.local -ProxyPort 19000 -Profile core
```

`development` habilita pilot/debug y no se mezcla con `production`. `docker-compose.preview.yml` solo publica Bridge/Chatwoot en loopback para QA; nunca combinarlo con el overlay production.

## Convenciones

- Migraciones Alembic aditivas y con tests clean/upgrade/downgrade.
- Toda entidad propia con installation scope y constraints compuestas.
- Mutaciones reintentables: `Idempotency-Key`; ediciones: `If-Match`.
- Operaciones sensibles: draft/pending approval; sin automatismo por defecto.
- No capturar excepciones para devolver 2xx falso.
- No imprimir secrets, cuerpos documentales o PII innecesaria.
- Actualizar API, tests, threat model y limitaciones con cada contrato nuevo.

## Antes de integrar

Ejecute corpus backend, quality, Portal completo, `git diff --check` y los verificadores infra. Un build local no sustituye la CI ni el candidate E2E.
