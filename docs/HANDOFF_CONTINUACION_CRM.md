# HANDOFF — Brief de continuación para el siguiente agente de IA

> **Propósito:** que otro agente de IA pueda retomar este proyecto sin contexto
> previo y continuar el trabajo de forma coherente con lo ya hecho. Léelo
> completo antes de tocar nada. Después lee `agents.md` (misión raíz) y
> `docs/PRODUCT_PLAN_CRM_B2B.md` (plan de producto).
>
> **Fecha del handoff:** 2026-08-16. **Último estado verde:** corpus backend
> 510 passed / 11 skipped, portal 53 tests vitest, quality gates D-030 PASS.

---

## 1. Qué es este proyecto

`agent-plataform` es una plataforma empresarial de agentes IA por instalación
aislada por cliente. Hoy se está reposicionando como **CRM B2B de ventas +
back-office comercial por instancia gestionada** (ver
`docs/PRODUCT_PLAN_CRM_B2B.md`).

Componentes principales:

- **Bridge API** (`bridge-api/`): FastAPI + SQLAlchemy (SQLite en tests,
  PostgreSQL en runtime). Núcleo transaccional: catálogo, precios, stock,
  presupuestos, pedidos, facturas, aprobaciones, RBAC, auditoría, RAG,
  automatizaciones y el CRM local.
- **Portal** (`portal/`): React + TypeScript (Vite), en español, con RBAC y
  modo claro/oscuro.
- **Integraciones:** PrestaShop (catálogo), GHL (CRM externo), Chatwoot (chat),
  Activepieces (automatizaciones). El core funciona SIN ellas (proveedores
  locales).
- **Docs de control:** `TASKS.md` (trabajo), `STATUS.md` (estado),
  `BLOCKERS.md` (bloqueos), `CHANGELOG.md` (historial),
  `docs/PRODUCTION_READINESS.md` (decisión autoritativa de producción).

**Decisión de producción actual:** `NOT PRODUCTION READY — REMEDIATION
INCOMPLETE` (los stop-ships SS-01..SS-07 siguen abiertos salvo SS-04 y SS-05).
Esto es importante: el trabajo de CRM que se está haciendo es **funcionalidad
nueva**, no cierra defectos P0/P1 existentes ni cambia esa decisión.

---

## 2. Cómo ejecutar todo (importante — el entorno tiene trucos)

Estás en **Windows + Git Bash**. Python 3.11 del sistema con las dependencias
ya instaladas (`bridge-api/requirements-dev.txt`). Node/npm disponibles en
`portal/` con `node_modules` presentes.

### Tests del backend (corpus hermético)

```bash
cd /c/Users/Usuario/Desktop/Agent/agent-plataform
PYTHONPATH=bridge-api python -m pytest tests bridge-api/tests -q
```

- `PYTHONPATH=bridge-api` es **obligatorio** (el paquete `app` vive dentro de
  `bridge-api/`). Sin él: `ModuleNotFoundError: No module named 'app'`.
- `tests/conftest.py` fija TODAS las variables de entorno (SQLite efímero en
  `/tmp`, instalación `test-installation`, LLM mock, etc.) para hermeticidad
  D-032. Los tests nunca dependen del `.env` del operador.
- Un test de un solo archivo:
  `PYTHONPATH=bridge-api python -m pytest tests/regression/test_p1_custom_fields_scoring.py -q`
- Los `SKIPPED` (11) son opt-in deliberados (PostgreSQL real, PrestaShop real,
  Python 3.12, `/dev/tcp` en Windows). No intentes "arreglarlos".

### Portal

```bash
cd /c/Users/Usuario/Desktop/Agent/agent-plataform/portal
npm run typecheck   # tsc --noEmit
npm run test        # vitest (una sola pasada)
npm run build       # tsc && vite build
```

### Quality gates (hay que pasarlos SIEMPRE antes de dar por terminado algo)

```bash
cd /c/Users/Usuario/Desktop/Agent/agent-plataform
python scripts/quality_gates.py --with-portal
```

Puertas: `ruff-hard` (E9,F a 0), `ruff-clean-zone` (reglas completas sobre la
zona limpia a 0), `ruff-ratchet` (deuda legacy ≤ baseline en
`scripts/quality_baseline.json`), y `portal` (typecheck + tests).

- Si el ratchet dice "La deuda se redujo: ejecute --update-baseline", ejecuta
  `python scripts/quality_gates.py --update-baseline` (recalcula total Y
  desglose `by_rule`).
- La zona limpia incluye `tests/`, `bridge-api/tests/` y varios servicios. El
  código nuevo en `bridge-api/app/main.py` cae en la zona legacy (ratchet): no
  añadas deuda de estilo nueva; el código nuevo en tests debe ser ruff-limpio.

---

## 3. Invariantes del proyecto (NO te las saltes)

