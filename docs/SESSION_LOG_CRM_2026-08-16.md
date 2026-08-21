# Informe de sesión — módulos CRM P1-c, P1-d y P2-e (2026-08-16)

> Documento de trabajo de la sesión del 2026-08-16. No es una fuente
> autoritativa de estado: la decisión de producción sigue en
> `docs/PRODUCTION_READINESS.md`, el trabajo en `TASKS.md`, los bloqueos en
> `BLOCKERS.md` y el historial en `CHANGELOG.md`. Este informe consolida lo
> implementado en la sesión para su revisión.
>
> **Para continuar el trabajo:** el brief autocontenido para el siguiente
> agente está en `docs/HANDOFF_CONTINUACION_CRM.md` (estado, convenciones,
> entorno, siguiente trabajo priorizado y definición de "hecho").

## Resumen ejecutivo

En la sesión se ejecutaron las mejoras accionables del análisis previo del
proyecto. Se cerraron **tres módulos del plan CRM B2B** (`PRODUCT_PLAN_CRM_B2B.md`,
tarea paraguas T-044) que estaban pendientes, se puso al día la gobernanza del
proyecto y se verificó todo con pruebas herméticas:

| Módulo | Plan | Fila | Estado |
|---|---|---|---|
| Campos personalizados por instalación | P1-c | T-048 | VERIFIED |
| Lead scoring básico en la cola | P1-d | T-049 | VERIFIED |
| Import/export CSV de leads | P2-e | T-050 | VERIFIED |

Además: sincronización de `BLOCKERS.md` con la evidencia real, corrección de un
bug latente en `--update-baseline` de los quality gates, y actualización del
baseline de deuda ruff.

**Resultado de las pruebas:** corpus backend **510 passed / 11 skipped**,
portal **53 tests vitest** con typecheck y build verdes, quality gates D-030
**PASS** (ruff-hard, ruff-clean-zone, ruff-ratchet y portal).

## Módulo P1-c — Campos personalizados por instalación (T-048)

Permite que cada instalación defina campos propios para leads u oportunidades,
con tipos, obligatoriedad y visibilidad por rol.

### Backend

- **Modelos** (`bridge-api/app/models/models.py`):
  - `CustomFieldDefinition`: clave estable única por instalación, etiqueta,
    entidad (`lead`/`opportunity`), tipo (`text`/`number`/`date`/`boolean`/
    `select`), opciones JSON, obligatoriedad, visibilidad
    (`all`/`operators`/`admins`), posición y `is_active`. La desactivación
    sustituye al borrado para conservar los valores existentes.
  - `CustomFieldValue`: un valor por campo y entidad, almacenado como JSON ya
    validado; FK diferible por instalación con `ON DELETE CASCADE`.
- **Migración** `bridge-api/alembic/versions/0018_custom_fields.py`: idempotente
  (re-upgrade safe) y downgrade no destructivo (política del proyecto). Crea las
  dos tablas con sus índices y la constraint única por campo/entidad.
- **Endpoints** (en `bridge-api/app/main.py`), todos auditados y con RBAC:
  - `GET /custom-fields`: lista definiciones activas filtradas por la
    visibilidad alcanzable por el rol del principal.
  - `POST /custom-fields`: solo admin; evento `custom_field.created`; clave
    duplicada → 409.
  - `PATCH /custom-fields/{id}`: solo admin; evento `custom_field.updated`.
  - `GET /custom-values`: definición+valor por entidad, filtrado por visibilidad.
  - `PUT /custom-values`: upsert idempotente con `Idempotency-Key`; valida el
    tipo/opciones contra la definición (`_coerce_custom_value`, fail-closed) →
    422; campo no visible para el rol → 403; evento `custom_field.value_updated`.

### Portal

- Pestaña «Campos personalizados» en la sección Clientes (solo admin),
  `portal/src/customFields.tsx`: tabla de definiciones con edición inline
  (etiqueta/visibilidad/obligatorio), activar/desactivar y formulario de alta
  con editor de opciones para campos `select`.
- La ficha del lead (drawer, `portal/src/timeline.tsx`) muestra y permite
  editar los valores de los campos visibles, con guardado idempotente.

## Módulo P1-d — Lead scoring básico (T-049)

Puntuación determinista y explicada de cada lead para priorizar la cola.

### Backend

- `_lead_score()` en `main.py`: puntúa 0–100 sumando señales con puntos y
  detalle. Sin LLM ni red — misma entrada produce misma salida.
  - **Origen**: chat (40), web/form (30), referral (25), import (20), local (10), otro (5).
  - **Antigüedad**: <1 día (20), <7 (15), <30 (10), <90 (5), más (0).
  - **Oportunidades abiertas**: +25 si hay alguna.
  - **Valor abierto**: +15 si el valor abierto > 0.
  - **Histórico ganado**: +10 si tiene alguna oportunidad ganada.
- `GET /leads/{lead_id}/score`: devuelve `score` + `signals` (RBAC operadores+).
- `GET /pipeline/board`: ahora expone `score` y `score_signals` por lead y
  ordena la cola de leads sin asignar por puntuación descendente (desempate por
  antigüedad, sort estable en dos pasos).

### Portal

- Columna «Puntuación» en la cola del kanban con badge
  (`score-high`/`score-medium`/`score-low`) y las señales en el tooltip
  (`portal/src/kanban.tsx`).

## Módulo P2-e — Import/export CSV de leads (T-050)

Vuelco y carga por lotes de leads, integrado con los campos personalizados.

### Backend

- `GET /leads/export.csv` (operadores+): exporta columnas fijas
  (`email`, `first_name`, `phone`, `company_name`, `source`, `status`,
  `assigned_to` como username, `created_at`) + una columna por campo
  personalizado de lead activo (su `key` como cabecera). Booleanos como
  `Sí`/`No`, NULL como celda vacía. Orden determinista por alta e id, cabecera
  `Content-Disposition` de descarga, límite 10.000 filas.
