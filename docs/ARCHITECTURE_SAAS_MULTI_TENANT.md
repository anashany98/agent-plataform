# Propuesta de arquitectura: evolución a SaaS multi-tenant

**Estado:** propuesta de diseño (sin implementar).
**Fecha:** 2026-08-15.
**Referencias:** `PRODUCTION_READINESS.md` (NOT PRODUCTION READY), `TASKS.md` P0-006,
`tests/regression/test_p0_model_tenant_isolation.py`.

---

## 1. Resumen ejecutivo

Hoy la plataforma es **single-tenant por despliegue**: una instalación = un
contenedor/stack = una BD PostgreSQL = un `INSTALLATION_ID` constante (env).
Las 24 tablas de dominio llevan columna `installation_id` no nula y el
aislamiento se hace **en la capa de aplicación** (ORM deny-by-default), no en
la base de datos. Vender la misma app a N clientes hoy implica desplegar N
stacks.

Esta propuesta evoluciona el despliegue a **una BD PostgreSQL compartida con
varios tenants** sin reescribir el dominio:

1. **La columna ya existe** en las 24 tablas owned: solo hay que *resolver*
   el tenant por petición (hoy es una constante de despliegue) en lugar de
   por entorno.
2. **Row-Level Security (RLS) de PostgreSQL** como defensa en profundidad:
   la BD *niega* por sí misma cualquier fila de otro tenant, incluso SQL
   crudo, migraciones o errores de la aplicación.
3. **Tiers de suscripción** como tabla de catálogo de tenants + límites
   computados en la capa de servicio (402/429), sin cambiar el modelo.

Riesgo total bajo: el cambio más grande es la **resolución de tenancy**
(una función) y una **migración de datos** (backfill de un único
`INSTALLATION_ID` por BD). El enforcement ORM actual, las FKs compuestas y
el backup/restore se conservan intactos.

> Nota de nomenclatura: la auditoría P0-006 citaba 14 modelos owned; el
> inventario actual del mixin `InstallationOwnedMixin` es de **24 modelos**
> (User, AuditLog, DailyLLMBudget, IdempotencyRecord, OutboxMessage,
> ApprovalRequest, Customer, Lead, Opportunity, Product, Pricelist, Quote,
> Order, StockReservation, InvoiceDraft, ConversationState,
> PrestashopSyncHistory, AgentDefinition, WikiPage, SEOProject, LandingPage,
> ScheduledTask, RAGDocument, RAGChunk). La propuesta cubre los 24.

---

## 2. Estado actual: cómo funciona la tenancy hoy

### 2.1 Modelo físico

- `InstallationOwnedMixin` añade `installation_id String(128) NOT NULL
  index`, con `default=get_current_installation_id()` (models.py).
- 24 tablas owned + 1 no owned: `installation_lifecycle` (una fila por
  instalación, PK = `installation_id`; controla export/erase/legal hold).
- FKs **compuestas** (`installation_id, id`) deferibles en 12 relaciones:
  customer→pricelist, quote→customer, order→customer/quote,
  reservation→order/product, invoice→order/customer,
  conversation→customer/quote/order, rag_chunk→document. Garantizan que una
  fila de un tenant nunca referencie a otra de otro tenant a nivel de BD.
- Índices únicos compuestos por instalación: `(installation_id, username)`,
  `(installation_id, source, external_id)`, `(installation_id, sku)`,
  `(installation_id, confirmation_token)`, etc.

### 2.2 Enforcement (aplicación, deny-by-default)

- **Lecturas**: `do_orm_execute` inyecta `with_loader_criteria(
  InstallationOwnedMixin, ... installation_id == current)` en **todo**
  SELECT ORM (models.py ~línea 1031). `identity_token` mantiene el
  identity-map tenant-aware (Session.get() no filtra por PK sin SQL).