Todo módulo nuevo DEBE respetar estas reglas, que son la razón de que el
corpus sea verde y la plataforma sea auditable:

1. **Aislamiento por instalación (tenant).** Los modelos heredan
   `InstallationOwnedMixin` (inyecta `installation_id` por contexto ORM,
   deny-by-default). Toda constraint única relevante es por instalación:
   `uq_<entidad>_installation_<campo>`, y siempre
   `uq_<entidad>_installation_id`. Las FKs entre tablas owned son compuestas
   `(installation_id, ...)` con `deferrable=True, initially="DEFERRED"`.

2. **Migraciones Alembic idempotentes y no destructivas.**
   - Idempotentes: `if "<tabla>" not in _table_names():` antes de crear.
   - `downgrade()` vacío con comentario (política: los datos de negocio nunca
     se destruyen).
   - El head actual es **`0018`**. La siguiente migración será `0019`, con
     `down_revision = "0018"`.
   - Hay un test de paridad estricta migraciones↔modelos
     (`test_clean_install_upgrades_to_explicit_model_schema`): los ÍNDICES con
     nombre deben coincidir exactamente. Si un modelo usa `index=True` en una
     columna, la migración debe crear `ix_<tabla>_<columna>`; y el mixin aporta
     `ix_<tabla>_installation_id`. Replicar los nombres tal cual.

3. **RBAC en cada endpoint.** `Depends(require_roles(*READ_ROLES))` para leer,
   `*OPERATOR_ROLES` para operar, `*ADMIN_ROLES` para administrar. Están en
   `app/security.py`. Los roles: `provider_admin`, `client_admin` (admin);
   `supervisor`, `commercial`, `support`, `operator` (operador); `viewer`
   (lectura).

4. **Auditoría en cada mutación.** Llamar a `_audit(db, event_type=...,
   status_value=..., details={...}, principal=principal)` con un `event_type`
   estable tipo `dominio.accion` (p. ej. `custom_field.created`).

5. **Idempotencia en mutaciones de API.** Endpoints que crean datos requieren
   cabecera `Idempotency-Key` (sin ella, 428) y usan el patrón
   `_begin_idempotent_mutation(...)` / `_complete_idempotency(...)` /
   `_fail_idempotency(...)`. El `dry_run` queda exento. Mira `create_lead`,
   `import_leads` o `upsert_custom_value` como referencia.

6. **Sin mocks de producción ni datos inventados.** Si un proveedor externo no
   está disponible, el código degrada a un proveedor local honesto o devuelve
   error explícito; nunca finge éxito.

7. **Documentación al cerrar cada módulo.** Actualizar `TASKS.md` (fila nueva),
   `STATUS.md` (entrada de bloque `> **...**` arriba), `CHANGELOG.md` (bloque
   `## [...]` arriba). Es obligatorio, no opcional.

---

## 4. Lo que ya está hecho (contexto inmediato)

Plan CRM B2B (`docs/PRODUCT_PLAN_CRM_B2B.md`, tarea paraguas **T-044** en
`TASKS.md`). Bloque P1 "núcleo vendible (M1 = Pro)":

| Módulo | Fila | Estado |
|---|---|---|
| Kanban de pipeline (etapas, drag&drop, cola de leads) | T-043 | VERIFIED |
| Reporting de ventas (funnel, ticket medio, win-rate, aging) | T-045 | VERIFIED |
| Timeline de interacción por lead | T-046 | VERIFIED |
| Actividades de comercial (tareas + recordatorios email) | T-047 | VERIFIED |
| **Campos personalizados por instalación** | **T-048** | **VERIFIED** |
| **Lead scoring básico en la cola** | **T-049** | **VERIFIED** |

Bloque P2 "crecimiento":

| Módulo | Fila | Estado |
|---|---|---|
| **Import/export CSV de leads** | **T-050** | **VERIFIED** |
| Email integrado (plantillas, firma, apertura/clics) | — | pendiente |
| Campañas segmentadas | — | pendiente |
| Calendario de comercial | — | pendiente |
| API pública + webhooks salientes | — | pendiente |
| SSO/OIDC + MFA | — | pendiente |

(Los tres módulos en negrita son los que se implementaron en la sesión del
2026-08-16; detalle en `docs/SESSION_LOG_CRM_2026-08-16.md`.)

Bloque P3 "enterprise" (pendiente): tickets/SLA, equipos, multi-tenant RLS,
billing, SCIM, BI. Datos maestros (pendiente): separar cuenta/contacto, merge,
probabilidad por etapa, motivo de pérdida/ganancia.

---

## 5. Patrones de referencia (cópialos, no reinventes)

Para añadir un módulo nuevo, usa estos archivos como plantilla:

| Pieza | Referencia |
|---|---|
| Modelo tenant-owned | `CustomFieldDefinition` / `Activity` en `bridge-api/app/models/models.py` |
| Migración idempotente | `bridge-api/alembic/versions/0017_activities.py` y `0018_custom_fields.py` |
| Endpoint CRUD con RBAC + auditoría | actividades / campos personalizados en `bridge-api/app/main.py` |
| Upsert idempotente con `Idempotency-Key` | `upsert_custom_value` y `import_leads` en `main.py` |
| Test hermético backend | `tests/regression/test_p1_custom_fields_scoring.py` (fixture `scoring_env`, seeds con `SessionLocal`, limpieza) |
| Componente de portal | `portal/src/customFields.tsx`, `portal/src/activities.tsx` |
| Test vitest del portal | `portal/src/customFields.test.tsx` (mock de `globalThis.fetch`) |
| Pestaña en la sección Clientes | `ClientesSection` en `portal/src/App.tsx` |

Estructura típica de un test backend: un fixture que crea usuarios
(`commercial`, `viewer`) con `_create_user` + `_login`, helpers de siembra que
insertan directo por `SessionLocal` con ids únicos (`uuid.uuid4().hex[:8]`), y
cleanup en `finally` borrando esas filas.

---

## 6. Qué hacer a continuación (priorizado)

Continúa por el plan CRM. Orden sugerido:

1. **Webhooks salientes + API pública (P2-f).** Es el siguiente de mayor valor
   y la infraestructura YA existe: `app/services/automations.py::send_webhook`
   (firma HMAC + allowlist anti-SSRF `_assert_outbound_url_allowed`) y el
   outbox durable (`app/services/outbox.py`). Diseña un modelo
   `WebhookSubscription` (url, secret, eventos suscritos, activo) con su
   migración `0019`, CRUD auditado y un dispatcher que, al producirse eventos
   CRM (lead creado, cambio de etapa, pedido confirmado…), encole el payload
   firmado por el outbox. Añade evals herméticos (sin red real) y una sección
   en el portal.
2. **Email integrado (P2).** Plantillas, firma y tracking de apertura/clics
   sobre el `SmtpEmailProvider` y el spool local ya existentes
   (`app/services/smtp_provider.py`, `automations.send_email`).
3. **Calendario de comercial (P2).** Vistas diaria/semanal sobre las
   actividades ya existentes (`Activity.due_at`).
4. **Campañas segmentadas (P2).** Sobre el spool/SMTP y la segmentación por
   campos personalizados y score ya existentes.
5. Después, datos maestros y el bloque P3 según el plan.

Para cada módulo: respeta las invariantes de la sección 3, añade evals
herméticos backend + vitest portal, pasa el corpus completo y los gates, y
documenta en `TASKS.md` / `STATUS.md` / `CHANGELOG.md`.

**No intentes cerrar los stop-ships SS-01..SS-07 ni la decisión de producción**
salvo que te lo pidan explícitamente: requieren infraestructura real (TLS/DNS,
imágenes por digest, soak, delivery de alertas) y decisiones del propietario
que están fuera del alcance de una sesión de código.

---

## 7. Trampas conocidas (ahorran tiempo)

- **`_lead_score` y cualquier score del CRM es determinista** (sin LLM/red).
  No lo conviertas en no determinista sin necesidad; los tests lo assertan.
- **El test de paridad de migraciones es estricto con los nombres de índice.**
  Si la migración y el modelo discrepan en un índice nombrado,
  `test_clean_install_upgrades_to_explicit_model_schema` falla.
- **`--update-baseline`** actualiza total y desglose; si un test de baseline
  falla por desglose desincronizado, ejecútalo.
- **`GET /leads/export.csv` debe registrarse ANTES que rutas parametrizadas**
  tipo `/leads/{lead_id}` si alguna vez se crean, o FastAPI lo shadoweará.
- En Windows, algunos tests de red/puertos se saltan a propósito; no los
  fuerces.
- El portal parsea los detalles de error de FastAPI (`detail`); devuelve
  mensajes en español coherentes con el resto de la UI.
- No hagas commit ni push a menos que te lo pidan (el workspace no tiene
  remote configurado; hay 250+ cambios sin commitear de sesiones previas).

---

## 8. Definición de "hecho" para un módulo

Un módulo está terminado SOLO si:

1. El código respeta las invariantes de la sección 3.
2. `PYTHONPATH=bridge-api python -m pytest tests bridge-api/tests -q` pasa
   verde (sin nuevos fallos).
3. `npm run typecheck`, `npm run build` y `npm run test` pasan en `portal/`.
4. `python scripts/quality_gates.py --with-portal` da `Quality gates D-030: OK`.
5. Hay filas/entradas nuevas en `TASKS.md`, `STATUS.md` y `CHANGELOG.md`.
6. (Opcional, si Docker está operativo) validación en vivo contra el stack
   candidato `agent-candidate-0815` siguiendo `docs/LIVE_VALIDATION_CHECKLIST.md`.