- `POST /leads/import` (operadores+, con `Idempotency-Key`):
  - Valida emails por fila sin abortar el lote (inválidos → `errors`).
  - Deduplica por email (`skipped_duplicates`), incluida la deduplicación
    intra-lote (flush por lead).
  - Crea con `source="import"` y `status="new"`.
  - `dry_run` informa sin crear nada ni exigir idempotencia.
  - Evento auditado `lead.import_completed` con conteos.

### Portal

- Botón «Exportar CSV» en la sección Leads (`portal/src/App.tsx`): descarga el
  blob como `leads.csv`; deshabilitado si no hay leads.

## Gobernanza y calidad

- **`BLOCKERS.md` sincronizado** con la evidencia de `STATUS.md`:
  - B-007 (DR/restore) → **RESOLVED** por el ensayo integral SS-05.
  - B-003 (PrestaShop), B-005 (Chatwoot), B-006 (IA externa), B-010 (runtime)
    → **MITIGADO** con el residual documentado en cada fila.
  - Abiertos de verdad: B-002 (procedencia git), B-004 (sandbox GHL),
    B-008 (revisión legal).
- **Bug corregido en `scripts/quality_gates.py`**: `--update-baseline` solo
  actualizaba el total `legacy_zone_ruff_full` y dejaba el desglose `by_rule`
  desincronizado (rompía `test_baseline_file_documents_visible_debt`). Ahora
  recalcula el desglose con la misma selección de la zona legacy (formato
  `concise` de ruff). Baseline ruff fijado en **133**.
- **Documentación autoritativa actualizada**: filas T-048/T-049/T-050 en
  `TASKS.md` (y nota de progreso en la paraguas T-044), entradas en
  `STATUS.md` y tres bloques en `CHANGELOG.md`.

## Archivos creados o modificados

### Creados

| Archivo | Líneas | Contenido |
|---|---:|---|
| `bridge-api/alembic/versions/0018_custom_fields.py` | 133 | Migración idempotente de campos personalizados |
| `tests/regression/test_p1_custom_fields_scoring.py` | 616 | 17 evals herméticos (P1-c, P1-d, P2-e) |
| `portal/src/customFields.tsx` | 433 | Pestaña de gestión de campos personalizados |
| `portal/src/customFields.test.tsx` | 140 | 4 evals vitest del componente |

### Modificados (cambios de esta sesión)

- `bridge-api/app/models/models.py`: modelos `CustomFieldDefinition`/`CustomFieldValue`.
- `bridge-api/app/main.py`: constantes y schemas de campos personalizados y de
  importación, `_lead_score`, `_visibility_allowed`, `_coerce_custom_value`, y
  los endpoints `GET/POST /custom-fields`, `PATCH /custom-fields/{id}`,
  `GET/PUT /custom-values`, `GET /leads/{id}/score`, `GET /leads/export.csv`,
  `POST /leads/import`; board ordenado por score.
- `portal/src/kanban.tsx` y `kanban.test.tsx`: badge de puntuación en la cola.
- `portal/src/timeline.tsx`: edición de campos personalizados en la ficha del lead.
- `portal/src/App.tsx` y `App.test.tsx`: pestaña «Campos personalizados» y botón «Exportar CSV».
- `portal/src/styles.css`: estilos de score y campos personalizados (claro/oscuro).
- `scripts/quality_gates.py` y `scripts/quality_baseline.json`: fix del desglose + baseline 133.
- `TASKS.md`, `STATUS.md`, `CHANGELOG.md`, `BLOCKERS.md`.

## Evidencia de pruebas

| Prueba | Resultado |
|---|---|
| `pytest tests bridge-api/tests` | **510 passed / 11 skipped** |
| `tests/regression/test_p1_custom_fields_scoring.py` | 17 evals verdes |
| Portal `npm run typecheck` | verde |
| Portal `npm run build` | verde |
| Portal `npm run test` | **53 tests vitest verdes** |
| `scripts/quality_gates.py --with-portal` | D-030 **OK** (hard 0, clean-zone 0, ratchet 133 ≤ 133, portal PASS) |
| Paridad migraciones↔modelos | `test_clean_install_upgrades_to_explicit_model_schema` verde (head 0018) |

Notas de hermeticidad (D-032): los tests corren contra la instalación de prueba
por defecto con SQLite efímero; usuarios y filas se crean/limpian con ids únicos;
no se toca la red ni el `.env` del operador. Los 11 skipped son opt-in
(PostgreSQL real, PrestaShop real, Python 3.12, `/dev/tcp` en Windows, etc.).

## Lo que NO se hizo (y por qué)

- **Cerrar los stop-ships SS-01/SS-02/SS-03/SS-06/SS-07** (checkout inmutable,
  imágenes certificadas, TLS/DNS reales, soak, delivery de alertas): requieren
  infraestructura real, certificados/DNS, decisiones del propietario y un
  entorno de carga — no son tareas de código aisladas.
- **Poner `production-gates.yml` a correr en un remote de CI**: necesita un
  runner/remote configurado.
- **Revisión legal B-008** (titularidad/licencias): es una decisión de negocio,
  no técnica.
- **Resto del P2/P3 del CRM** (email integrado, campañas, calendario, API
  pública + webhooks salientes, SSO/MFA, tickets/SLA, multi-tenant RLS,
  billing): pendientes de siguientes rondas. El candidato natural siguiente es
  **webhooks salientes (P2-f)**, que reutiliza `send_webhook` (HMAC + allowlist
  anti-SSRF) y el outbox durable ya existentes.