- **Escrituras**: `before_flush` asigna `installation_id` a filas nuevas y
  rechaza cualquier operación entre instalaciones; `do_orm_execute` aplica
  el mismo criterio a UPDATE/DELETE masivos y a inserts por lotes.
- **Contexto**: `installation_scope(installation_id)` (ContextVar) selecciona
  el tenant activo en workers y tests; en producción el valor es la constante
  `settings.INSTALLATION_ID` del despliegue.

### 2.3 Qué se reutiliza y qué falta

| Ya existe (se reutiliza) | Falta para SaaS |
|---|---|
| Columna `installation_id` en las 24 tablas | Resolución del tenant por petición (hoy: env constante) |
| Enforcement ORM deny-by-default | RLS en la BD (defensa en profundidad) |
| FKs compuestas y unicidad por tenant | Catálogo de tenants (`tenants`) + estado de ciclo de vida multi-tenant |
| `installation_lifecycle` (erase/export/legal hold) | Facturación/tiers y límites |
| Rate limit por instalación (Redis) | Migración de datos (backfill) y backfill de índices |
| Backup/restore integral (SS-05, RPO/RTO medidos) | Per-tenant backup/export (para bajas de clientes) |

---

## 3. Objetivo y modelo de aislamiento

### 3.1 Alternativas consideradas

| Modelo | Coste operativo | Aislamiento | Recomendación |
|---|---|---|---|
| **A. BD compartida + RLS** | Un solo Postgres, pool compartido, pg_dump único | BD + app | **Recomendado** (primera fase) |
| B. BD compartida, esquema por tenant (`tenant_a.*`) | Migraciones y DDL por tenant | Alto, pero complejo operativamente | No |
| C. BD por tenant (multi-instancia, como hoy) | N Postgres → caro, sin agregación | Máximo | Fase 4 opcional (clientes enterprise con requisito de aislamiento físico) |

Se recomienda **A** para el SaaS: el enforcement ORM ya es sólido y
testeado; RLS añade la capa de BD que falta. C queda como oferta enterprise
premium (aislamiento físico) sin cambiar el producto — es el modelo de hoy.

### 3.2 Resolución de tenancy por petición

Hoy `get_current_installation_id()` = `settings.INSTALLATION_ID`.
En SaaS pasa a resolverse por petición:

```
jwt.tenant_id  →  tenant_id  →  get_current_installation_id()
   (subdominio o header X-Tenant-Id para webhooks no autenticados)
```

- **JWT**: el token lleva `tenant_id` (claim) firmado; `Principal` ya lo
  transporta si se añade el claim.
- **Webhooks/endpoints públicos** (Chatwoot, triggers de automatización,
  páginas públicas): el tenant se resuelve por subdominio
  (`cliente.bridge.app` → normalize) o header firmado. Los webhooks HMAC ya
  incluyen timestamp+payload; se añade el tenant al payload firmado.
- La función `get_current_installation_id()` **no cambia de firma**: cambia
  su origen (de env a ContextVar rellenada por el middleware de tenancy).
  Todo el enforcement ORM, workers, tests y `installation_scope` siguen
  funcionando sin tocar nada.

**Este es el cambio más pequeño y de mayor efecto del plan.**

### 3.3 Catálogo de tenants

Nueva tabla no owned:

```sql
CREATE TABLE tenants (
    id               text PRIMARY KEY,          -- antes installation_id
    slug             text UNIQUE NOT NULL,      -- subdominio: "distribuidora-a"
    display_name     text NOT NULL,
    status           text NOT NULL DEFAULT 'active',  -- active|suspended|erased
    tier             text NOT NULL DEFAULT 'starter',
    plan_started_at  timestamptz NOT NULL DEFAULT now(),
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
```

`installation_lifecycle` pasa a FK a `tenants.id` (borrado lógico y físico
por tenant, reutilizando el erase/export ya existentes).

---

## 4. Row-Level Security en PostgreSQL compartido

### 4.1 Política por tabla owned

Una migración Alembic (0014) genera para cada una de las 24 tablas owned:

```sql
ALTER TABLE products FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON products;
CREATE POLICY tenant_isolation ON products
    USING (installation_id = current_setting('app.tenant_id', true))
    WITH CHECK (installation_id = current_setting('app.tenant_id', true));
```

- `FORCE ROW LEVEL SECURITY` aplica la política **también al superusuario**:
  la BD niega por sí misma, sin depender de roles.
- `current_setting('app.tenant_id', true)`: `missing_ok=true` devuelve NULL
  (y la política niega todo) si la sesión no tiene tenant — **fail-closed**:
  una sesión huérfana no lee ni escribe nada.
- La migración genera las 24 políticas con un loop sobre
  `Base.metadata` filtrando `InstallationOwnedMixin` (mismo mecanismo que el
  test `test_all_tenant_owned_models_require_a_non_nullable_installation_id`),
  para que no haya tabla nueva sin política.

### 4.2 Fijar el tenant por sesión/transacción

```python
@event.listens_for(engine, "begin")
def _set_tenant_on_transaction(conn):
    tenant = get_current_installation_id()   # ContextVar de la petición
    conn.exec_driver_sql("SELECT set_config('app.tenant_id', :t, true)",
                         {"t": tenant})      -- SET LOCAL: solo esta transacción
```

- `set_config(..., true)` = `SET LOCAL`: el valor **nunca sobrevive** a la
  transacción, impidiendo fuga entre peticiones reutilizadas por el pool.
- El mismo evento cubre workers (`installation_scope`) y migraciones offline
  (que se ejecutan sin tenant activo → RLS niega todo → se usa
  `SET app.tenant_id` temporal solo en scripts de backfill).

### 4.3 Qué resuelve RLS y qué no

**Resuelve (defensa en profundidad):**
- SQL crudo (`text()`) que se escape del filtro ORM.
- Reportes/ad-hoc de operaciones que consultan directo.
- Errores de programación futuros que olviden el filtro.
- Lecturas por PK (`Session.get`) si el identity-token fallara.

**No reemplaza:**
- El enforcement ORM (RLS falla con NULL en sesiones sin tenant; el ORM da
  el error en castellano y con contexto).
- El control de acceso por rol (RLS es por *tenant*, no por *usuario* dentro
  del tenant; el RBAC actual por rol sigue en la app).
- El rendimiento: hay que verificar planes (índices compuestos
  `(installation_id, ...)` ya existen en las tablas de acceso caliente).

### 4.4 Backfill y migración de datos

Fase 1 (cada BD actual es de un solo tenant):

```sql
BEGIN;
-- 1) Crear el tenant único de la instalación actual.
INSERT INTO tenants (id, slug, display_name, tier)
SELECT DISTINCT installation_id, lower(installation_id), installation_id, 'starter'
FROM users;                                    -- 1 fila

-- 2) El backfill no hace falta: las 24 tablas ya tienen installation_id
--    correcto (default get_current_installation_id() en cada insert).

-- 3) Índices ya compuestos. Verificar:
SET app.tenant_id = (SELECT id FROM tenants LIMIT 1);
SELECT count(*) FROM products;                 -- RLS activo, sin filtrar nada raro
COMMIT;
```

El grueso de la migración es **operacional**: pasar de N despliegues a un
solo Postgres compartido (pg_dump/restore por instalación, deduplicar
`installation_id` con `slug`), nunca de datos. La migración 0014 es solo DDL
(tenants + políticas RLS + FK de lifecycle).

---

## 5. Tiers de suscripción

### 5.1 Tabla de suscripción

