# Plataforma empresarial de agentes IA

Plataforma de instalación aislada por cliente que integra un núcleo transaccional propio, Chatwoot, Activepieces y FlowWink. La arquitectura está preparada para el MVP de Ofideep, con PrestaShop como fuente oficial del catálogo y GHL como CRM comercial.

## Estado verificado

**Decisión actual: `NOT PRODUCTION READY — CRITICAL RISK`** (ver `docs/PRODUCTION_READINESS.md`, única fuente autoritativa).

Estado de la remediación en la rama `production-remediation` (2026-08-03):

- Seis P0, quince P1 y dos P2 verificados con evidencia reproducible; 14 defectos abiertos (11 P1, 3 P2).
- Corpus combinado de 228 pruebas (`pytest tests bridge-api/tests`) verde en ambos órdenes de colección.
- Migraciones Alembic aditivas hasta la revisión `0005`; downgrades preservadores.
- Portal con typecheck, build y tests de componentes/accesibilidad (vitest + axe) verdes.
- `pip-audit` y `npm audit --omit=dev` sin vulnerabilidades (`scripts/audit_dependencies.py`).

Los informes previos a la remediación (`docs/REMEDIATION_REPORT.md`, `docs/MASTER_PLATFORM_REPORT.md`, `docs/FINAL_REPORT.md`, `docs/COMMERCIAL_READINESS_REPORT.md`) están marcados como **SUPERSEDED** y no deben usarse para decisiones actuales. No se declara preparación para producción ni piloto comercial hasta superar los gates de `docs/PRODUCTION_READINESS.md`.

## Arquitectura

- **Bridge API:** autenticación, RBAC, catálogo cacheado, precios, existencias, presupuestos, pedidos, borradores de factura, aprobaciones, auditoría, RAG y costes.
- **PrestaShop:** fuente oficial de productos, características, combinaciones, reglas de precio y stock.
- **GHL:** contactos, oportunidades, notas y seguimiento comercial.
- **Chatwoot:** widget, conversaciones y transferencia a empleados.
- **Activepieces:** automatizaciones e integraciones externas.
- **FlowWink:** interfaz/capa de agentes; no es la base transaccional.
- **Portal:** React + TypeScript, en español, con autenticación real y modo claro/oscuro.

## Aprovisionamiento recomendado

### Linux o macOS

```bash
./scripts/provision-client.sh ofideep ofideep.local 9000
```

### Windows PowerShell

```powershell
pwsh -File .\scripts\provision-client.ps1 `
  -ClientId "ofideep" `
  -Domain "ofideep.local" `
  -ProxyPort 9000
```

El script genera `.env.ofideep`, secretos independientes y una instalación Docker con el proyecto `agent-ofideep`.

## Hosts locales predeterminados

Todos atraviesan el proxy en el puerto configurado:

- Portal: `http://ofideep.local:9000`
- API: `http://api.ofideep.local:9000`
- Chatwoot: `http://chat.ofideep.local:9000`
- FlowWink: `http://agents.ofideep.local:9000`
- Activepieces: `http://automation.ofideep.local:9000`

En producción deben configurarse DNS y TLS reales.

## Comandos

```bash
make check CLIENT_ID=ofideep
make build CLIENT_ID=ofideep
make up CLIENT_ID=ofideep
make health CLIENT_ID=ofideep
make logs CLIENT_ID=ofideep
make test
make test-coverage
```

## Configuración de Chatwoot

Después de crear la cuenta e inbox:

```bash
python scripts/configure-chatwoot-webhook.py \
  --env-file .env.ofideep \
  --account-id <ID_CUENTA> \
  --api-token <TOKEN_CHATWOOT>
```

El script crea el webhook real, guarda el secreto de firma fuera de la salida estándar y reinicia únicamente Bridge API.

## Configuración de PrestaShop y GHL

Completar en `.env.ofideep`:

```dotenv
PRESTASHOP_BASE_URL=https://tienda.example.com
PRESTASHOP_API_KEY=...
PRESTASHOP_SHOP_ID=

GHL_API_TOKEN=...
GHL_LOCATION_ID=...
GHL_PIPELINE_ID=...
GHL_PIPELINE_STAGE_ID=...
```

El acceso de PrestaShop debe limitarse a lectura. La sincronización empieza en modo simulación:

```http
POST /integrations/prestashop/sync?limit=300&dry_run=true&include_details=true
```

La sincronización incluye características, combinaciones, existencias y reglas de precio disponibles. Los importes fiscales siguen la configuración de cada instalación y deben validarse con el cliente.

## Copias y restauración

Las copias integrales requieren una contraseña de cifrado:

```bash
export BACKUP_ENCRYPTION_PASSPHRASE='una-frase-larga-y-segura'
make backup CLIENT_ID=ofideep
make restore CLIENT_ID=ofideep ARCHIVE=backups/ofideep/<archivo>.tar.gz.enc
```

La restauración debe ensayarse en una instalación vacía antes del piloto.

## Documentación principal

- `docs/REMEDIATION_REPORT.md`
- `docs/LIVE_VALIDATION_CHECKLIST.md`
- `docs/SECURITY.md`
- `docs/INSTALLATION.md`
- `docs/BACKUP_RESTORE.md`
- `docs/API_REFERENCE.md`
- `STATUS.md`
- `TASKS.md`

Los informes originales no verificados se conservan únicamente como historial en `docs/archive/unverified-original/`.