```sql
CREATE TABLE tenant_subscriptions (
    tenant_id       text PRIMARY KEY REFERENCES tenants(id),
    tier            text NOT NULL,             -- starter|pro|enterprise
    status          text NOT NULL,             -- trial|active|past_due|cancelled
    seats           int  NOT NULL DEFAULT 5,
    catalog_limit   int  NOT NULL,             -- SKUs máx (0 = ilimitado)
    automations_limit int NOT NULL,            -- tareas programadas activas
    rag_mb_limit    int  NOT NULL,
    integration_slots int NOT NULL,            -- prestashop/ghl/chatwoot/activepieces
    llm_daily_usd   numeric(10,2) NOT NULL,    -- presupuesto LLM diario
    retention_days  int  NOT NULL,             -- LIFECYCLE_DEFAULT_RETENTION_DAYS
    external_email  boolean NOT NULL DEFAULT false,  -- SMTP real habilitado
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
```

### 5.2 Matriz de tiers (propuesta, alineada con límites ya existentes)

| Límite | Starter | Pro | Enterprise |
|---|---|---|---|
| Precio orientativo | €149/mes | €499/mes | €1.900/mes + setup |
| Catálogo (SKUs) | 1.000 | 25.000 | Ilimitado (hoy: 41.652 reales) |
| Usuarios (seats) | 5 | 25 | Ilimitado |
| Presupuestos/pedidos/facturas | Sí (draft) | Sí + aprobaciones | Sí + automatización total |
| Automatizaciones activas | 2 | 10 | Ilimitado |
| RAG (MB) | 50 | 500 | 2.000 |
| Integraciones | 0 (catálogo local) | 1 (PrestaShop o GHL) | Todas (PrestaShop, GHL, Chatwoot, Activepieces) |
| Email real (SMTP) | No (spool manual) | Sí | Sí + dominios propios |
| LLM diario | 5 USD | 25 USD (default) | 100 USD |
| Retención / backup | 30 días / diario | 90 días / diario+semanal | 365 días / PITR |
| Soporte | Comunidad | Email | SLA 99,5 % + aislado físico (modelo C) |

### 5.3 Enforcement de límites (capa de servicio)

- **Columnas en `tenants`/`tenant_subscriptions` + guardas centralizadas**:
  una función `enforce_tenant_limits(tenant_id, resource, delta)` llamada en
  los puntos de escritura (import de catálogo, alta de usuario, activación de
  tarea, ingesta RAG, creación de integración).
- **Códigos**: `402 Payment Required` (límite del tier superado, con
  `X-Tier` y upgrade path) y `429` para rate limit por tenant (ya existe por
  instalación; se parametriza por tier: 120 req/min starter → 600 pro).
- **Sin tocar el modelo**: los límites NO van en el esquema de dominio; son
  una capa de política encima, auditable (`audit_log` event_type
  `subscription_limit_hit`).
- **Gracia**: los límites se comprueban en escritura, no en lectura; un
  catálogo que crece por sync de PrestaShop se pausa (estado `over_quota` en
  la tarea `prestashop_sync`) en lugar de borrar datos.

---

## 6. Plan de migración por fases

| Fase | Contenido | Entregable | Riesgo / rollback |
|---|---|---|---|
| **F0 — Catalogo + resolución** | Tabla `tenants`; middleware que rellena la ContextVar desde JWT `tenant_id`/subdominio; `get_current_installation_id()` lee la ContextVar. Sin RLS. | Multi-tenant funcional sobre BD compartida (misma app, mismo enforcement ORM) | Bajo. Rollback: volver a `settings.INSTALLATION_ID` |
| **F1 — Datos + índice** | Consolidar N instalaciones en un Postgres (pg_dump/restore por instalación); crear `tenants` por instalación; verificar índices compuestos. | Un solo Postgres, N tenants, cero pérdida | Medio (operacional). Restore por instalación con SS-05 |
| **F2 — RLS** | Migración 0014: políticas + `FORCE RLS` + `set_config` por transacción; suite de aislamiento ampliada (RLS: select/update/delete/insert cross-tenant → 0 filas) | La BD niega por sí misma | Bajo si F0/F1 verdes; desactivar RLS = DROP POLICY |
| **F3 — Tiers/billing** | `tenant_subscriptions`, guardas de límite, 402/429, panel de suscripción | Monetización operativa | Bajo (capa de política, no toca datos) |
| **F4 — Enterprise/aislamiento físico** | Oferta modelo C (BD por tenant) para clientes premium; export/erase por tenant | Tope del porfolio | Medio (provisionado), ya cubierto por lifecycle |

**Criterios de salida por fase:** los 24 modelos con política RLS verificada
por tests; cero `Session.get` que devuelva fila de otro tenant; backup de la
BD compartida con RPO/RTO medidos (reusar `backup-restore-integral.py`,
que ya es formato 4 cifrado sobre Postgres); E2E de provisión de tenant
nuevo (crear tenant → login → catálogo vacío → sync PrestaShop).

---

## 7. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| **Rendimiento**: RLS añade un `current_setting` por fila | Índices compuestos `(installation_id, ...)` ya presentes; verificar con EXPLAIN en el catálogo real (41.653 SKUs) antes de FORCE RLS; RLS se evalúa como predicado, no como join |
| **Fuga de tenant por pool de conexiones** | `set_config(..., true)` = `SET LOCAL` en el evento `begin`: el valor muere con la transacción |
| **Errores de app que devuelvan 500 en vez de datos** | Fail-closed es la intención: RLS niega; el ORM traduce a 404/403; tests de aislamiento cubren la matriz cruzada |
| **`Session.get` con identity map** | Ya resuelto con `identity_token`; los tests `test_identity_map_cannot_leak...` se amplían a RLS |
| **Embeddings (pgvector) compartidos** | `rag_chunk`/`rag_document` son owned y entran en RLS igual que el resto; dimensiones por tenant ya aisladas por `installation_id` |
| **Backup/restore multi-tenant** | `backup-restore-integral.py` restaura la BD completa (todos los tenants) con RPO/RTO ya medidos; el export/erase por tenant usa `installation_lifecycle` |
| **Auditoría y LLM budget** | `audit_log` y `daily_llm_budget` ya son owned: el presupuesto LLM diario por tenant sale gratis |
| **Migraciones futuras que rompan RLS** | La migración 0014 + un test que verifique que toda tabla owned tiene política (mismo patrón que el test de columna NOT NULL) |

---

## 8. Qué NO cambia (y por qué es la fuerza del plan)

- **Modelo de dominio**: la columna ya está en las 24 tablas; ninguna tabla
  cambia de forma en F0–F3.
- **Enforcement ORM**: `with_loader_criteria` + `before_flush` +
  `do_orm_execute` siguen siendo la primera línea; RLS es la segunda.
- **FKs compuestas y unicidad por tenant**: la integridad referencial
  cross-tenant ya está garantizada por la BD.
- **RBAC por rol dentro del tenant**: RLS aísla tenants; los 7 roles y la
  matriz `security.require_roles` (SS-04, 63 checks) siguen iguales.
- **Backup/restore, rate limit, ciclo de vida**: se parametrizan por tenant,
  no se reescriben.
- **Tests**: la suite de aislamiento (`test_p0_model_tenant_isolation.py`)
  se amplía, no se reemplaza — los 24 modelos y el identity map ya están
  cubiertos.

---

## 9. Recomendación de secuencia

1. **F0 + F2 en una misma entrega** (resolución de tenant + RLS + tests):
   son las dos piezas que convierten la app en SaaS con riesgo controlado.
2. **F1 operacional después**, con el stack candidato: consolidar
   `agent-candidate-0815` (41.653 SKUs, 1 tenant) en el Postgres compartido
   y validar paginación/RLS en vivo.
3. **F3 (tiers)** cuando haya 2+ clientes reales: sin métricas de uso
   reales, los límites son adivinanzas.

La decisión de negocio pendiente: **modelo A (compartido+RLS) como default**
y **modelo C (aislamiento físico) solo en enterprise** — el código ya soporta
ambos sin ramas.
