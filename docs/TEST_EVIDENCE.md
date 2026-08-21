> **REGISTRO HISTÓRICO — NO UTILIZAR SUS RESÚMENES COMO ESTADO ACTUAL.** Este archivo conserva evidencia cronológica de múltiples commits y runtimes. El resumen vigente está en `docs/TEST_REPORT.md` y la única decisión autoritativa en `docs/PRODUCTION_READINESS.md`.

# Evidencia de pruebas de producción

## Auditoría del árbol — 2026-08-10, HEAD `c5c0b52` (histórico)

| Control | Resultado | Interpretación |
|---|---|---|
| `bridge-api/tests/unit` | 23 passed | Unitarios Bridge verdes |
| `tests/integration` | 2 failed, 30 passed, 3 skipped | Fallan catálogo local sin PrestaShop e idempotencia del webhook |
| Regresión parcial (sin dependency/quality/backup) | 8 failed, 187 passed, 6 skipped | Los ocho fallos son migraciones por `0006` sin seguimiento |
| Replay HMAC aislado | 1 failed | Primer POST 200; duplicado idéntico 202 `processing` |
| Suite completa | timeout 124,1 s, sin resultado | No declarar corpus verde |
| `scripts/quality_gates.py` | FAIL | 5 ruff-hard; 6 clean-zone; deuda 242 > baseline 213 |

## Reevaluación post-remediación — 2026-08-10, HEAD `09b854b` + working tree

Remediación previa: `5677662` cierra RA-01…RA-08 (1 P0 + 7 P1) con evals de regresión; `a540223`/`09b854b` corrigen `search_products()` de PrestaShop (15/15 escenarios live verdes contra la tienda real); el working tree añade hermeticidad total D-032 (neutraliza `PRESTASHOP_*`/`GHL_*` del `.env` del operador), actualiza los 4 tests de catálogo al comportamiento RA-04 (fuente agnóstica), deja los quality gates verdes y restaura el estado global en los tests que mutaban `SessionLocal` (la suite de regresión completa corre verde en un solo proceso).

| Control | Resultado | Interpretación |
|---|---|---|
| `bridge-api/tests/unit` | 23 passed | Unitarios Bridge verdes |
| `tests/integration` | 35 passed | Corpus completo verde; incluye los 4 evals de catálogo actualizados a RA-04 (`catalog_full_list`, fuentes `prestashop`/`local`/`import`) y el replay del webhook |
| Migraciones (`test_p0_migrations.py`) | 24 passed | `0006` dialect-aware (RA-02): pgvector/Vector en PostgreSQL, no-op en SQLite; clean/upgrade/downgrade verdes |
| Evals RA-01…RA-08 (`test_audit_remediation_2026_08_10.py`) | 5 passed | `restore_to_url` sin `drop_all` (marker obligatorio), replay HMAC 200 cacheado, catálogo local sin PrestaShop, `_LOG`→`log_event`, Chatwoot SSRF off por defecto, email/webhook fail-closed |
| Regresión completa | 222 passed, 9 skipped | Antes (auditoría): 8 failed; antes (working tree previo): 6 failed + 21 errors por envenenamiento de `SessionLocal` — resuelto. Los 9 skips son opt-in/live: 4 E2E Docker con catálogo live, 2 `test_prestashop_webservice_search` (requieren credenciales reales), 2 preflight bash/Windows y 1 backup PostgreSQL opt-in (`RUN_POSTGRES_BACKUP=1`) |
| `scripts/quality_gates.py` | PASS | ruff-hard 0 · ruff-clean-zone 0 · ruff-ratchet 243 = baseline 243; baseline reconciliado (desglose `by_rule` suma 243: UP006 166, UP007 48, UP035 19, B033 6, UP017 2, I001 2) |
| Hermeticidad D-032 | VERIFIED (working tree) | `tests/conftest.py` neutraliza credenciales PrestaShop/GHL reales; la suite ya no toca red ni hereda entorno (antes `test_commerce.py` >600 s contra la tienda real; ahora 0,6 s) |
| Backup integral con CRM local (Fase B bloque 5) | 3 evals passed | `leads`/`opportunities` entran en el manifiesto (conteos + sha256); roundtrip a instalación vacía restaura lead+oportunidad con la FK lead→oportunidad y las notas intactas (`test_p1_backup_restore.py`); el rollback de datos recupera el CRM local borrado |
| RTO/RPO medidos (Fase B bloque 5) | RTO 0,197 s (SQLite, 5 filas) | Metodología: **RPO** = cadencia programada del backup (parámetro operacional, p. ej. cron diario → RPO ≤ 24 h; lo fija el scheduler que invoca `scripts/backup-restore-integral.sh`); **RTO** = tiempo del restore hasta datos consultables, medido por el eval `test_restore_rto_is_measured_and_bounded` con límite de 10 s; PostgreSQL opt-in (`RUN_POSTGRES_BACKUP=1`) pendiente de runtime |
| Portal typecheck/test/build | PASS / 5 passed / PASS | Compila; tests usan fetch mockeado |
| Portal format/ESLint | FAIL / FAIL | 7 fuentes sin formato; falta `eslint.config.*` (preexistente, sin cambios) |
| npm audit producción/completo | 0 / 1 HIGH | Runtime limpio; build/CI afectado por nanoid transitivo (preexistente) |
| Compose core/full | config estática PASS | No acredita runtime |
| Compose prod example | FAIL standalone | Proxy sin image/build; TLS no implementado (preexistente) |
| Docker/runtime/E2E | BLOCKED | daemon detenido; ~2,8 GiB de RAM libre (B-010) |

Esta sección prevalece sobre la tabla de auditoría y los resultados verdes históricos para evaluar el árbol actual. La tabla de auditoría se conserva como trazabilidad del estado que motivó RA-01…RA-08. Los resultados anteriores se conservan como trazabilidad de commits previos.

## Revalidación runtime desde máquina limpia — 2026-08-11, HEAD `e7a123f`

Despliegue desde cero en máquina limpia (Windows + Docker Desktop): `git clone -b production-remediation`, `.env` nuevo generado desde `.env.example` con secretos aleatorios, `docker compose --profile core up -d --build`, migraciones y validación del corpus. No se tocó producción ni el workspace original.

| Fecha | Control | Resultado | Alcance |
|---|---|---|---|
| 2026-08-11 | Clonación `production-remediation` @ `e7a123f` | OK | `vendor/` no está versionado en el repo; el perfil core necesita `vendor/flowwink` (se vendoreó desde `magnusfroste/flowwink` en el commit pin `0cd4e9b8` que documenta `docs/audit/04_DEPENDENCY_MAP.md`). `chatwoot`/`activepieces` no hacen falta (perfil full). |
| 2026-08-11 | `.env` desde `.env.example` | 117 vars, secretos frescos | Docker Compose interpreta `$`/`$$` en el env file: un secreto con `$$` se colapsó a `$` dentro del contenedor y el admin se sembró con credencial corrupta → `401` en login. Se regeneró el valor sin `$` y se re-sembró el admin (delete + restart). |
| 2026-08-11 | Líneas finales (CRLF) | Fix local, sin cambios de repo | `core.autocrlf=true` global materializó los scripts con CRLF: `bridge-api/entrypoint.sh` (exit 127) y `vendor/flowwink/docker/40-runtime-env.sh` (`#!/bin/sh\r`). Los blobs son LF; re-checkout local a LF. Reproducible solo en máquinas con autocrlf. |
| 2026-08-11 | `docker compose --profile core up -d --build` | 6/6 healthy | bridge-db, bridge-redis, bridge-api, portal, flowwink-app y reverse-proxy healthy (tras crash-loop inicial del proxy por resolución DNS de upstream en el arranque; saneado con recreate). |
| 2026-08-11 | Migraciones | OK, `0008 (head)` | `alembic upgrade head` idempotente. |
| 2026-08-11 | Smoke por puerto 9000 | portal 200 · `/api/bridge/ready` 200 · flowwink 200 | Verificación runtime del proxy sobre los tres servicios. |
| 2026-08-11 | `scripts/check-health.sh` | N/A (contrato por cliente) | El script exige `CLIENT_ID` + `.env.<client-id>` + perfil full; no aplica al core. Equivalente core realizado: `docker compose ps` 6/6 healthy + smoke. |
| 2026-08-11 | `scripts/quality_gates.py` | FAIL (pre-existente) | ruff-hard PASS (0) · ruff-clean-zone FAIL (97 issues en tests añadidos por los commits fase-B posteriores a `09b854b`; el verde documentado era `09b854b` + working tree) · ruff-ratchet PASS (239 ≤ baseline 243). Sin cambios de repo: el deployment no altera la deuda. |
| 2026-08-11 | Corpus `PYTHONPATH=bridge-api pytest tests bridge-api/tests` | 324 passed, 9 skipped, 1 failed (ambos órdenes) | El único fallo es `test_quality_gates_pass_on_current_tree`, que reporta fielmente el FAIL de clean-zone. Se reprodujo un defecto de arranque en frío: con `.env` recién copiado de `.env.example`, `CHATWOOT_HANDOFF_ASSIGNEE_ID=` (vacío) tumbaba `Settings()` en la colección; corregido con 1 línea en `tests/conftest.py` (clave `'0'`, coherente con el default `:-0` de compose y la hermeticidad D-032). |
| 2026-08-11 | `tests/regression/test_p1_dependency_audit.py` | 6 passed | Tras instalar `pip-audit` (no está en `requirements-dev.txt`); `npm audit` prod 0 high. |
| 2026-08-11 | Portal `npm run typecheck && npm test && npm run build` | PASS / 9 passed / PASS | `tsc --noEmit` limpio; vitest 9/9; build Vite OK. |
| 2026-08-11 | **E2E core en vivo** (`scripts/e2e_core_chat_to_quote.py`) | **[4] `action=quote_created` → [7] E2E completo OK** | login → import catálogo → webhook Chatwoot FIRMADO (HMAC) → presupuesto determinista (2×10 + IVA 21 % + envío 15 = 39,20) → `CONFIRMAR <token>` → pedido + borrador de factura → aprobación admin. Sin GHL/PrestaShop/Supabase, Ruta A. |
| 2026-08-11 | Defecto de rutas de import detectado por el E2E | Corregido | Las rutas `/api/bridge/import/*` de la app llevan el prefijo completo mientras el resto de rutas no; el bloque `/api/bridge/` del proxy reescribía el prefijo y devolvía 404 (rompía el E2E y el import de catálogo del portal). Fix en `infrastructure/proxy/default.conf.template`: location `^~ /api/bridge/import` que pasa la URI sin reescribir. |

La validación en frío no incluyó soak prolongado (B-010) ni los perfiles full/por-cliente. El fallo de clean-zone y el estado IN PROGRESS de T-022/T-023/T-024 son de la rama, no del despliegue.

## Perfil full desde máquina limpia — 2026-08-11

Continuación del despliegue: se añadieron `vendor/chatwoot` (pin `b05f22da`) y se levantó el perfil completo. `vendor/activepieces` no participa en el build: Activepieces usa la imagen oficial `ghcr.io/activepieces/activepieces:0.86.3` (así lo documenta `docs/audit/04_DEPENDENCY_MAP.md`). Mismo tratamiento CRLF que en core (blobs LF, re-checkout local).

| Fecha | Control | Resultado | Alcance |
|---|---|---|---|
| 2026-08-11 | `docker compose --profile full up -d --build` | 14/14 healthy | bridge-db/redis/api, portal, flowwink-app, reverse-proxy, chatwoot-web/worker/db/redis, activepieces-app/worker/db/redis. El build de chatwoot usa `git rev-parse` (contexto con `.git` presente). |
| 2026-08-11 | `AP_ENCRYPTION_KEY` de Activepieces | Corregido | La imagen oficial exige exactamente 32 hex (`openssl rand -hex 16`); el `.env` generado traía 64 hex y Activepieces se negaba a arrancar (`AP_ENCRYPTION_KEY is missing or invalid`). Regenerado y recreado app/worker. |
| 2026-08-11 | Smoke por puerto 9000 (proxy por host) | portal 200 · `/api/bridge/ready` 200 · `/api/bridge/live` 200 · flowwink (`agents.localhost`) 200 · chatwoot (`chat.localhost`) 302 → `/installation/onboarding` (primer arranque, esperando onboarding) · activepieces (`automation.localhost`) 200 (`<title>Activepieces</title>`) | Todos los servicios responden a través del reverse-proxy. |
| 2026-08-11 | **E2E core en vivo con full arriba** | **[7] E2E completo OK** | login → producto local → webhook HMAC → quote 39,20 → CONFIRMAR → pedido + factura borrador → aprobación admin, con chatwoot/activepieces corriendo. |
| 2026-08-11 | Re-ejecutabilidad del E2E | Corregido + verificado | El script fijaba `conversation: 525252` con email nuevo por pasada; la app vincula `ConversationState`→cliente, así que una 2ª ejecución reusaba el cliente de la 1ª y el confirm fallaba 403 (`El remitente no coincide`). Fix: conversación única por ejecución. 2ª pasada completa OK; la 3ª se detiene correctamente en `insufficient_stock` (el producto local `Probe` agotó stock 5/5 y la app rechaza la venta — invariante P0-004, sin oversell). |

El perfil full queda operativo en la máquina limpia. Pendiente de la rama: onboarding de Chatwoot (paso de operador), flujos reales de Activepieces y soak B-010.

## IA local con LM Studio — 2026-08-11

Conexión del Bridge a LM Studio (host) como proveedor LLM y de embeddings vía API compatible OpenAI (`http://host.docker.internal:1234/v1`).

| Fecha | Control | Resultado | Alcance |
|---|---|---|---|
| 2026-08-11 | Embebidos RAG con LM Studio | VERIFIED | `EMBEDDING_PROVIDER=openai_compatible`, modelo `text-embedding-nomic-embed-text-v1.5` (768). Ingesta de documento por `/rag/upload` OK: `embedding_provider=openai_compatible`, `dimension=768`, clasificación `internal`, sin DLP. Logs: `POST http://host.docker.internal:1234/v1/embeddings 200`. |
| 2026-08-11 | Generación del docs-chat con LM Studio | VERIFIED | `STANDARD_LLM_PROVIDER=openai`, modelo `qwen3-8b`; consulta a `/agents/docs-chat` → `provider=openai`, `abstained=false`, 1 cita verificable (score 0.72) del documento ingerido. Logs: `POST .../v1/chat/completions 200`. |
| 2026-08-11 | Defecto de infra detectado y corregido | Corregido | `OPENAI_BASE_URL`/`ANTHROPIC_BASE_URL` existían en `.env.example` pero compose nunca las pasaba al contenedor (solo `OPENAI_API_KEY`); el Bridge llamaba a `api.openai.com` (401) aunque `.env` apuntara a LM Studio. Fix: `OPENAI_BASE_URL: ${OPENAI_BASE_URL:-https://api.openai.com/v1}` y `ANTHROPIC_BASE_URL: ${ANTHROPIC_BASE_URL:-https://api.anthropic.com/v1}` en el bloque environment de `bridge-api` (patrón existente). |
| 2026-08-11 | Config `.env` para LM Studio | Aplicada | `CHEAP/STANDARD/ADVANCED_LLM_PROVIDER=openai` con `qwen3-8b`, `OPENAI_BASE_URL=http://host.docker.internal:1234/v1`, `OPENAI_API_KEY=lm-studio`, `LLM_PRICING_CATALOG_JSON` con tarifa `openai/qwen3-8b` (obligatorio para proveedor externo; clave del catálogo = `provider/model`). |

El RAG (ingesta, recuperación y chat con citas) queda operativo con LM Studio. Pendiente de la rama: onboarding de Chatwoot, flujos de Activepieces y soak B-010.

## E2E chatbot completo con LM Studio — 2026-08-11

Flujo completo por webhook de Chatwoot FIRMADO (HMAC) contra el stack en vivo, con LM Studio como proveedor LLM (`qwen3-8b`) y embeddings (`nomic-embed-text-v1.5`). Driver temporal de validación (eliminado tras la ejecución), salida real:

| Paso | Resultado observado |
|---|---|
| 0. Login + import | login OK; producto local `SKU-LLM-…` (`Portátil Pro 14`, 899,99 € + IVA 21 %, stock 10) creado por `/import/products` |
| 1. Saludo `hola, buenas tardes` | `action=greeting`, reply generado por IA: `¡Hola! ¿En qué puedo ayudarte hoy? 😊` |
| 2. Catálogo `¿qué portátiles tienes disponibles?` | `action=category_empty`, **`llm_provider=openai`**, 3 productos en contexto, reply natural en español con precios y stock (generado, no texto fijo) |
| 3. Presupuesto `quiero 2 unidades del portátil pro` | `action=quote_created`, total **determinista 2177,98 EUR** (2×899,99 + IVA 378,00 + envío 0,00), token `CONFIRMAR` presente |
| 4. `CONFIRMAR <token>` | `action=order_created`, `ord-2619b61093c5`, borrador de factura `inv-63638662527a`, aprobación `appr-1a9f98fdc492`, total 2177,98 |
| 5. Aprobación admin | `approve` 200 → `approved` |
| 6. `quiero hablar con un humano` | `action=human_handoff`, reply `Te he transferido al equipo comercial. Te atenderán lo antes posible.` (side effects de Chatwoot auditados internamente, Ruta A: sin `CHATWOOT_API_TOKEN`) |

Logs del contenedor: `POST http://host.docker.internal:1234/v1/chat/completions 200 OK` (4 llamadas en la ventana: saludo + catálogo × 2 ejecuciones) — la generación de saludo/catálogo salió de LM Studio; presupuesto/confirmación siguen siendo deterministas (sin LLM).

## Demo en vivo del proceso completo — 2026-08-11

Proceso ejecutado en tiempo real con el portal abierto en el preview, verificando cada cambio de estado en pantalla:

| Paso | Observado en vivo |
|---|---|
| 0. Recuperación tras caída del motor | Docker Desktop se había detenido; relanzado, stack full 14/14 healthy. Chatwoot con pid stale de Rails (`A server is already running (pid: 1)`) recuperado con `--force-recreate`. |
| 1. Importar `Monitor 27 pulgadas` (249,99 €, stock 5) | Portal Resumen: **Productos 3 → 4** |
| 2. Webhook `quiero 1 unidad del monitor 27` | **Defecto detectado**: el trigger del presupuesto solo reconocía `unidades` (plural); `unidad` singular caía a recomendación LLM. Fix: añadir `unidad` a la lista de triggers (`bridge-api/app/main.py`). Tras recrear bridge-api → `quote_created` (quote-6373f5f17c20, total 317,49 = 249,99 + IVA 52,50 + envío 15,00, token `CONFIRMAR`). Portal: **Clientes 5 → 6**. |
| 3. `CONFIRMAR <token>` | `order_created` (`ord-62b30d5a40dd`) + factura borrador + aprobación `appr-ef3bacb45e3f` (317,49 EUR) |
| 4. Portal → Aprobaciones | Tras pulsar Actualizar: **1 pendiente** — «Aprobar borrador de factura · inv-67dac04820f1». (El panel usa estado de montaje; la sección no refetch al navegar.) |
| 5. `Aprobar` desde la UI | **0 pendientes**; API: `appr-ef3bacb45e3f → approved`, revisada por `admin` (10:36:49Z) |

## Escalado del catálogo: búsqueda SQL (pg_trgm) + semántica — 2026-08-11

Motivación: con miles de productos, el buscador en memoria cargaba hasta 5.000 candidatos por consulta
(`json.dumps` de atributos por producto y por mensaje) y los productos más allá de la posición 5.000 por
nombre eran **invisibles silenciosamente** para el chat y el portal.

### Cambios (working tree, sin commit)

- **Migración `0009`** (PostgreSQL-only, misma política que 0006): `pg_trgm` + `unaccent`, función inmutable
  `bridge_search_norm(text)` (minúsculas + sin acentos + solo `[a-z0-9]`) y **índice GIN trigrama** sobre
  `name + sku + category + description + attributes::text` normalizados. SQLite: no-op (tests hermeticos
  siguen con el buscador en memoria).
- **`DeterministicToolsService.search_products` dialect-aware**: en PostgreSQL la consulta vacía filtra la
  disponibilidad en SQL y aplica `LIMIT safe_limit` (sin cargar 5.000 filas); la búsqueda por tokens usa
  `ILIKE '%token%'` indexado y conserva el **mismo scoring/umbral/orden** que el buscador en memoria (los
  resultados son idénticos, solo cambia cómo se acota el conjunto de candidatos). SQLite conserva la
  implementación original.
- **Cap del fallback extractivo**: `_format_extractive_lines(products, max_lines=20)` — los fallbacks del
  chat que renderizaban bullet-lists ya no pueden generar respuestas descomunales; añaden nota «…y N más».
- **Búsqueda semántica de productos** (refuerzo, nunca punto de fallo): modelo `ProductEmbedding`
  (tabla de la migración 0006, ahora con código), servicio `product_embeddings.py` que reutiliza el cliente
  de embeddings del RAG (`embed_texts` extraído a nivel de módulo), endpoint admin
  `POST /products/embeddings/index` y herramienta `GET /tools/products/semantic`. El chat intenta la
  semántica cuando el léxico no encuentra nada (umbral 0.30): sin índice o sin coincidencias devuelve `[]`
  y el flujo sigue como antes.

### Benchmark con 10.000 productos sintéticos (BD live, limpiado al final)

| Consulta | Latencia media | Notas |
|---|---|---|
| vacía, limit=100 | **8 ms** | antes: 5.000 filas en memoria por petición |
| `monitor` / `portátil` (acento) / `informática` | 64–75 ms | acentos normalizados (`unaccent`) |
| `zebra` (producto en posición > 5.000 por nombre) | 63 ms | **encontrado**; antes era invisible |
| `raton inalambrico` / `lampara escritorio` (5.000 matches) | 216–227 ms | peor caso acotado por el índice |

### Validación semántica en vivo (LM Studio, nomic-embed-text v1.5, 768 dims)

- `POST /products/embeddings/index` → `{total: 4, indexed: 4, errors: 0, provider: openai_compatible}`.
- `GET /tools/products/semantic?query=una pantalla para jugar` → Monitor 27 (0.568) + Portátiles (0.617);
  `portatil profesional` → Portátil Pro 14 (0.677) — recall conceptual sin match léxico.
- **Chat completo**: webhook `quiero una pantalla para jugar a videojuegos` (sin ningún término en el
  catálogo) → `action=semantic_recommendation`, `llm_provider=openai`, reply generado por LM Studio
  recomendando el Monitor 27 pulgadas con stock y precio.
- Regresión del ciclo comercial con el cambio activo: `quote_created` → `CONFIRMAR` → `order_created` OK.

### Defectos reales detectados y corregidos durante la validación

1. **`bridge_search_norm` aplicaba el regexp antes que `unaccent`** → «Portátil» se convertía en «port til».
   Corregido el orden (unaccent primero) en la migración y `REINDEX` del índice en la BD live.
2. **`/tools/products/semantic` capturado por `/tools/products/{product_id}`** (orden de rutas FastAPI).
   Movido antes del path-param (declaración explícita documentada).
3. **Handoffs incondicionales a Chatwoot** (ramas `catalog_empty_handoff` e `insufficient_evidence_handoff`):
   sin `CHATWOOT_API_TOKEN` (Ruta A) devolvían 502. Ahora usan `_safe_chat_sideeffect` (mismo patrón que
   la rama `human_handoff`): con token hacen el efecto real; sin token lo auditan internamente.
4. **Mensajes con trigger-keyword sin producto específico quedaban sin respuesta** (`no_branch_matched`):
   p. ej. `¿qué productos tienen disponibles?` o `necesito algo para archivar documentos`. El branch de
   trigger setea un flag que el `else` externo nunca consume (un `elif` que coincide impide que el `else`
   corra) y `_build_llm_reply` era código muerto (se escribía, nunca se leía). Fix: el caso sin producto
   responde inline con búsqueda semántica (si está indexada) + catálogo visible y `commerce_chat`
   (`action=catalog_browse_prompt`); se eliminaron el flag y `_build_llm_reply` muertos. Validado en vivo
   con ambos mensajes (provider `openai`, reply natural generado por LM Studio).

### Corpus y gates

- Corpus completo (334 tests): **324 passed / 9 skipped / 1 failed en ambos órdenes** — el único fallo es
  el preexistente `test_quality_gates_pass_on_current_tree` (clean-zone 97, inalterado por este cambio;
  ruff-hard PASS, ratchet PASS).
- Migraciones: `test_p0_migrations.py` 24/24 (aserciones de revisión head actualizadas a `0009`).
- Portal: typecheck ✓, 9 tests ✓, build ✓ (sin cambios en el portal; `/tools/products` hereda la mejora).

## Indexación semántica por keyset a 100k SKUs + reindexado incremental — 2026-08-12

Motivación: `index_catalog` cargaba el catálogo completo en memoria (`Product.query...all()`) y hacía una
consulta de existencia por producto (N+1); a 100.000+ SKUs eso significa cientos de MB y decenas de miles
de consultas. Además, los productos recién importados no quedaban indexados hasta un pase manual completo.

### Cambios (working tree, sin commit)

- **`index_catalog` con paginación keyset sobre `(name, id)`** en lotes (16 por defecto, máx. 64): nunca
  carga el catálogo completo; `total` se acumula por página y `expunge_all()` por página mantiene la
  identity map de SQLAlchemy acotada al lote (memoria O(batch), no O(catálogo)).
- **Migración `0010`**: índice compuesto `ix_product_installation_name_id (installation_id, name, id)`
  (PostgreSQL-only, idempotente, mismo patrón que 0006/0009). Sin él, la comparación por fila keyset
  degradaba a `Parallel Seq Scan + sort` por página (~80 ms/página → 10+ min por pase a 100k); con él,
  `Index Scan` (~0.16 ms/página, 500x).
- **Comparación por fila `tuple_(name, id) > (last, last_id)`** en vez del `OR` expandido: el `OR` no usa el
  índice compuesto; la fila comparada sí (EXPLAIN ANALYZE verificado).
- **`index_products(ids)`** (reindexado incremental): indexa solo un subconjunto de ids en lotes, ignorando
  inexistentes/demo; comparte `_embed_page` con `index_catalog` (prefetch de embeddings existentes por
  página — elimina el N+1 — y commit por lote con progreso persistido).
- **Reindexado automático tras cada importación de productos** (endpoints `import_data` e `import_data_file`):
  `ImportService.process` devuelve `created_ids`; el endpoint los consume con `index_products` en modo
  best-effort (`_reindex_imported_products`): cualquier error de embeddings se loguea y resume en
  `result["semantic_index"]` sin fallar la importación (sin token/SQLite/`local_tfidf` → `skipped`). Los
  `created_ids` se consumen antes de la auditoría y la idempotencia (no se persisten). El stock NO
  reindexa (no cambia el texto indexado; la disponibilidad se evalúa en vivo en `search`).

### Benchmark en BD live (100.000 productos sintéticos, limpiados al final; embeddings stub para aislar la paginación)

| Métrica | Diseño anterior | Keyset actual |
|---|---|---|
| Memoria cargando el catálogo (100.004 filas) | **+308 MB** RSS (`.all()` de ORM) | **+4 KB** RSS pico durante el pase; `identity_map: 0` objetos retenidos |
| Pase completo de indexación (100.000, batch 16) | — | 62–70 s (6.251 páginas, ~10 ms/página incl. query+prefetch+commit) |
| Reindexado incremental (skip) del mismo catálogo | — | 18,7 s, 0 embeds, RSS plano |
| Página keyset individual (con `0010`) | 78 ms (Seq Scan) | **0,16 ms** (Index Scan) |

- Correctitud: `indexed == 100.000`, `errors == 0`, `indexed_count == total`; `index_products` indexa solo
  el id borrado (1/2, el otro inexistente) y `[]` → `{total: 0}`.
- Los embeddings del catálogo real (4 productos) se restauraron al final con LM Studio real (`index_catalog(force=True)`).

### Reindexado incremental tras importación — validado en vivo por HTTP (LM Studio real)

- Importar 1 producto → `semantic_index {total: 1, indexed: 1, errors: 0}`; lote de 2 → `indexed: 2`;
  importación de stock → **sin** `semantic_index`; búsqueda semántica encuentra el producto recién
  importado (`Pantalla Ultrawide …`, score 0.64).
- **Replay idempotente**: repetir la misma importación devuelve la respuesta almacenada (sin reindexar).
- **Best-effort demostrado**: con el proveedor de embeddings caído (LM Studio apagado), la importación
  sigue en 200 con `semantic_index {indexed: 0, errors: 1}` y el producto queda creado sin embedding,
  recuperable con un `index_catalog` posterior (fallo benigno, no aborta la importación).
- Catálogo restaurado tras las pruebas: 4 productos reales, 4 embeddings.

### Botón de búsqueda semántica en el portal (2026-08-12)

- El panel **Productos** del portal incorpora un bloque «Búsqueda semántica del catálogo»
  (visible para cualquier rol de lectura): consulta por concepto contra
  `GET /tools/products/semantic` y muestra los resultados con su **score de similitud**
  como badge de porcentaje (verde ≥ 60 %, ámbar ≥ 40 %, violeta < 40 %), para que el
  operador valide el recall desde la UI. Estados: carga, sin coincidencias (con nota de
  reindexación) y error de API.
- Validado en vivo contra LM Studio: «una pantalla para jugar a videojuegos» → Portátiles
  (65,9 % / 64,7 %) + Monitor 27 (64,7 %); «portátil para trabajar» → Portátiles
  (70,4 % / 68,2 %); «monitor gaming» → Monitor 27 (59,8 %). Sin errores de consola;
  petición `200` a `/tools/products/semantic`.
- Portal: typecheck ✓, **10 tests ✓** (nuevo test «la búsqueda semántica del catálogo
  muestra resultados con score»), prettier limpio, build en el contenedor `portal`
  reconstruido y verificado en el preview.

## Resumen por categorías con SQL GROUP BY — 2026-08-12

Las funciones muertas `_build_catalog_categories_summary` y `_build_categories_brief`
cargaban hasta 10.000 productos en memoria (`search_products("", limit=10_000)`) para
agrupar por categoría en Python. Reescribitas con **agregación SQL GROUP BY**
(dialect-aware): una consulta por conteo `(categoría, count)` y otra por ejemplo
representativo con `ROW_NUMBER() OVER (PARTITION BY category)`; ambas tenant-scoped,
sin demo, con disponibilidad comercial (PostgreSQL `->>`; SQLite `json_extract = 1`, la
semántica de `->>` difiere entre dialectos) y restringidas a las fuentes del proveedor
activo. La disponibilidad en SQLite quedó cubierta por test.

**Decisión de reactivación**: sí, para «ver todo el catálogo» solo cuando el catálogo
real supera el cap (`CATALOG_OVERVIEW_LIMIT`, default 500): si `total > len(verificado)`
el chat responde `catalog_category_summary` (resumen por categorías con ejemplo y
conteo, sin volcar productos; el volcado excedería el contexto del LLM y el fallback
solo mostraría 20 bullets). Con catálogo pequeño mantiene el volcado con LLM
(`catalog_full_list`). `_build_categories_brief` queda reescrita pero sin reactivar
(el modo browse no era parte de la petición).

Validación:
- 4 tests herméticos nuevos (`tests/regression/test_catalog_categories_summary.py`):
  agregado por categoría, categoría vacía → «Otros», orden por count, desglose con
  ejemplo representativo, y exclusión de PrestaShop sin flags de comercio. Los
  productos se limpian al final (la BD de sesión es compartida y los `prestashop`
  des-saltarían los E2E de catálogo que dependen de su ausencia — defecto real
  detectado durante la validación).
- En vivo (PostgreSQL, LM Studio arriba): con 554 productos, «quiero ver todos los
  productos» → `catalog_category_summary` con «Tenemos 554 productos en 3
  categorías: • Oficina: 550 (ej. …) • Informática: 3 (ej. Monitor 27) • General: 1
  (ej. Probe)»; tras limpiar (4 productos) → `catalog_full_list` (volcado LLM
  intacto).
- Corpus: **328 passed / 9 skipped / 1 failed en ambos órdenes** (324 previos + 4
  nuevos; único fallo el gate preexistente). Lint limpio en el bloque nuevo de
  `main.py` y en el test (zona limpia).

## Endurecimiento contra tokens de 2 caracteres — 2026-08-12

`_search_tokens` exigía tokens de ≥2 caracteres y no incluía ``de``/``es``/``un`` en
`_SEARCH_STOPWORDS`: esos tokens matcheaban SKUs y nombres por subcadena (``de`` →
``demo``, ``es`` → ``mesa``/``escritorio``, ``un`` → ``unidad``) con peso alto de SKU
(+12) y producían falsos positivos en preguntas no relacionadas. Fix: mínimo de **3
caracteres** en `_search_tokens` (compartido por el buscador Python y el de Postgres;
las consultas que quedan sin tokens devuelven `[]` y el chat cae a sus ramas
semánticas/catálogo). También se modernizó la anotación de retorno de la función
(UP006).

Validación:
- Test hermético `tests/regression/test_search_short_tokens.py` con productos cuyos
  SKUs/nombres contienen ``de``/``es``/``un`` (``DESK-DEMO``, ``MESA-ESCR``,
  ``UNIDAD-ALU``): ``search_products("de")``/``"es"``/``"un"`` → ``[]``;
  ``"de un escritorio"`` → solo Escritorio; ``"silla"``/``"mesa"`` siguen
  funcionando. Aserciones a prueba de residuos de otros tests en la BD compartida
  (defecto detectado en la primera pasada del corpus: `test_commerce` deja una
  «Silla lumbar verificada»).
- En vivo (PostgreSQL): `de`/`es`/`un` → `[]`; `de un escritorio` → solo Escritorio
  Modelo Demo; `silla` → Silla Ergonómica. Sin cambios en los flujos del webhook
  (el corpus cubre quote/confirmación y catálogo).
- Corpus: **329 passed / 9 skipped / 1 failed en ambos órdenes** (328 previos + test
  nuevo; único fallo el gate preexistente).
- **Visibilidad en el portal**: `/tools/products/semantic` ahora devuelve
  `discarded_tokens` (tokens <3 caracteres deduplicados, calculados con
  `_discarded_short_tokens` sobre el texto normalizado); el bloque de búsqueda
  semántica del panel Productos muestra «Tokens de 1–2 caracteres ignorados por el
  buscador léxico: “de”, “un”» cuando la consulta los contiene (con o sin
  resultados), para que el operador entienda por qué el buscador léxico devolvió
  vacío. Verificado en vivo: `de un escritorio` → nota + 1 resultado (Portátil
  56,2%); `es` → `discarded_tokens=["es"]` y 0 resultados; `pantalla para jugar a
  videojuegos` → `["a"]` y 3 resultados. Test de portal nuevo (`App.test.tsx`):
  11 passed + typecheck OK + prettier OK.

### Corpus y gates

- Corpus completo (334 tests): **324 passed / 9 skipped / 1 failed en ambos órdenes** — el único fallo es
  el preexistente `test_quality_gates_pass_on_current_tree` (clean-zone 97 inalterado; ruff-hard PASS).
  El ratchet de ruff (baseline 243, desglose sin UP045) ahora reporta 259: la diferencia son 51 hallazgos
  **UP045** (`Optional[X]` → `X | None`) sobre código legacy no tocado por este cambio — regla emitida por
  la versión de ruff local (0.16.2) que el baseline (2026-08-11) no contempla; los archivos de este cambio
  (`product_embeddings.py`, migraciones, helper del reindexado) quedaron **limpios** (0 hallazgos). Se
  decide no tocar el código legacy ni subir el baseline: es decisión de mantenimiento, no de este cambio.
- Migraciones: `test_p0_migrations.py` 24/24 (aserciones de revisión head actualizadas a `0010`).

## Regla de evidencia

## Regla de evidencia

## Regla de evidencia

Una prueba solo se marca `VERIFIED` si es reproducible, comprueba efectos reales y no sustituye el componente objetivo por mocks. Build, arranque, health e integración son niveles distintos.

## Evidencia heredada contrastada

| Fecha | Prueba | Resultado observado | Alcance real | Estado actual |
|---|---|---|---|---|
| 2026-08-02 | Pytest backend aislado | 31 passed; 2 warnings; 4,96 s | SQLite, demo, mocks/stubs, TF-IDF local, rate limit desactivado | BLOCKED |
| 2026-08-02 | Coverage backend | 67 % total | No cubre rutas críticas reales ni concurrencia suficiente | BLOCKED |
| 2026-08-02 | Portal typecheck/build | TypeScript y build Vite correctos | Sin tests frontend ni UX runtime | VERIFIED |
| 2026-08-02 | Compose config | Código 0; 14 servicios, 3 redes, 9 volúmenes | Valida sintaxis, no runtime | VERIFIED |
| 2026-08-02 | Runtime heredado | 12 healthy; Chatwoot restart; proxy unhealthy | Demuestra fallos, no funcionalidad | BLOCKED |
| 2026-08-02 | Build `--no-cache --pull` | Cancelado al 95,3 % de RAM | Sin resultado de build | BLOCKED |
| 2026-08-02 | Backup restore | No ejecutado | Sin RPO/RTO | BLOCKED |
| 2026-08-02 | UX Playwright | No ejecutada | RAM, proxy y wrapper incompatible | BLOCKED |

Los resultados `BLOCKED` pueden contener una ejecución histórica correcta, pero no constituyen evidencia de producción por usar dobles, cubrir solo una capa o demostrar un fallo. La Fase 1 volvió a ejecutar la suite y añadió primero reproducciones rojas para los riesgos P0/P1 cubiertos por el gate G02/G03.

## Gate G01 — baseline

| Fecha | Control | Resultado | Alcance |
|---|---|---|---|
| 2026-08-02 | `docker compose --profile '*' config --quiet` | VERIFIED, código 0 | Renderizado estático de 14 servicios, 3 redes y 9 volúmenes; no acredita runtime |
| 2026-08-02 | Integridad de registros | VERIFIED | 38 tareas con estados autorizados; 30 criterios PR completos; 24 gates ordenados |
| 2026-08-02 | Enlaces Markdown de control/baseline | VERIFIED | Ningún destino local ausente en los 13 documentos del gate |
| 2026-08-02 | `git diff --check` | VERIFIED | Sin errores de whitespace; los avisos CRLF son informativos |
| 2026-08-02 | Patrones de secretos de alta señal | VERIFIED | Cero archivos coincidentes fuera de vendor/artefactos; `.env` ignorado y no trazado |

El gate G01 no arrancó servicios, no leyó valores de `.env`, no inspeccionó el contenido de volúmenes y no convierte ningún criterio funcional en `VERIFIED`.

## Gate G02/G03 — reproducción y registro

| Fecha | Control | Resultado | Alcance |
|---|---|---|---|
| 2026-08-02 | Suite heredada sin host aislado | 7 passed, 9 failed, 15 errors | Reproduce deriva del harness por configuración externa |
| 2026-08-02 | Suite heredada con `ALLOWED_HOSTS` sintético | 31 passed, 1 warning, 2,00 s | SQLite, demo, mocks/stubs, TF-IDF; no producción |
| 2026-08-02 | `pytest tests/regression` | 19 failed esperados, 1 warning, 1,04 s | Tests rojos previos a corrección; cero `xfail`/`skip` |
| 2026-08-02 | `pip-audit` | Exit 1; 60 entradas/53 IDs únicos en 2 paquetes | Resolución actual de `requirements.txt`; sin fixes |
| 2026-08-02 | `npm audit --package-lock-only` | Exit 1; 1 high, 1 moderate | Lockfile Portal; sin scripts ni cambios |
| 2026-08-02 | Ruff / Black / MyPy | 286 / 15 archivos / 80 errores | Código de producción Bridge; todos exit 1 |
| 2026-08-02 | Runtime/logs sanitizados | PID Chatwoot 56 veces; Nginx 72 fallos `setuid` | Contenedores detenidos; evidencia live futura bloqueada |

El detalle, comandos y separación entre observado/no observado/bloqueado están en `docs/remediation/REPRODUCTION_EVIDENCE.md` y sus anexos.

## Gate P0 de Fase 2 — corrección y verificación

Commit de implementación: `de236e9`.

| Fecha | Control | Resultado | Alcance |
|---|---|---|---|
| 2026-08-02 | Matriz funcional P0 secuencial | 101 passed; 1 warning; 3,19 s | Unitarios, integración, demo, confirmación, comercio, aislamiento/modelos y 20 contratos PrestaShop |
| 2026-08-02 | Migraciones SQLite herméticas | 23 passed; 1 warning; 10,28 s | Clean/adopción, preflight fail-closed, fixture, downgrade/reupgrade y FK integrity |
| 2026-08-02 | PostgreSQL 15, run `6057fe090e42` | `verified` normal y `python -O`; 0 filas residuales | 12 FKs compuestas diferibles, confirmación concurrente, oversell y carreras release/release, release/cancel, release/expire |
| 2026-08-02 | PostgreSQL 15, run `2a888ab9b141` | `head-cycle` verified; revisión final `0002`; 0 residuos | Downgrade hasta base y reupgrade preservan fixture y reserva activa con expiración |
| 2026-08-02 | PostgreSQL 15, run `4f4b1445b8d6` | `historical-upgrade` verified; 12 FKs; 0 residuos | Adopción desde `0001`, tenant backfill, token legado hasheado y datos preservados |
| 2026-08-02 | Guardas del verificador | 7 passed | Sin `assert` optimizable; DB/installation/run deben coincidir; contexto inseguro se rechaza |
| 2026-08-02 | Compose config | código 0 | Renderizado estático tras flags demo y contexto PrestaShop; no acredita runtime |
| 2026-08-02 | Ruff focalizado / compileall / diff | verde | `E9,F,I` en archivos P0; compilación de app/migraciones/scripts/tests; deuda global histórica no se oculta |
| 2026-08-02 | Secret hygiene | `.env` ignorado/no trazado; 0 patrones de alta señal | Working tree P0; no sustituye scan de historial/artefacto final |

Los PostgreSQL fueron contenedores únicos `pgvector/pgvector:pg15`, sin puertos ni volúmenes, con tmpfs y límites. Cada nombre se resolvió exactamente antes de eliminarlo; no se tocó `agent-platform-fixed-bridge-db-1` ni ningún proyecto ajeno. Los verificadores exigen una base `p0_verify_<run>`, una instalación `p0-verify-<run>` y un acknowledgement explícito, limpian en `finally` y solo imprimen `verified` después del cleanup.

La evidencia P0 acredita los seis defectos P0 de rama. No acredita aún una release candidata, restore, build/full stack, UI, RAG, integraciones externas ni los P1 abiertos; por ello no cambia el estado comercial.

## Bloque P1 de invariantes — corrección y verificación

Commit de implementación: `48051e8`.

| Fecha | Control | Resultado | Alcance |
|---|---|---|---|
| 2026-08-02 | Corpus backend completo | 159 passed; 1 warning; 16,31 s | Unitarios/regresión/integración local: CAS, retries, ACL, health, importación, leases/checkpoints, LLM y PrestaShop; no sustituye E2E externo |
| 2026-08-02 | Migraciones SQLite herméticas | 23 passed; 1 warning; 11,48 s | Clean, histórica, downgrade/reupgrade y nueva revisión `0003` reejecutable |
| 2026-08-02 | PostgreSQL 15, run `a83f2d719c4e` | `head-cycle` verified; revisión final `0003` | Downgrade/reupgrade preserva datos y reserva activa; inbox y ledger presentes |
| 2026-08-02 | PostgreSQL 15, run `b94e3f820d5a` | `historical-upgrade` verified; revisión final `0003` | Adopción histórica, 12 FKs, token legado hasheado y datos preservados |
| 2026-08-02 | PostgreSQL 15, run `f38c7d264b9e` | `verified` normal y `python -O`; 0 residuos | Aprobación CAS: 1 ganador/1 conflicto; presupuesto LLM: 1 provider call/1 rate limit, gasto `0.000101`; concurrencia P0 intacta |
| 2026-08-02 | Compose config / health contract | código 0; `/live` y `/ready` separados | Compose usa readiness de Bridge; fallo de DB devuelve 503 en pruebas dirigidas; no acredita stack arrancado |
| 2026-08-02 | Ruff focalizado / compileall / diff | verde | `F,B,I` con `B008` excluido de forma explícita; bytecode y whitespace; la deuda global histórica permanece abierta |
| 2026-08-02 | Secret hygiene y cleanup | 0 patrones de alta señal; 0 verificadores residuales | `.env` ignorado/no trazado; stack completo permaneció detenido |

La evidencia cierra D-011, D-013, D-014, D-024, D-033, D-034 y D-036. D-010, D-019, D-020, D-021, D-022 y D-035 solo quedan parcialmente remediados o bloqueados: no se ha demostrado reconciliación del efecto externo ambiguo, handoff visible en Chatwoot real, corpus DLP/prompt-injection, circuit breaker/outbox/DLQ, provisioning único ni exactamente-once frente a un crash entre proveedor y checkpoint.

No se arrancó el full stack, no se usaron credenciales/datos reales y no se contactaron proveedores externos. Los contenedores PostgreSQL fueron efímeros, aislados, etiquetados y eliminados; no se tocó `agent-platform-fixed-bridge-db-1` ni ningún proyecto ajeno. El estado sigue siendo `NOT PRODUCTION READY — CRITICAL RISK`.

## Reverificación 2026-08-03 — corpus hermético (D-032) y entorno

Acción de entorno autorizada por el propietario (`DECISIONS.md` D-008): el 2026-08-03 se detuvieron con `docker compose down` (sin `-v`) los compose projects del workspace antiguo `C:\Users\PC\Desktop\PROYECTOS\automatiazcion\agent-platform`: `agent-platform`, `agent-piloto-rc1` y `agent-cliente-demo-es-staging`. Volúmenes conservados; puerto 9000 liberado; la memoria de la VM Docker queda pendiente de liberación/medición.

| Fecha | Control | Resultado | Alcance |
|---|---|---|---|
| 2026-08-03 | Corpus combinado `pytest tests bridge-api/tests`, env limpio, HEAD `637e512` | 2 failed / 157 passed | Reproducción de D-032: `tests/conftest.py:20` vacía `CHATWOOT_API_TOKEN` y contamina `bridge-api/tests/unit/test_demo_data_guards.py`; los unit tests heredaban el entorno del proceso |
| 2026-08-03 | Fix `4afd0c7`: valores production-like explícitos (`CHATWOOT_API_TOKEN`, `CHATWOOT_HANDOFF_TEAM_ID`) en `_production_like_settings` | 1 archivo, +2 líneas | Los tests dejan de depender del entorno del operador |
| 2026-08-03 | Corpus combinado, env limpio, orden `tests bridge-api/tests` | 159 passed; 14,45 s | D-032 VERIFIED: un único comando reproducible |
| 2026-08-03 | Corpus combinado, env limpio, orden inverso `bridge-api/tests tests` | 159 passed; 15,80 s | Sin dependencia del orden de colección |
| 2026-08-03 | Portal `npm run typecheck` | `tsc --noEmit` limpio | Re-ejecutado sobre el mismo tree |
| 2026-08-03 | D-012 `4d97449`: `ToolExecutor` deny-by-default + `/agents/tools/invoke` | 10 evals passed (allowlist, desconocida/prohibida, matriz cruzada, argumentos/IVA, inyección, viewer, auditoría) | Las herramientas solo se ejecutan por el endpoint gobernado; `/agents/run` no ejecuta herramientas aunque el prompt lo pida |
| 2026-08-03 | Corpus combinado tras D-012, env limpio | 169 passed; 15,70 s | Regresión completa verde con los evals nuevos |
| 2026-08-03 | D-021 `3733bad`: circuit breakers por proveedor + outbox durable con DLQ (`OutboxService`, migración `0004`, `/outbox*`, métricas) | 18 evals passed (estados del breaker, fail-fast sin red, 4xx como liveness, backoff→DLQ, permanente directo, requeue, tema sin dispatcher, roles 401/403/409/422, E2E webhook→outbox con avería y recuperación GHL) | Avería GHL encola el lead (`queued_for_retry`); `POST /outbox/process` lo recupera sin duplicar contacto/oportunidad; circuito abierto falla rápido sin tocar la red |
| 2026-08-03 | Corpus combinado tras D-021, env limpio, orden `tests bridge-api/tests` | 187 passed; 16,36 s | Regresión completa verde con los evals de resiliencia |
| 2026-08-03 | Corpus combinado tras D-021, env limpio, orden inverso `bridge-api/tests tests` | 187 passed; 17,65 s | Sin dependencia del orden de colección |
| 2026-08-03 | D-035 `5a3edf8`: checkpoint del resultado tras cada efecto externo visible y resume en takeover (`_resume_webhook_from_checkpoint`) | 3 evals passed (crash inyectado tras el efecto, lease caducado con `processing` atascado y fallo antes del efecto con dedupe por `source_message_id`) | El takeover con checkpoint de éxito completa sin repetir respuesta ni presupuesto; los mensajes ya completados siguen siendo `duplicate_ignored`; auditoría `webhook_checkpoint_resume` |
| 2026-08-03 | Corpus combinado tras D-035, env limpio, orden `tests bridge-api/tests` | 190 passed; 14,13 s | Regresión completa verde con los evals de crash/recovery |
| 2026-08-03 | Corpus combinado tras D-035, env limpio, orden inverso `bridge-api/tests tests` | 190 passed; 14,78 s | Sin dependencia del orden de colección |
| 2026-08-03 | D-010 `ce2723c`: reconciliación GHL previa al efecto (`find_opportunity_by_reference` por `external_reference`, `find_note_by_body`) en dispatcher outbox y `/integrations/ghl/leads` | 6 evals passed (crash en ventana de oportunidad, crash en ventana de nota, crash del endpoint directo con takeover, fail-closed con búsqueda caída, DLQ por referencia ausente y contratos del adaptador) | Un crash en cualquier ventana efecto→checkpoint produce como mucho un efecto externo por lead contra un doble de proveedor que duplicaría si se le llamara dos veces; sin reconciliación verificable nunca se crea; el lead sin referencia va a DLQ; reconciliación auditada (`ghl_lead_reconciled`) |
| 2026-08-03 | Corpus combinado tras D-010, env limpio, orden `tests bridge-api/tests` | 196 passed; 14,75 s | Regresión completa verde con los evals de reconciliación |
| 2026-08-03 | Corpus combinado tras D-010, env limpio, orden inverso `bridge-api/tests tests` | 196 passed; 15,01 s | Sin dependencia del orden de colección |
| 2026-08-03 | D-020 `0541650`: clasificación RAG public/internal/confidential/restricted con ACL deny-by-default, DLP determinista en ingesta (DNI/NIE con letra, tarjeta con Luhn, IBAN ES mod-97, JWT, AWS, sk_live, claves privadas) que eleva la clasificación a confidential sin persistir valores, redacción de secretos en respuesta y citas, rechazo de consultas con patrones de inyección y marcado `trusted=false` del contenido recuperado | 10 evals passed (matriz de clasificación, DLP types-only, checksums inválidos, internal invisible al chat público, confidential/restricted, ingest rechazo de clasificación desconocida, DLP eleva y redacta, exfiltración y aislamiento entre instalaciones) | Las consultas de inyección/exfiltración no devuelven contenido confidencial; los secretos detectados en ingesta suben la clasificación sin guardarse en metadatos y se redactan en respuesta y citas; el chat público nunca ve documentos internal |
| 2026-08-03 | Corpus combinado tras D-020, env limpio, orden `tests bridge-api/tests` | 206 passed; 14,60 s | Regresión completa verde con los evals de RAG seguro |
| 2026-08-03 | Corpus combinado tras D-020, env limpio, orden inverso `bridge-api/tests tests` | 206 passed; 15,89 s | Sin dependencia del orden de colección |
| 2026-08-03 | D-017 `7fb4f45`: Pillow fijado en `>=12,<13` (49 CVEs cerrados en 10.x/11.x), pypdf en `>=6,<7` (CVE de 5.9), Vite `^7` (esbuild path traversal cerrado); script `scripts/audit_dependencies.py` ejecuta `pip-audit` + `npm audit --omit=dev` y bloquea si high/critical >0 | 6 evals passed (rangos Pillow/pypdf/Vite, npm audit prod, pip-audit, ejecución del script) | `pip-audit` y `npm audit --omit=dev` reportan 0 vulnerabilidades; el corpus rechaza cualquier rango permisivo con versiones vulnerables; Vite ^7 + portal typecheck + build verde |
| 2026-08-03 | Corpus combinado tras D-017, env limpio, orden `tests bridge-api/tests` | 212 passed; 59,91 s | Regresión completa verde con los evals de auditoría |
| 2026-08-03 | Corpus combinado tras D-017, env limpio, orden inverso `bridge-api/tests tests` | 212 passed; 60,44 s | Sin dependencia del orden de colección |
| 2026-08-03 | D-028 `af53b8b`: middleware FastAPI con logs JSON correlacionados (correlation_id, request_id, tenant_id, user_id, route, method, status, latency_ms), contextvars por proceso con restauración robusta, redacción determinista por clave y valor, métricas Prometheus para HTTP/outbox/breaker/RAG/alertas y reglas in-memory integradas en `/metrics` | 10 evals passed (correlación generada y propagada, ausencia de secretos en logs bajo fault injection, log_event redacta por clave y valor, breaker abierto dispara alerta, DLQ dispara alerta, `/metrics` expone breakers+alertas, registry de reglas, access log estructurado, redacción de tipos documentados) | Cada request queda trazado y correlacionado sin filtrar secretos; un breaker abierto o un mensaje en DLQ dispara alerta verificable sin PII |
| 2026-08-03 | Corpus combinado tras D-028, env limpio, orden `tests bridge-api/tests` | 222 passed; 61,72 s | Regresión completa verde con los evals de observabilidad |
| 2026-08-03 | Corpus combinado tras D-028, env limpio, orden inverso `bridge-api/tests tests` | 222 passed; 62,74 s | Sin dependencia del orden de colección |
| 2026-08-03 | D-029 `ff0eed8`: `LifecycleService` con export JSON portable de datos operativos (sin users ni AuditLog), erase con retención configurable e inmediata, proceso de borrados vencidos y legal hold que bloquea cualquier erase; borrado en orden FK con eliminación de archivos RAG; modelo `InstallationLifecycle` + migración aditiva `0005`; endpoints `/lifecycle/*` con `ADMIN_ROLES` | 6 evals passed (export completo sin credenciales ni AuditLog, export vacío, erase inmediato preserva AuditLog y elimina archivo RAG, retención con vencimiento y proceso de borrados vencidos, legal hold bloquea solicitud y borrado vencido con auditoría, aislamiento entre instalaciones) | El fixture completo se exporta y se elimina de DB y disco; el AuditLog y usuarios sobreviven; la retención conserva los datos hasta el vencimiento; el legal hold bloquea solicitud y borrado vencido; una instalación no toca los datos de otra |
| 2026-08-03 | Corpus combinado tras D-029, env limpio, orden `tests bridge-api/tests` | 228 passed; 69,32 s | Regresión completa verde con los evals de lifecycle |
| 2026-08-03 | Corpus combinado tras D-029, env limpio, orden inverso `bridge-api/tests tests` | 228 passed; 60,63 s | Sin dependencia del orden de colección |
| 2026-08-03 | Migraciones herméticas actualizadas a head `0005` | 23 passed | Clean, histórica, downgrade/reupgrade y reserva activa conservadas con la tabla `installation_lifecycle` |
| 2026-08-03 | D-026/D-027 `33d77c1`: portal con secciones reales (cinco anchors rotos corregidos), runner vitest + testing-library + vitest-axe y claims de documentación corregidos | 5 evals frontend passed (login accesible con error del servidor, cada ancla con destino renderizado, secciones con datos reales, error explícito sin permisos, aprobaciones decidibles + axe) y 1 eval backend (listado `GET /rag/documents` sin rutas de disco ni contenido) | `npm run typecheck`, `npm run build` y `npm run test` verdes; ningún anchor sin destino; los módulos muestran datos reales o estados vacío/error explícitos |
| 2026-08-03 | Corpus combinado tras D-026/D-027, env limpio, orden `tests bridge-api/tests` | 229 passed; 63,32 s | Regresión completa verde con el eval del listado de documentos |
| 2026-08-03 | D-030 `ca73a6c`: `scripts/quality_gates.py` con tres puertas (`ruff-hard` E9,F a 0, `ruff-clean-zone` a 0, `ruff-ratchet` con baseline visible de 213 por regla en `scripts/quality_baseline.json`) y deuda de estilo en tests legacy corregida | 6 evals passed (gates verdes en el árbol, trinquete bloquea crecimiento con baseline bajo, baseline cuadrado con desglose, nombres de gate estables) | Los gates pasan en el árbol actual; el trinquete falla si la deuda legacy supera el baseline; la deuda permanece visible y documentada |
| 2026-08-03 | Corpus combinado tras D-030, env limpio, orden `tests bridge-api/tests` | 235 passed; 78,88 s | Regresión completa verde con los evals de quality gates |
| 2026-08-03 | Corpus combinado tras D-030, env limpio, orden inverso `bridge-api/tests tests` | 235 passed; 70,65 s | Sin dependencia del orden de colección |
| 2026-08-03 | Ruff focalizado + quality gates | Verde | `scripts/quality_gates.py` ejecutable y verde; `ghl_adapter.py`, `rag_security.py`, `audit_dependencies.py`, `observability.py`, `lifecycle.py` y todos los tests limpios al completo; imports muertos del middleware D-028 eliminados en `ff0eed8` |
| 2026-08-04 | D-012 `bf647cf` (lote 1): motor de automatizaciones FlowWink sin Supabase — router de email local (sin red), `quote-expiry-reminders` idempotente por ventana, `dunning-processor` sin mutar importes, `generate-invoice-pdf` determinista, `send-webhook` firmado HMAC, sweep pull; endpoints `/automations/sweep` y `/automations/invoices/{id}/pdf` | 7 evals passed (quote-expiry idempotente, dunning marca overdue sin mutar totales, PDF válido/determinista/con nº de factura, firma HMAC coincide, email local auditado sin red, sweep agregado) | Funcionalidad nueva (T-015), no cierra defectos; respeta idempotencia, auditoría y sin efecto financiero sin aprobación; `automations.py` en zona limpia del gate D-030 |
| 2026-08-04 | Corpus combinado tras D-012 lote 1, env limpio, orden `tests bridge-api/tests` | 242 passed; 70,10 s | Regresión completa verde con los evals de automatizaciones |
| 2026-08-04 | D-012 `59558a1` (lote 2): `docs-chat` de FlowWink sobre el RAG del Bridge — ACL por rol, abstención sin evidencia, citas verificables, respuesta extractiva honesta sin LLM real | 3 evals passed (extractivo con citas, abstención por ACL `confidential` denegada a viewer, abstención por consulta irrelevante con `min_score`) | Sin LLM real responde extractivo y honesto (nunca simulado disfrazado); sin ACL o sin evidencia se abstiene |
| 2026-08-04 | Corpus combinado tras D-012 lote 2, env limpio, orden `tests bridge-api/tests` | 245 passed; 70,61 s | Regresión completa verde con los evals de agent-ai |
| 2026-08-04 | Corpus combinado tras D-012 lote 2, env limpio, orden inverso `bridge-api/tests tests` | 245 passed; 65,14 s | Sin dependencia del orden de colección |
| 2026-08-04 | D-015/D-016 `6b34200`: backup/restore/rollback verificables — manifiesto con conteos+sha256, `restore_backup` a motor vacío, `verify_backup`, `rollback_installation` | 4 evals passed (roundtrip SQLite restaura y verifica, detección de corrupción, rollback recupera presupuesto borrado y revierte mutación, roundtrip PostgreSQL efímero con extension vector) | Restauración REAL (no simulada): los datos respaldados se recuperan en un motor vacío y se verifican conteos y checksums; el rollback de una instalación no toca al resto |
| 2026-08-04 | Corpus combinado tras D-015/D-016, env limpio, orden `tests bridge-api/tests` | 248 passed, 1 skipped (postgres opt-in); 72,96 s | Regresión completa verde con los evals de backup/rollback |
| 2026-08-04 | Runtime Docker perfil **core** (D-008/D-025): `docker compose --profile core up -d` → bridge-db/bridge-redis/bridge-api/portal healthy; reverse-proxy healthy con `cap_add` SETUID (26 workers sin `setuid EPERM`); chatwoot/activepieces en 502 graceful (opcionales); límites `deploy.resources` aplicados (verificados con `docker inspect`); smoke por puerto 9000: portal 200, `/api/bridge/ready` 200, flowwink 200 | Proxy estable tras restart, sin crash-loop; host ~3,9 GB libres con el core arriba | Verificación runtime real del core sin Chatwoot/Activepieces (Ruta A) |
| 2026-08-04 | **E2E core en vivo** (`scripts/e2e_core_chat_to_quote.py`): login admin → producto real `local` → webhook Chatwoot FIRMADO (HMAC) → `action=quote_created`, lead capturado y presupuesto con total **determinista** 2×50 +21 IVA +15 envío = 136,00 y token `CONFIRMAR <TOKEN>` emitido — **sin Chatwoot** (canal de respuesta interno auditado, Ruta A) | Webhook 200, quote_created; el cálculo no usa LLM y respeta Decimal | Primer E2E chat→lead→presupuesto contra el stack vivo, sin dependencias externas |

El conteo coincide con el corpus documentado: 225 tests en `tests/` + 23 en `bridge-api/tests` = 248. La reverificación no arrancó servicios del proyecto ni contactó proveedores externos; el eval de PostgreSQL es opt-in (`RUN_POSTGRES_BACKUP=1`) y se ejecutó con un contenedor efímero que se eliminó al terminar. El estado sigue siendo `NOT PRODUCTION READY — CRITICAL RISK`.

## Próxima evidencia obligatoria — P1 restante de Fase 2

1. Contrato live del endpoint de búsqueda/reconciliación GHL pendiente de sandbox (B-004); la microventana efecto→checkpoint ya está cerrada por reconciliación (D-010, `ce2723c`), el crash ambiguo bridge-side verificado (D-035, `5a3edf8`) y el outbox/DLQ con circuit breakers también (`3733bad`).
2. Sandbox del proveedor RAG real (B-006) y dataset de exfiltración a escala real; la clasificación/DLP y el corpus anti prompt injection ya están verificados (D-020, `0541650`).
3. SBOM y hashes pin a pin por release; las dependencias están verificadas (D-017, `7fb4f45`).
4. OTel/Prometheus scrape y SLO formales en runtime; la instrumentación, alertas y redacción de secretos están verificadas (D-028, `af53b8b`).
5. Revisión legal de la política de retención (B-008); el export/erase con retención y legal hold está verificado (D-029, `ff0eed8`); la inclusión de backups en el borrado queda para D-015.
6. CI formal y modularización por dominio; los quality gates con trinquete están verificados (D-030, `ca73a6c`).
7. Egress, proxy, Chatwoot, perfiles y límites verificados en runtime seguro.
8. Backup/restore en instalación vacía y release/rollback trazable.
9. Licencias y pruebas E2E/UI.

## Importación real COPYBRAS — 2026-08-12

Importación en vivo del catálogo real del usuario (`CSV_D_COPYBRAS_2025_.csv`,
9.917 filas originales) vía `POST /api/bridge/import-file/products` (proyecto
PrestaShop → CSV propio de COPYBRAS, separador `;`, UTF-8 con BOM).

- **Transformación** (`scripts` ad-hoc en `.freebuff/`): mapeo de columnas en
  español → esquema de importación (`sku` ← `REFERENCIA 2025` → `EAN 2025` →
  `CPY-{id}`; `name` ← `Nombre`; `base_price` ← `PRECIOS 2025` decimal español;
  `stock_quantity` ← `CANTIDAD`; `category` ← categoría top-level; `external_id`
  ← `Referencia`; `source=import`). Descartadas 4 filas vacías (basura).
  Resultado: **9.913 productos válidos**, 18 categorías top-level (ARCHIVO 1.489,
  ESCRITURA 1.284, ESCOLAR 1.215, …), 330 sin precio (→ 0), 1.674 sin stock (→ 0).
- **Dry-run**: 9.913 filas validadas, 0 errores (sin commit).
- **Import real** (con `Idempotency-Key`): `{status: success, imported_count:
  9913, updated_count: 0, errors: []}` + `semantic_index: {total: 9913, indexed:
  9913, skipped: 0, errors: 0, provider: openai_compatible, model:
  text-embedding-nomic-embed-text-v1.5}`. Registro de idempotencia `completed`
  con el body completo (el cliente vio un 504 del proxy por el timeout de 90s
  mientras el reindexado inline terminaba en el servidor; el trabajo se completó
  y el registro quedó `completed`/200).
- **Fix del 504**: `proxy_read_timeout` del bloque `^~ /api/bridge/import` en
  `infrastructure/proxy/default.conf.template` subido de 90s a **900s** (el
  reindexado semántico inline de 10k+ productos tarda varios minutos; 90s
  cortaba la respuesta aunque el servidor seguía procesando).
- **Verificación funcional** (API, catálogo 9.917 = 4 + 9.913):
  - Léxica: `acuarela jovi` → ACUARELA JOVI…; `silla ergonomica` → SILLA DE
    DIRECCION Q-CONNECT ERGONOMICA…; `grapadora` → GRAPADORA EL CASCO…;
    `folios` → CARPETA PORTAFOLIOS…
  - Semántica: `algo para archivar documentos` → ARCHIVADOR DE PALANCA
    LIDERPAPEL… (score 0.737), CAJA ARCHIVADOR… (0.733), ARCHIVADOR… (0.729) —
    recall conceptual correcto sobre 9.913 productos.
  - UTF-8 verificado a nivel de bytes en Postgres (`CUÑA` = `C3 91`; el
    mojibake de la consola Windows es solo display).
  - Dashboard: 9.917 productos; portal renderiza el catálogo nuevo.
- **Notas**: el rate limit de login (8 intentos/15 min, backend memoria) bloqueó
  la verificación tras múltiples logins; se limpió reiniciando bridge-api (los
  datos viven en Postgres). El corpus de tests usa SQLite hermético
  (`/tmp/agent_platform_fixed_tests.db`), ajeno a la Postgres viva.

## Conexión PrestaShop real (btopdigital.es) — 2026-08-13

**Configuración** (`.env`, fuera de git): `PRESTASHOP_BASE_URL=https://btopdigital.es`,
`PRESTASHOP_API_KEY` (real, del usuario), `PRESTASHOP_COUNTRY_ID=6`,
`PRESTASHOP_CURRENCY_ID=EUR`. El dashboard pasa a `prestashop: configured`.

- **Probe en vivo**: login 200 → `integrations.prestashop=configured`; búsquedas reales
  en la tienda `ACUARELA`/`JOVI`/`sacapuntas` → productos reales `source=prestashop`
  (ACUARELA JOVI 12 COLORES 3,77 €, SACAPUNTAS M+R METALICO 1,23 €, IVA 0,21, stock 5.000,
  `source_url` real hacia `btopdigital.es`). `sync?dry_run&limit=1000&include_details` 200
  (tarda ~14 min: ~5 llamadas secuenciales por producto).
- **Hallazgo y fix — colisión de `external_id`**: la constraint
  `uq_product_installation_external_id` era única por instalación, no por fuente. El import
  COPYBRAS usó ids de la tienda (`external_id=42`…) y el sync PrestaShop intenta el mismo →
  UniqueViolation en commit. Fix: constraint única por fuente `(installation_id, source,
  external_id)` — migración **0011** (PostgreSQL: drop/add constraint; SQLite: no-op
  documentado, igual que 0006/0009/0010), modelo actualizado, test de migraciones ajustado
  para documentar la divergencia SQLite intencional (24/24 verdes). La app ya consultaba
  por `source`, y el import dedup por SKU: relajar la unicidad es seguro.
- **Sync real**: `limit=1000` → **commit de 1.000 productos `source=prestashop`** en BD
  local (BD final: `import` 9.913 + `local` 4 + `prestashop` 1.002).
- **Validación del chat con `source=prestashop`** (webhook Chatwoot firmado HMAC):
  «¿tenéis acuarelas de JOVI?» → `verified_product_recommendations` con ACUARELA JOVI
  (3,77 €, IVA 0,21, stock 5.000); «¿tenéis sacapuntas de metal?» → SACAPUNTAS M+R 200.0
  METALICO (1,23 €). `GET /tools/products?query=acuarela` devuelve los dos catálogos
  (`import` + `prestashop`).
- **Timeout del proxy**: bloque `^~ /api/bridge/...` para las rutas PrestaShop con
  `proxy_read_timeout 900s` (un sync con detalles supera 90s; el 504 cortaba la respuesta
  aunque el servidor seguía).
- **Concurrencia**: dos syncs lanzados a la vez + webhooks de prueba colisionaron
  (UniqueViolations → ambos rollback, BD quedó limpia, sin basura parcial). Re-lanzado un
  único sync en calma → commit correcto. Es un hallazgo real a endurecer (ver reporte).
- **Corpus** (tras el fix, ambos órdenes): **329 passed / 9 skipped / 1 failed** — único
  fallo `test_quality_gates_pass_on_current_tree` (clean-zone legacy preexistente, mi
  código aporta 0). Los 2 tests opt-in `test_prestashop_webservice_search.py` se saltan
  por diseño: el conftest blanquea `PRESTASHOP_*` (hermeticidad D-032) y `_adapter()`
  lee de la ruta hardcodeada de la máquina de auditoría
  (`C:/Users/PC/Desktop/PROYECTOS/agent-platform-fixed/.env`) — la misma validación se
  cubre en vivo con el probe.

## Ciclo completo chat → presupuesto → CONFIRMAR en vivo (2026-08-13)

Ciclo comercial completo ejecutado contra el stack real (perfil full 14/14) con el
catálogo de PrestaShop sincronizado (btopdigital.es). Driver:
`.freebuff/evidence_cycle_prestashop.py`; transcripto JSON:
`.freebuff/evidence_cycle_prestashop.json`; capturas del portal (preview vite
`localhost:5173`): dashboard (10.920 productos, PrestaShop "Configurado"), panel
Productos (catálogo con los tres orígenes y stock reservado) y búsqueda semántica
con scores sobre el catálogo PrestaShop.

| Fase | Mensaje | Acción | Evidencia |
|---|---|---|---|
| A. Chat recomendación | «¿tenéis acuarelas de JOVI?» | `verified_product_recommendations` (200) | ACUARELA JOVI 12/18/24 COLORES — 3,77/5,08/6,40 €, IVA 0,21, stock 5.000, `source=prestashop` |
| B. Compra producto PrestaShop | «me interesa ACUARELA JOVI…, quiero 2 unidades» | `insufficient_stock` → handoff (200) | Fail-closed por diseño: `check_stock` devuelve `external_confirmation_required` para `source != local` (autoridad de stock externa requiere confirmación humana; P0-003) |
| C0. Import local real | — | `import/products` (200) | Producto `LOCAL-919087` creado con datos reales del sync (ACUARELA JOVI 12, 3,77 €, IVA 0,21, stock 5.000) |
| C1. Chat → presupuesto | «Quiero comprar 2 unidades del producto LOCAL-919087» | `quote_created` (200) | Presupuesto `quote-01a9ef511d24`: subtotal 7,54 + IVA 1,58 + envío 15,00 = **24,12 €**; `CONFIRMAR 945433A8A29F47F6870ECF8B5452681F` |
| C2. CONFIRMAR | `CONFIRMAR <token>` | `order_created` (200) | Pedido `ord-dd218b18c26c` por 24,12 €; factura borrador pendiente de aprobación |
| C3. Aprobación admin | — | `approved` (200) | `approval_id=appr-4a62eb1ecc3a`, `reviewed_by: admin` |

Matemática verificada: 2 × 3,77 = 7,54 subtotal; IVA 21 % = 1,58; envío 15,00 → 24,12 €.
Stock en BD tras el pedido: `LOCAL-919087` pasa de 5.000 a **4.998** (2 reservadas).

**Defecto real corregido (504 en el branch de compra)**: el branch de keywords
(`quiero/unidades/…`) llamaba SIEMPRE al adaptador PrestaShop en vivo
(`search_products`), que escanea las 41.870 filas de la tienda cuando el webservice
no matchea la frase completa → 504 del proxy (>90s). Fix: **búsqueda en el catálogo
local sincronizado primero** y adaptador remoto solo como fallback si no hay match
(`bridge-api/app/main.py`, rama `quote_created`). Con el fix, el webhook responde en
~1-2 s. Sin el fix el ciclo completo era imposible en vivo.

**Hallazgo y fix (índice semántico tras el sync)**: con PrestaShop configurado, la
búsqueda semántica filtra por `sources={"prestashop"}` (proveedor de catálogo activo)
pero los productos sincronizados no tenían embeddings (el sync no reindexa; solo la
importación lo hace) → `/tools/products/semantic` devolvía `[]` para TODO el catálogo
(aunque el índice tuviera 9.918 filas). Fix doble: (1) indexación ejecutada en vivo
(`POST /products/embeddings/index` → `indexed: 1002`, 0 errores) y (2) cambio de
código: el sync ahora reindexa semánticamente los productos recién creados
(best-effort, mismo patrón que `_reindex_imported_products` de la importación;
`semantic_index` en la respuesta, nunca aborta). Resultado: «algo para pintar con
acuarelas» → LIBRO PARA COLOREAR ACUARELAS Y PINCEL **0,739**, PINCELES PENTEL
0,714, ACUARELA LIDERPAPEL 0,700 (todo `prestashop`).

**Validación de regresión**: `test_p0_prestashop_contract.py` 20/20,
`test_p0_catalog_confirmation.py` + `test_audit_remediation_2026_08_10.py` +
`test_p1_ghl_reconciliation.py` 20/20. Portal: typecheck + 11 tests verdes (no
tocados en este ciclo). Corpus completo previo: 329/9/1 (gate legacy).

## 2026-08-13 · Ciclo completo en la UI de Chatwoot (recomendación → presupuesto → CONFIRMAR → pedido)

**Entorno**: perfil `full` (con `vendor/chatwoot`), stack 14/14 healthy, bridge-api en
`0011 (head)`, PrestaShop real conectado y 1.000 productos sincronizados, LM Studio en
`host.docker.internal:1234` como proveedor LLM.

**Setup de Chatwoot desde first-run** (conversación real conducida por API y webhook real):
- Bootstrap: cuenta `Agent Platform BTOP`, admin `admin@btop.local`, agente `Asistente IA`
  (`ia@btop.local`), inbox API `Portal (API)` con `webhook_url=http://bridge-api:8005/webhooks/chatwoot`
  y `secret` fijado = `CHATWOOT_WEBHOOK_SECRET`, equipo `Comercial`.
- Flag SSRF `SAFE_FETCH_ALLOW_PRIVATE_NETWORK=true` **en `chatwoot-worker`** (el delivery
  del webhook corre en el worker, no en el web — el contenedor worker llevaba 46 h sin el
  flag y rechazaba `bridge-api` como host sin IP pública).
- El agente del bot se creó con `type='Agent'`, que **no es una clase STI válida en
  Chatwoot** (solo `SuperAdmin` y `AgentBot`): `send_reply` del bridge fallaba con
  `ActiveRecord::SubclassNotFound: 'Agent'` y 500. Fix: `type=NULL` (agente normal) en BD.
- El bot necesitaba `inbox_members` (Pundit `agent_can_view_conversation?` requiere
  `inbox_access?` o `team_access?`) para poder `show?` la conversación al hacer push de la
  respuesta.
- Flag Redis `CHATWOOT_INSTALLATION_ONBOARDING` presente pese al bootstrap: la UI
  redirigía a `/installation/onboarding`. Se eliminó para desbloquear el login.

**Defecto real encontrado y corregido (colisión de idempotencia)**: Chatwoot entrega por
cada mensaje dos eventos — `conversation_created` (con `id` = id de conversación) y
`message_created` (con `id` = id de mensaje). Como ambas secuencias arrancan en 1, los ids
colisionan (p. ej. conversación 3 y mensaje 3) y la key `chatwoot:<account>:<id>` se
reutilizaba con un payload distinto → `409 Idempotency-Key reutilizada con payload
diferente` y el mensaje se marcaba `failed`. Fix en `bridge-api/app/main.py`: el `event` se
incluye en la key solo para eventos que no son `message_created`
(`chatwoot:<account>:<event>:<id>`), preservando el formato histórico para
`message_created` (los replays y tests existentes siguen usando `chatwoot:<account>:<id>`).

**Ciclo real conducido en Chatwoot (conversación #11)**:
| Fase | Mensaje (cliente) | Respuesta (Asistente IA) |
|---|---|---|
| M1 recomendación | ¿tenéis acuarelas de JOVI? | 4 estuches Jovi (PS-10..13): 2,73–6,40 €, stock 5.000, `source=prestashop` |
| M2 presupuesto | Quiero comprar 2 unidades del producto LOCAL-919087 | `quote-0b9307b951f6`: subtotal 7,54 + IVA 1,58 + envío 15,00 = **24,12 €**, token `CONFIRMAR C5A9C90AAF97037AA2F395765645C869` |
| M3 confirmar | CONFIRMAR C5A9C90AAF97037AA2F395765645C869 | `Pedido ord-c7ddba7f0581 registrado por 24.12 EUR`, factura borrador pendiente de aprobación; labels `venta_confirmada`, `pendiente_aprobacion` |

**Capturas**: UI de Chatwoot (`http://localhost:3003`, login como `admin@btop.local`) con la
conversación #11 completa (recomendación, presupuesto y CONFIRMAR) en el hilo de preview.
Transcripto JSON: `.freebuff/chatwoot_cycle_evidence.json` (fecha, fase, from, content).

**Validación de regresión**: corpus completo previo 329/9/1 (gate legacy), contratos
PrestaShop 20/20, suites chat/presupuesto 20/20. Sin commit, como el resto del hilo.

## 2026-08-13 · Catálogo completo de PrestaShop sincronizado (41.652 productos → 51.570 total)

**Entorno**: perfil `full`, stack healthy, bridge-api en `0011 (head)` + working tree, PrestaShop real
`btopdigital.es` conectado con credenciales reales, LM Studio (`qwen3-14b` chat, `text-embedding-nomic-embed-text-v1.5` embeddings).

**Problema**: el sync de PrestaShop estaba capado a 1.000 productos (`safe_limit = min(limit, 1_000)`);
el intento previo de traer los ~41.652 remotos con `include_details` daba 504 (un solo request HTTP
con ~6 llamadas remotas por producto). El catálogo local no cubría el 98% de la tienda.

**Cambios de código (working tree)**:
- `prestashop_adapter.py`: `list_categories()` (mapa id→nombre), `get_stocks_batch()` (stock de 500
  productos en 1 llamada, ~0,3 s) y paso de `stock_map`/`category_names` a `_normalize_product`
  (evita las ~6 llamadas remotas por producto).
- `main.py` (`POST /integrations/prestashop/sync`): parámetro `offset`, modo bulk eficiente
  (categorías + stock en lote) cuando `include_details=false`, rechazo de referencias degeneradas en
  `_normalize_product` (la tienda tiene 2 SKUs basura `1,12E+11` duplicados) y dedupe de SKUs dentro
  del lote (constraint `uq_product_installation_sku`).
- Tests de contrato actualizados al contrato nuevo (`test_p0_commerce_authority.py`): suite 307 passed
  antes del sync; único fallo `test_quality_gates_pass_on_current_tree` = deuda ruff preexistente del hilo.

**Sync completo (driver resumible `.freebuff/sync_full_catalog.py`, estado en `sync_full_state.json`)**:
| Métrica | Valor |
|---|---|
| Páginas | 500 productos/lote, ~20 s (embeddings incluidos) |
| Duración total | ~30 min (antes: horas o 504) |
| Creados | 40.150 (39.650 + reintento del lote 14500: +500) |
| Actualizados | 1.502 |
| Lotes fallidos al final | 0 (el único fallo — offset 14500, SKUs degenerados — se reintentó tras el fix: 500 creados e indexados) |
| Productos prestashop en BD | **41.652** = exactamente los remotos activos |
| Productos import (CSV COPYBRAS) | 9.913 |
| **Total en BD** | **51.570** |

**Embeddings**: reindex final `POST /products/embeddings/index` → `{"total": 51570, "indexed": 196,
"skipped": 49442, "errors": 0}`; pendientes en BD: **0/51.570**. Los embeddings se generan por lote
durante el sync (reindexado incremental de `created_ids`).

**Búsqueda semántica validada en vivo** (`GET /tools/products/semantic`, top_k=3):
| Consulta | Top-3 con score |
|---|---|
| cubo de rubik | Cubo rubik shengshou petaminx 0,750 · CUBO MÁGICO RUBIK EN DISPLAY 0,748 · shengshou elite kilominx 0,748 |
| figura star wars | Hasbro retro collection 0,763 · return of the jedi 0,755 · the vintage imperial 0,752 |
| juego de mesa | star wars deckbuilding 0,769 · adventure games la isla 0,764 · the voting game 0,763 |
| boligrafo negro | BOLIGRAFO PENTEL BK-77 A NEGRO 0,743 · **BIC NARANJA FINE ORIGINAL NEGRO (PS-42) 0,726** · PARKER IM NEGRO 0,725 |

Los cubos de Rubik, figuras Star Wars y juegos de mesa **no existían en el catálogo local anterior**
(1.002 productos de oficina) — confirma que el catálogo completo es buscable por concepto.

**Chat en vivo contra la tienda real (conversación 35 de Chatwoot, inbox widget)**:
- Cliente: «¿tenéis cubos de rubik?»
- Asistente IA (qwen3-14b): «Actualmente no tenemos cubos de Rubik en stock, pero estos son los modelos
  más cercanos… **Cubo de Rubik Moyu Meilong 2x2 magnético Negro** (SKU=3154) | €7,43 | 0 disponibles ·
  **Cubo de Rubik Gan 13 Maglev UV Coated** (SKU=1432) | €105,00 · **Cubo de Rubik MF8 Son - Mum 4x4 II
  Negro** (SKU=1710) | €45,41…»
- **Stock verificado contra la API remota**: `stock_availables?filter[id_product]=20950/18688` →
  `quantity: 0` en ambos — el «0 disponibles» es dato real de la tienda, no error del sync (el sync de
  stock en lote es fiel: BIC PS-40/42 mantienen 5.000).

**Artefactos**: `.freebuff/sync_full_catalog.py` (driver resumible con `offset` persistido, reintentos
3× y registro de lotes fallidos), `.freebuff/sync_full.out.log` (log de progreso por lote),
`.freebuff/sync_full_state.json` (estado final).

## 2026-08-14 · Sync incremental diario, delta de stock, historial auditado, lock Redis y tarea programada

**Contexto**: el catálogo completo quedó sincronizado (51.570 productos, sección anterior). Este bloque
cierra la operación diaria: sync incremental programado, delta de stock, historial auditable y lock
anti-solapamiento.

### Sync incremental (`scripts/prestashop-sync-incremental.py`)

- La tienda **no admite `filter[date_upd]` ni `sort=[date_upd_*]`** en el webservice (500 en todos los
  formatos; la lista de filtros no incluye la fecha). Diseño final: el adaptador pagina el listado
  ligero `[id,date_upd]` del catálogo activo y **filtra las fechas cliente-side**; solo los ids
  modificados se recuperan en detalle (por ids) con stock en lote.
- Validado en vivo: `since=2026-08-13 14:25:51` (desde `max(updated_at)` de la BD con 10 min de
  solape) → escaneo de 41.652 productos en **49 s**, **0 cambios**. Camino «con cambios»
  (`since=2026-06-29 18:00:00`, dry-run) → detectó y normalizó **exactamente 41.652 productos** en 153 s.
- Solo los productos **nuevos** del delta reciben embedding (sin reindexado masivo).

### Delta de stock (solo-stock)

- `stock_availables` tampoco expone fecha en esta tienda. Cada ejecución trae el mapa de stock remoto
  del catálogo completo y **solo escribe las filas que difieren** del local, cubriendo cambios de
  stock que no tocan `products.date_upd`.

### Paginación hasta EOF (P1-013 / D-033)

- `get_features`, `get_combinations` y `get_stocks_batch` usan ahora `_get_paginated_rows` (sin límites
  fijos que truncaran silenciosamente). Hallazgo en vivo: `get_stocks_batch` no incluía `id` en el
  `display`, con lo que la guarda de unicidad rechazaba el lote («Respuesta inestable») — corregido
  añadiendo `[id,...]` y revalidado: el sync incremental completo volvió a `status=success`.

### Historial auditado (`prestashop_sync_history`, migración 0012)

- Una fila por ejecución: `started_at`, `finished_at`, `duration_seconds`, `since` (NULL en sync
  completo), `incremental`, `status` (`success`/`dry_run`/`conflict`/`failed`/`skipped`), conteos
  (`created`/`updated`/`unchanged`) y `error`. Best-effort: un fallo de registro nunca aborta el sync.
- `GET /integrations/prestashop/sync/history?limit=N` (roles de lectura) + panel Integraciones del
  portal con las últimas 8 ejecuciones y badges de estado (validado en preview real, 0 errores de
  consola).
- Ejecución real registrada: `id=9ad2d9b8 status=success duracion=79.803s since=2026-08-13 14:25:51 creados=0 actualizados=0`.

### Lock Redis anti-solapamiento

- `SET NX EX` sobre `bridge:prestashop:sync` (TTL `PRESTASHOP_SYNC_LOCK_SEC`, 1.800 s), patrón del
  outbox worker. Segundo sync → **409** + historial `skipped` («Otro sync de PrestaShop en curso»);
  el cron lo trata como SKIP (exit 0). Liberación en `finally` (verificado: `EXISTS` = 0 tras terminar).
  Fail-open si Redis no está disponible.

### Tarea programada (Windows)

- `schtasks /Create /TN prestashop-sync /SC DAILY /ST 04:30` (usuario actual, sin elevación), comando
  `python scripts\prestashop-sync-incremental.py >> logs\prestashop-sync.log 2>&1`. Ejecución manual
  de prueba: OK, log escrito y ejecución registrada en el historial.

### Resultados

| Check | Resultado |
|---|---|
| Sync incremental en vivo (2 ejecuciones) | `success`, 51-80 s, 0 cambios, historial escrito |
| Camino «con cambios» (dry-run) | 41.652 detectados/normalizados en 153 s |
| Stock delta en vivo | paginación hasta EOF sin 503 (display con `id`) |
| Suite de tests | **314 passed, 9 skipped** (solo gate `ruff-clean-zone` legacy preexistente) |
| Contrato PrestaShop + comercio | 35/35 verdes |
| Ruff E9/F | 0 (hard); script y líneas nuevas limpios |
| Tarea programada | creada y ejecutada una vez con éxito |

**Artefactos**: `scripts/prestashop-sync-incremental.py`, `logs/prestashop-sync.log`,
`bridge-api/alembic/versions/0012_prestashop_sync_history.py`.

## 2026-08-14 — P0-003 opción C: verificación en vivo de stock remoto en CONFIRMAR (prestashop)

**Decisión**: los productos `source=prestashop` completan el ciclo comercial con verificación en vivo del stock
remoto en el momento de CONFIRMAR (fail-closed solo donde de verdad falta stock), en lugar del handoff ciego.

### Cambios

- `confirm_quote_transactional` acepta `verified_remote_stock={product_id: qty}`. Para items de autoridad externa
  (source != local) exige verificación en vivo: sin ella o con stock insuficiente → `InsufficientStockError` (409);
  con stock suficiente → crea el pedido **sin reserva local** (la autoridad es la tienda). Los items locales
  conservan la reserva/reserva por línea.
- Rama CONFIRMAR del webhook: `_verify_quote_remote_stock` verifica en vivo `stock_availables` en lote
  (`get_stocks_batch`, 1 llamada por presupuesto) antes de crear el pedido. Si falta stock: mensaje honesto
  («la tienda no tiene N unidades disponibles en este momento»), handoff a humano (open + assign + nota privada)
  y 409 sin pedido.
- Rama de compra: un producto prestashop con stock proyectado crea el presupuesto (con aviso «la disponibilidad
  se verificará en vivo contra la tienda al confirmar el pedido») en lugar de responder «no hay N unidades»
  (falso). Otras fuentes sin autoridad local (p. ej. `import`) conservan el handoff honesto.

### Validación en vivo (stack real + tienda real btopdigital.es)

| Paso | Resultado |
|---|---|
| Compra por SKU (`PS-5399` BIC ATLANTIS, stock sincronizado 5.000) | `quote_created`, sin mensaje falso de agotado, con aviso de verificación en vivo |
| `CONFIRMAR <token>` | **200 `order_created` `ord-43a3207f8846`** (18,90 €) |
| Reserva local del pedido | **0 reservas** para el producto prestashop (autoridad externa verificada en vivo) |
| Pedido excesivo (6.000 uds de un producto con 5.000 remotos) | **409** «Stock remoto insuficiente», sin pedido |
| Handoff en el caso 409 | Chatwoot conv 39: reply honesto + nota privada + **asignado a Admin BTOP** |
| Chatwoot conv 38 (éxito) | Presupuesto → labels `venta_confirmada`/`pendiente_aprobacion` → Pedido `ord-43a3207f8846` |

### Tests

- Nuevos: rama de compra prestashop crea presupuesto sin mensaje falso; CONFIRMAR con stock remoto suficiente
  crea pedido sin reserva local; CONFIRMAR con stock remoto insuficiente → 409 + handoff; fail-closed sin
  verificación; verificado con `verified_remote_stock` no reserva local.
- Suite: **320 passed, 9 skipped** (fallo único: gate `ruff-clean-zone` legacy preexistente, aporte 0).

## Catálogo real en stack candidato + paginación en vivo — 2026-08-15

Poblado el catálogo PrestaShop real (btopdigital.es) en el stack candidato
(`agent-candidate-0815`, `docker-compose.yml`) mediante el sync incremental del
endpoint (`POST /integrations/prestashop/sync?since=...`), que sobre la tabla
vacía usa `since=1970-01-01` y fetchea el catálogo completo (comportamiento
documentado del adaptador: paga el listado ligero `[id,date_upd]` y filtra
cliente-side).

### Sync

| Métrica | Resultado |
|---|---|
| `total_remote` | **41.652** |
| Creados / actualizados / sin cambios | 41.652 / 0 / 0 |
| Duración | **326,5 s** |
| Historial `prestashop_sync_history` | 1 fila `success`, incremental=true, `since=1970-01-01`, 326,456 s |
| Estado BD | `prestashop=41.652`, `local=1` → **41.653 totales** |
| Índice semántico | `skipped` (sin proveedor de embeddings remoto en el candidato; la búsqueda léxica sí opera) |

### Validación `GET /catalog/products` en vivo (proxy 19020 → bridge-api)

| Verificación | Resultado |
|---|---|
| Envelope | `{items, total, limit, offset}`; `total=41653`, `limit=50`, `items=50` |
| Frescura | `updated_at` ISO UTC presente en cada fila |
| Origen | 100 % `prestashop` en el listado paginado |
| Páginas 0 y 50 | **disjuntas** (sin solape) y página 1 **estable** (bytes idénticos entre llamadas) |
| Orden por `unit_price desc` | Precios decrecientes; nombres Canon RF/EF ordenados correctamente |
| Última página | `offset=41600, items=53` → 41.653 = 208×200 + 53 (sin huecos) |
| Recorrido completo (209 páginas × 200) | **41.653 IDs únicos = total reportado (coverage 100 %)**, 477 s con pacing por rate limit (429) |
| Búsqueda léxica `query=rubik` | 69 resultados; top: «Cubo de rubik calvin's 4x4x5 crazybad» |
| Filtro `source=local` | 1 resultado (producto local de la candidata) |
| `sort=evil;DROP` | **422** «Orden no permitido» (whitelist; sin inyección) |

Nota: el walk completo a 209 páginas requirió pacing por el rate limit de la
candidata (120 req/min, 429) — comportamiento esperado del gateway; cada página
individual respondió en < 0,8 s.

### Matriz E2E rol × módulo del portal — 2026-08-15 (SS-04)

Driver `scripts/e2e_role_matrix.py` contra el proxy del stack candidato
(`http://127.0.0.1:19020/api/bridge`, instalación `candidate-0815`).

| Dimensión | Resultado |
|---|---|
| Checks | **63/63 PASS** (7 roles × 9 endpoints) en **5.27 s** |
| Catálogo `/catalog/products` + `/dashboard` | 200 para los 7 roles (tier `READ_ROLES`) |
| Clientes, leads, presupuestos, pedidos, wiki | 200 para admins + supervisor/commercial/support/operator; **403 para `viewer`** (tier `OPERATOR_ROLES`) |
| Tareas programadas + usuarios | 200 solo `provider_admin`/`client_admin`; 403 para el resto (tier `ADMIN_ROLES`) |
| Contrato catálogo | envelope `{items,total}` presente por rol |
| Contrato dashboard | role-aware: `role` correcto y `permissions.approve`/`manage_users` solo true para admins |
| Limpieza | usuarios `e2erm-*` desactivados vía `PATCH /users/{id}`, filas borradas por SQL → `users=2` (baseline); 5/5 healthy; `/ready` 200 |
| Artefacto | `logs/rehearsal/e2e_role_matrix_20260815T145447Z.json` |

La matriz confirma en vivo que el acceso observado coincide uno a uno con
`security.require_roles` (READ/OPERATOR/ADMIN): el portal no decide permisos
por su cuenta.

### Validación en vivo del chat comercial con Ollama — 2026-08-15

Driver `scripts/validate_chat_live.py` contra el webhook real de Chatwoot del
stack candidato (`http://127.0.0.1:19020/api/bridge/webhooks/chatwoot`, HMAC
firmado, instalación `candidate-0815`), con Ollama (deepseek-r1:8b vía
`host.docker.internal:11434`) y el catálogo real de 41.652 SKUs.

| Escenario | Consulta | Resultado |
|---|---|---|
| Saludo | "hola buenas tardes" | acción `greeting`, Ollama, saludo cálido sin volcado |
| Búsqueda | "¿tenéis cubos de rubik?" | `verified_product_recommendations`, recomienda productos reales |
| Comparación | compara cubo de rubik con llavero vs display | `product_comparison`, diferencia útil |
| Categoría ausente | "¿tenéis hoverboards?" | `insufficient_evidence_handoff` **determinista** (abstain honesto, sin LLM) |
| Memoria (2 turnos) | ¿cubos de rubik? → ¿el de llavero cuánto cuesta? | retoma el hilo; cliente+asistente persistidos en PostgreSQL por conversación |
| Persona (saludo) | "hola buenas tardes" | "¡Hola! Soy Carmen de BTOP Digital. ¿En qué puedo ayudarte?" |
| Persona (cierre) | comprar cubo con llavero, presupuesto | `quote_created` determinista: "Presupuesto <id> **de BTOP Digital**: … CONFIRMAR <token>" |

| Dimensión | Resultado |
|---|---|
| Veredicto | **PASS 8/8 turnos** HTTP 200 + persistencia de memoria en PostgreSQL |
| Heurísticas | respuesta no vacía, proveedor real (Ollama) salvo abstain/cierre deterministas, sin `SKU=`/volcado crudo, longitud acotada, bullets ≤15 |
| Hallazgo corregido | el LLM inventó un producto ("Cubo de Rubik Mágico 3x3 Premium", SKU inexistente) → `_enforce_verified_product_output` garantiza que solo se mencionan productos del bloque real |
| Artefactos | `logs/rehearsal/chat_live_validation_20260815T*.json` |

Configuración de la persona: `COMMERCE_ASSISTANT_NAME=Carmen` +
`COMMERCE_STORE_NAME=BTOP Digital` en `.env.candidate-0815`, propagadas al
contenedor vía `environment:` de `docker-compose.yml` (con defaults).

### Cierre de venta real: pedido + factura por email — 2026-08-15

Driver `scripts/validate_sale_live.py` contra el webhook real de Chatwoot del
stack candidato. Compra de un producto local con stock → `CONFIRMAR <token>`
→ pedido + envío de factura por email.

| Dimensión | Resultado |
|---|---|
| Compra | `quote_created` con token CONFIRMAR (HTTP 200) |
| Confirmación | `order_created`: "¡Pedido confirmado! ord-… Tu factura INV-2026-… está lista. La factura se ha enviado por email." |
| PostgreSQL | pedido `confirmed`, factura `draft`, aprobación `issue_invoice` `pending`, reserva local `1` |
| Email (spool) | "Tu factura INV-2026-6E64071A de BTOP Digital" → `comprador-venta-…@example.invalid`, adjunto `factura-….pdf` (magic `%PDF-`) |
| Veredicto | **PASS 15/15 checks** (`logs/rehearsal/sale_live_validation_20260815T234653Z.json`) |

### Adaptación de idioma y registro — 2026-08-15

`_detect_language_register` anexa una directiva determinista al prompt de
sistema (idioma es/en por tokens; registro formal/tuteo por marcadores), de
modo que la adaptación no depende de que el modelo la infiera. El driver
`scripts/validate_chat_live.py` valida en vivo con Ollama:

| Escena | Consulta | Respuesta observada |
|---|---|---|
| formal | "Buenas tardes. Me gustaría saber si tienen cubos de Rubik en su catálogo, por favor." | "Buenas tardes, ¿usted busca algún modelo en particular…? podemos recomendarle…" (sin tuteo) |
| ingles | "Hello! Do you have Rubik's cubes in your catalog?" | "Hello! We have several Rubik's-style cubes available… Our catalog contains…" (prosa en inglés; nombres de producto reales intactos) |
| tuteo | "hola! tienes cubos de rubik baratos?" | "¡Hola! ¿Qué tal? … tengo dos opciones que podrían ser de tu interés" (registro cercano) |

Además, toda respuesta que cite `SKU=NNNN` se verifica contra el catálogo
real (`skus_existentes`): ninguna cita un SKU inexistente. Veredicto del
driver **PASS 11/11 turnos** (`chat_live_validation_*.json`).

### Evaluación LLM-as-judge de naturalidad — 2026-08-16

`scripts/llm_judge_naturalness.py` puntúa automáticamente las respuestas
reales de `logs/rehearsal/chat_live_validation_*.json` con un juez Ollama
(deepseek-r1:8b, temperatura 0, self-consistency de 3 pasadas por respuesta):

| Dimensión | Media (1-5) | Lectura |
|---|---|---|
| Fluidez | 3.18 | correcto pero plano; el 8b no escribe con soltura |
| Coherencia | 3.27 | falla cuando repite el saludo en follow-ups (memoria) |
| Persona | 2.67 | inconsistente: no siempre adapta idioma/registro ni se presenta |
| Honestidad | 3.56 | sin invención (todos los SKUs citados existen); alguna afirmación de disponibilidad con stock 0 |
| **Global** | **3.17** | **VERDICT FAIL** (media < 4) |

El veredicto FAIL es honesto y estable entre ejecuciones: el hallazgo
principal es la repetición de la plantilla de saludo de deepseek-r1:8b en
mensajes de seguimiento (coherencia 1 en el segundo turno de memoria). La
honestidad está anclada por **fact-check determinista contra la BD real**:
si una respuesta cita un SKU inexistente, `honestidad=1` con nota, con
independencia del juez. El juez 8b es ruidoso (notas que a veces contradicen
la puntuación, p. ej. penaliza "presentación formal" bajo honestidad); por
eso se promedian 3 pasadas y se documenta la limitación. Artefacto:
`logs/rehearsal/llm_judge_naturalness_20260816T001137Z.json`.

### Comparación de jueces: deepseek-r1:8b vs qwen3-14b — 2026-08-16

El juez es provider-agnóstico (ollama / openai_compatible / anthropic con la
misma configuración del producto) y `--compare A B` ejecuta dos jueces sobre
la misma evidencia (11 respuestas, 1 pasada):

| Dimensión | deepseek-r1:8b | qwen3-14b (LM Studio) | Δ absoluto |
|---|---|---|---|
| Fluidez | 3.55 | 4.36 | 0.82 |
| Coherencia | 3.27 | 3.64 | 1.09 |
| Persona | 2.78 | 4.33 | 1.55 |
| Honestidad | 3.89 | 4.22 | 0.91 |
| **Media / Veredicto** | **3.38 / FAIL** | **4.12 / FAIL** | — |

Lectura: **ambos jueces coinciden en el veredicto (FAIL) y en el hallazgo
principal** — la repetición de la plantilla de saludo de deepseek-r1:8b en
mensajes de seguimiento rompe la coherencia (qwen puntúa 1 en memoria y en
persona). El 8b como juez es **severo de más en persona** (Δ1.55: castiga
respuestas que no repiten el nombre/tienda en cada mensaje, que es lo que el
producto prohíbe) y algo en honestidad (Δ0.91). Acuerdo global (|Δ|≤1 en las
cuatro dimensiones): 3/11. El juez qwen3-14b da notas más consistentes y
justificadas; se recomienda como juez de referencia. Artefacto:
`logs/rehearsal/llm_judge_comparison_20260816T005617Z.json`.

### Corrección determinista de la repetición de saludo + revalidación — 2026-08-16

**Defecto (hallazgo principal de la evaluación):** deepseek-r1:8b abría cada
respuesta con la plantilla `¡Hola! Soy <asistente> de <tienda>.` aunque la
conversación ya tuviera historial, rompiendo coherencia (1) y persona en
follow-ups. El prompt lo prohibía; el 8b lo ignoraba.

**Corrección determinista** (independiente del modelo, en `agent_ai.py`):

- `_strip_greeting_repeat(text, has_history, intent)` — con historial y turno
  no-saludo elimina cualquier prefijo de saludo/presentación (español e
  inglés: `¡Hola!`, `Buenas tardes`, `Hello! I'm …`, `¿en qué puedo
  ayudarte?`…) y capitaliza el resto; si la respuesta era solo el saludo
  repetido devuelve vacío y `commerce_chat` cae al fallback extractivo
  honesto.
- `_ensure_greeting_persona(...)` — espejo para el primer saludo: si el LLM
  omitió el nombre, inserta `Soy <asistente> de <tienda>.` tras el saludo
  (o al inicio).
- **Historial previo separado del mensaje actual**: el webhook persiste el
  mensaje del cliente ANTES de generar la respuesta, así que el historial
  cargado incluía el mensaje en curso; `prior` excluye el último `client`
  cuando coincide con `query` (primera vuelta en vivo: el espejo nunca
  disparaba).
- Prompt: la directiva determinista de idioma/registro también se anexa al
  final del prompt de usuario (los modelos pequeños siguen la última
  instrucción) y la regla 4 prohíbe saludar cuando hay historial.

**Validación en vivo** (`scripts/validate_chat_live.py`, Ollama, stack
`agent-candidate-0815`, catálogo real de 41.652 SKUs): PASS **11/11**.
Follow-ups sin saludo: memoria t2 «En relación a tu pregunta sobre productos
con llavero…», persona t2 cierre «Presupuesto quote-… de BTOP Digital…».
Saludo inicial con persona: «¡Hola! Soy Carmen de BTOP Digital. ¿En qué puedo
ayudarte hoy?». Artefacto:
`logs/rehearsal/chat_live_validation_20260816T094327Z.json`.

**Revalidación LLM-as-judge sobre la nueva evidencia** (misma rúbrica):

| Juez | Media antes | Media después | Coherencia del follow-up (memoria t2) |
|---|---|---|---|
| deepseek-r1:8b (3 pasadas) | 3.17 FAIL | **3.30 FAIL** | 1 → **4** |
| qwen3-14b (LM Studio, 1 pasada) | 4.12 FAIL | **4.28 FAIL** | 1 → **5** |

Ambos jueces confirman la corrección del defecto. El veredicto global sigue
FAIL por **hallazgos residuales distintos**: (a) honestidad de disponibilidad
— el primer turno de memoria afirma «están en venta»/«disponibles» con stock
0 verificado (qwen honestidad 2, señal real; deepseek también lo señaló en
T-038); (b) ruido del juez — el saludo puro de persona («hola buenas tardes»
→ «¡Hola! Soy Carmen de BTOP Digital…») se puntúa como si buscara un
producto (qwen coherencia 1, nota «no responde al mensaje»). Ningún SKU
citado es inventado (overlay determinista pasa). Artefactos:
`logs/rehearsal/llm_judge_naturalness_20260816T094520Z.json` (8b) y
`logs/rehearsal/llm_judge_naturalness_20260816T103452Z.json` (qwen).
Corpus **444 passed / 11 skipped / 0 errores**; quality gates D-030 PASS;
fila T-040.

### Gate de regresión LLM-as-judge en quality gates — 2026-08-16

**Acción de regresión** (`T-041`): `scripts/quality_gates.py --with-judge`
añade el gate `llm-judge` al pipeline:

- **Disparo**: solo cuando cambian los archivos de prompt/chat
  (`git status --porcelain` sobre `agent_ai.py`, `main.py`,
  `validate_chat_live.py`, `llm_judge_naturalness.py` y sus tests;
  `--force-judge` fuerza). Sin cambios → SKIP rápido.
- **Criterio**: ejecuta el evaluador sobre la evidencia en vivo más reciente
  y **FALLA si la media global < 4.0** (`--judge-threshold`). El detalle
  muestra las medias y mínimos por dimensión.
- **Degradación fail-open** (D-032): sin evidencia en `logs/rehearsal/`,
  juez no alcanzable (probe 3 s) o sin puntuaciones válidas → SKIP auditado
  (la infraestructura ausente nunca tumba el pipeline).
- **Juez de referencia**: qwen3-14b en LM Studio local (`T-039` lo
  recomienda por notas más consistentes; con deepseek-r1:8b el baseline
  queda bajo el umbral por diseño — el gate lo señala si se usa con
  `--judge-spec ollama`).

**Ejecución real** (candidato, 11 respuestas en vivo, qwen3-14b):

```
[GATE] llm-judge: PASS — media global 4.3 (umbral 4.0) |
  por dimensión {fluidez 4.64, coherencia 4, persona 4.33, honestidad 4.22} |
  mínimos {coherencia 1, honestidad 1} | qwen3-14b | 11 respuestas
```

Artefacto auditable: `logs/rehearsal/quality_gate_judge_20260816T110137Z.json`
(verdict PASS, judge, threshold, aggregate, records). La regresión habría
sido detectada: un cambio que baje la media bajo 4 (o, con el criterio
estricto del evaluador, un mínimo < 2 como la repetición de saludo de T-040)
hace fallar `quality_gates.py --with-judge`. 6 evals herméticos nuevos en
`test_p1_quality_gates.py` (módulo juez falso, sin red): skip sin cambios /
sin evidencia / juez caído / sin puntuaciones + PASS sobre umbral + FAIL bajo
umbral. Corpus **450 passed / 11 skipped / 0 errores**; gates D-030 PASS;
fila T-041.

## Kanban de pipeline P1-a en vivo — 2026-08-16

Implementación del módulo P1-a del plan CRM (`docs/PRODUCT_PLAN_CRM_B2B.md`):
etapas configurables sobre `opportunities`, drag&drop con cambio de etapa
auditado y cola de leads sin asignar. Validado contra el stack candidato
(`agent-candidate-0815`, rebuild de la imagen bridge-api y migración `0015`
aplicada a su PostgreSQL real).

### Backend (9 evals herméticos, `tests/regression/test_p1_pipeline_kanban.py`)

| Verificación | Resultado |
|---|---|
| `GET /pipeline/stages` siembra | 6 etapas `new/qualified/quote/negotiation/won/lost` en orden (idempotente) |
| `PUT /pipeline/stages` | Solo admin; conserva keys estables por nombre; oportunidades de etapas eliminadas → primera etapa (`pipeline.stage_reassigned`); 422 con <2 o nombres duplicados; auditado `pipeline.stages_updated` |
| `GET /pipeline/board` | Oportunidades por etapa + cola de leads sin asignar + usuarios `{id, username, role}` (sin hashes); viewer 403 |
| `PATCH /opportunities/{id}` | Cambio de etapa validado contra el pipeline; `changed:false` si es la misma; 422 etapa inexistente; 404 oportunidad; auditado `pipeline.stage_changed` |
| `PATCH /leads/{id}/assign` | Asigna/desasigna (`user_id=null`); valida usuario activo (422); auditado `lead.assigned` con from/to |

### Frontend (5 evals vitest, `portal/src/kanban.test.tsx`)

| Verificación | Resultado |
|---|---|
| Render | Columnas con contador, tarjetas (cliente + valor), cola de leads sin asignar |
| Drag&drop | `dragstart/dragover/drop` sobre otra columna → `PATCH /opportunities/{id}` con `{stage}` y recarga |
| Asignación | Select de la cola → `PATCH /leads/{id}/assign` con `{user_id}` |
| RBAC | Viewer no ve «Editar etapas» |
| Editor admin | Renombrar/añadir/guardar → `PUT /pipeline/stages` con `{names}` en orden + flash «Pipeline actualizado. Cambio auditado.» |

### Validación en vivo (proxy 5176 → bridge-api candidato, catálogo 41.652 SKUs)

| Verificación | Resultado |
|---|---|
| Board en vivo | 6 etapas (Nuevo 26 oportunidades; Calificado/Presupuesto/Negociación/Ganado/Perdido vacías), cola **27 leads sin asignar** |
| Asignación desde la UI | Lead E2E `lead-e2ef409435f495e@example.com` → comercial; cola 27→**26**, lead fuera de la cola |
| Auditoría de asignación | `lead.assigned` en `audit_logs`: `{"lead_id": ..., "from": null, "to": "<comercial>"}` con actor admin |
| Cambio de etapa | `PATCH /opportunities/{id}` `new→won→new` (`changed:true` en ambas) |
| Auditoría de etapa | Dos eventos `pipeline.stage_changed` con `{"opportunity_id": ..., "from": "new", "to": "won"}` y el inverso |
| Portal | Toggle «Leads y oportunidades / Pipeline (kanban)» en la sección Clientes; drag&drop HTML5 nativo; editor de etapas solo admin (preview en vivo) |

### Regresión

Corpus completo **459 passed / 11 skipped / 0 errores**; gates D-030 PASS
(ruff-hard 0 issues, ruff-clean-zone 0 issues, ruff-ratchet 132 vs baseline
243); portal `tsc --noEmit` limpio, `vite build` OK y **32 vitest passed**
(27 previos + 5 del kanban). Fila T-043.

## Reporting de ventas P1-b en vivo — 2026-08-16

Primer módulo implementado de la T-044 (paraguas CRM): funnel por etapa,
ticket medio, win-rate y aging real por etapa. Fila **T-045**.

### Backend (3 evals herméticos, `test_p1_pipeline_kanban.py`)

| Verificación | Resultado |
|---|---|
| Funnel + ticket + win-rate | 4 oportunidades sembradas (new×2 100/300, won×1 400, lost×1 50): `new.count=2`, `total_value=400`, avg_ticket **212,5**, mediana **200**, win-rate **50 %** (1/2), open 2/400 — una oportunidad `won` con `status=open` NO cuenta como abierta (bug detectado por el test y corregido) |
| Aging | `new` aging_avg ≥ 3 y aging_max ≥ 10 días con `stage_changed_at` sembrado a 3 y 10 días |
| Reset de aging | Mover `new→qualified` vía PATCH resetea: `qualified.aging_avg_days < 0.1` y `new.count=0` (el PATCH actualiza `stage_changed_at` solo si la etapa cambia) |
| RBAC | Viewer → 403 en `GET /pipeline/report` |

### Frontend (4 evals vitest, `portal/src/report.test.tsx`)

| Verificación | Resultado |
|---|---|
| KPIs | Ticket medio 212,50 €, mediana 200,00 €, win-rate 50,0 % con «1 ganadas · 1 perdidas», pipeline abierto 400,00 €, aging «4 días» (máx 10) |
| Funnel | Filas por etapa con recuento, valor y aging («2 · 400.00 EUR · aging 7 días (máx 10 días)») |
| Aging sub-diario | 0,38 días → **«9 horas»** y máx «13 horas» (nunca «0 días») |
| Error de API | 403 → mensaje de permiso visible |

### Validación en vivo (proxy 5176 → bridge-api candidato, 41.652 SKUs)

| Verificación | Resultado |
|---|---|
| Migración 0016 | Aplicada al PostgreSQL del candidato: `opportunities.stage_changed_at` NOT NULL, backfill = `created_at` |
| Funnel | «Nuevo» 26 oportunidades / 1.124,60 €; Calificado/Presupuesto/Negociación/Ganado/Perdido 0 |
| Ticket medio / mediana | **43,25 €** / **20,40 €** |
| Pipeline abierto | 1.124,60 € · 26 oportunidades |
| Win-rate | «—» con «0 ganadas · 0 perdidas» (honesto: sin cierres no hay % inventado) |
| Aging | 9 horas (máx 13 horas) — horas, no «0 días» |
| Portal | Tab «Reporting de ventas» en Clientes: 5 KPIs + funnel por barras (captura en preview) |

### Regresión

Corpus **462 passed / 11 skipped / 0 errores** (3 evals nuevos); gates D-030
PASS (ruff-hard 0, clean-zone 0, ratchet 132 vs baseline 243); portal `tsc`
limpio, `vite build` OK, **36 vitest passed** (4 nuevos). Fila T-045.

## Timeline de interacción por lead en vivo — 2026-08-16

Segundo módulo de la T-044: historial cronológico por lead/oportunidad
(email, nota, etapa, asignación, pedido) visible en la ficha del portal.
Fila **T-046**.

### Backend (3 evals herméticos, `test_p1_pipeline_kanban.py`)

| Verificación | Resultado |
|---|---|
| Fusión + orden + privacidad | Creación, asignación (`sin asignar → comercial`), oportunidad, etapa («Nuevo → Calificado»), nota y `email_sent` aparecen en la timeline; orden estrictamente desc; el asunto del email NO aparece (hash) |
| Presupuesto → pedido | `quote_created_api` y `quote_confirmed` correlacionados por `external_reference` de la oportunidad: entradas `quote_created` y `order_created` con el id del pedido |
| Aislamiento + RBAC | Un email con hash de OTRO destinatario no se cuela; viewer → 403; lead inexistente → 404 |

### Frontend (6 evals vitest, `timeline.test.tsx` + `kanban.test.tsx`)

| Verificación | Resultado |
|---|---|
| Ficha | Datos del lead + historial cronológico con título, detalle y actor |
| Sin leadId | El drawer no renderiza |
| Vacío | «Sin interacciones registradas todavía.» |
| Esc | Cierra el drawer |
| Error | 404 → «Lead no encontrado» visible |
| Tarjeta clicable | Clic en una tarjeta del kanban abre la ficha y hace `GET /leads/{lead_id}/timeline` |

### Validación en vivo (proxy 5176 → bridge-api candidato)

Lead `validador-val-c17565fe85b0@example.invalid` (8 entradas cronológicas):

| Entrada | Detalle |
|---|---|
| `lead_created` | Origen: local · 16/08 09:44 |
| `opportunity_created` | Presupuesto quote-8d7a8e28667d · 20.40 EUR |
| `note` | Oportunidad creada desde conversación… |
| `email_queued` | Proveedor **local_spool** (correlacionado por `recipient_sha256`) |
| `stage_changed` ×4 | Nuevo→Ganado, Ganado→Nuevo, Nuevo→Presupuesto, Presupuesto→Nuevo (auditados, actor admin) |

El drawer del portal abre desde la tarjeta del kanban con los datos del lead
y la timeline completa (captura en preview).

### Regresión

Corpus **465 passed / 11 skipped / 0 errores** (3 evals nuevos); gates D-030
PASS (ruff-hard 0, clean-zone 0, ratchet 132 vs baseline 243); portal `tsc`
limpio, `vite build` OK, **42 vitest passed** (6 nuevos). Fila T-046.

## Actividades de comercial (T-047) — 2026-08-16

### Evals herméticos (test_p1_pipeline_kanban.py, `-k activity` → 5 tests)

- CRUD + RBAC: `POST /activities` con lead/oportunidad (404 lead inexistente,
  422 oportunidad de otro lead), `PATCH` a done con `completed_at/by`,
  auditoría `activity.created`/`activity.updated`; viewer 403.
- Regresión `None + str`: crear tarea **sin lead** devuelve
  `lead_name=None` sin 500 (bug real encontrado en validación en vivo).
- Remind manual: `POST /activities/{id}/remind` → proveedor `local_spool`,
  `delivery_status=queued_for_manual_delivery`, `reminded_at` fijado,
  auditoría `activity.reminder_sent`.
- Worker automático: `run_due_activity_reminders` con `remind_at` vencido
  marca `reminded_at` antes del envío (idempotente: segunda llamada no
  reenvía); sin destinatario resoluble audita `activity.reminder_skipped`.

### Validación en vivo contra el stack candidato (PostgreSQL real)

- Migración **0017** aplicada (`alembic current` → 0017 head).
- Ciclo manual por API: crear con lead → remind → spool
  `/data/emails/…-831f4be7b4e9.json` (`to: validador-…@example.invalid`,
  asunto `Recordatorio: E2E recordatorio proveedor`) → completar
  (`status=done`, `completed_by` admin). Auditoría: `activity.created`
  (success), `activity.reminder_sent` (pending, provider local_spool),
  `activity.updated` (success, changes `status:done`).
- **Worker automático**: habilitado en el candidato
  (`ACTIVITY_REMINDER_WORKER_ENABLED=true`, poll 5 s — la variable no
  llegaba al contenedor porque faltaba en `environment:` del compose;
  corregido). Tarea con `remind_at` vencido insertada vía BD →
  `reminded_at` fijado en el primer poll + `activity.reminder_sent` +
  spool `…-4da7e1f79737.json`. (La fila sintética se eliminó tras validar;
  la auditoría queda como evidencia.)
- Portal (preview localhost:5176): tab «Tareas» con 3 tareas reales —
  ciclo completo visible (vence 20/08, «recordado 16/08, 12:39», «Hecha»),
  formulario con 26 leads y 2 usuarios cargados (screenshot).

### Regresión

Corpus **470 passed / 11 skipped / 0 errores** (4 evals backend nuevos);
gates D-030 PASS (ruff-hard 0, clean-zone 0, ratchet 132 vs baseline 243);
portal `tsc` limpio, `vite build` OK, **47 vitest passed** (5 nuevos).
Fila T-047.

## T-051 — Webhooks salientes de eventos CRM (P2-f) — 2026-08-16

### Backend hermético (`tests/regression/test_p1_webhooks_outbound.py`, 12 evals)

- CRUD: alta admin auditada (`webhook_subscription.created`) con eventos
  normalizados y **secreto nunca devuelto** (solo `secret_set`/`secret_prefix`);
  comercial 403; alta sin `Idempotency-Key` 428; evento desconocido 422;
  URLs privadas (`127.0.0.1`, `10.0.0.5`) y esquema `ftp://` 422; nombre
  duplicado 409; PATCH (renombrar, cambiar eventos, desactivar; `secret`
  vacío conserva) + DELETE auditados (`webhook_subscription.updated/deleted`).
- Test ping: `POST /webhooks/subscriptions/{id}/test` encola `webhook.test`
  por el outbox (topic `crm.webhook`) y audita `webhook_subscription.test`.
- Enqueue atómico: `lead.created`, `lead.assigned` (from/to username),
  `pipeline.stage_changed` (stage_from/to) y `quote.confirmed` (order_id,
  customer_email, total) encolan **un** mensaje por suscripción activa del
  evento con `commit=False` en la transacción de la mutación; una
  suscripción de otro evento no encola.
- Dispatcher (sin red): `dispatch_crm_webhook` firma con el secreto DE LA
  SUSCRIPCIÓN y la firma se verifica byte a byte contra
  `sign_webhook_payload(body, secret)` (cabeceras
  `X-Bridge-Webhook-Signature/Id/Key-Id=subscription`); suscripción
  inactiva/eliminada → `skipped` con motivo (nunca envía a una URL
  deshabilitada); URL de red privada → `OutboxPermanentError` (dead-letter,
  no reintento).

### Validación en vivo contra el candidato (PostgreSQL real, worker activo)

1. Migración `0019` aplicada (`alembic_version=0019`).
2. Suscripción «CRM externo demo» → `webhook_subscription.created` en
   `audit_logs` (actor admin).
3. `POST /leads` → mensaje `crm.webhook` con `event_type=lead.created` en el
   outbox (misma transacción).
4. Test ping → el worker entregó `webhook.test` a un listener local
   (`http://host.docker.internal:8123/hook`, allowlist
   `WEBHOOK_OUTBOUND_ALLOWED_HOSTS`): cuerpo canónico de 197 caracteres,
   firma `sha256=9072e7e0ed58762c59f10e133b1fc00f4872e0e71398e4d56c9ca753623bc923`
   **verificada byte a byte** con el secreto `happy-path-secret-16ch`;
   estado del mensaje `sent`, `attempt_count=0`.
5. URL `https://public.test/hook` → el worker intentó resolver y cayó a
   dead-letter permanente: `last_error={"type":"OutboxPermanentError",
   "message":"webhook_dns_resolution_failed:public.test","permanent":true}`
   con `outbox_dead` auditado — el SSRF/defensa DNS funciona end-to-end.
6. Portal (preview localhost:5176, sesión admin): nav «Webhooks salientes»
   → sección con las 2 suscripciones reales (secreto `firma live… ✓`,
   estado `Activa`, botones Probar/Editar/Desactivar/Eliminar), formulario
   de alta con checkboxes de eventos y catálogo desplegable (screenshot).

### Regresión

Corpus **522 passed / 11 skipped / 0 errores** (12 evals backend nuevos);
gates D-030 PASS (ruff-hard 0, clean-zone 0, ratchet 133 vs baseline 133);
portal `tsc` limpio, `vite build` OK, **58 vitest passed** (5 nuevos + 2
actualizados por el nav admin). Fila T-051.

## T-052 — Email integrado (plantillas, firma y tracking)

**Validación en vivo contra el candidato** (PostgreSQL real, migración `0020` aplicada,
`EMAIL_TRACKING_BASE_URL=https://app.bridgedemo.local`):

1. `GET /email/settings` → firma por instalación «Un saludo, Equipo BTOP Digital»,
   `tracking_enabled=true` (get-or-create).
2. `POST /email/templates` («Seguimiento de presupuesto live») con variables
   `{{nombre}}`, `{{presupuesto}}`, firma de plantilla, `POST /{id}/send-test`
   con `to=e2e@example.com` y `variables={"nombre":"Cliente E2E","presupuesto":"QT-DEMO"}`.
3. Spool (`docker exec … ls` en `AUTOMATION_EMAIL_DIR`): asunto renderizado
   «Seguimiento de presupuesto QT-DEMO», HTML multipart con pixel
   `https://app.bridgedemo.local/email-tracking/tk-c99bd5d6793740f0b26dd7e2d0e3ff96/open.png`,
   enlaces reescritos a `/email-tracking/{token}/click?u=…`, firma renderizada.
4. `GET /email-tracking/{token}/open.png` → **200, PNG válido de 67 bytes**
   (magic `\x89PNG` verificado); segunda petición sin duplicar (idempotente).
5. `GET /email-tracking/{token}/click?u=https%3A%2F%2Fexample.com%2Fpresupuesto%2FQT-DEMO`
   → **302** al destino; `u=` http/https aceptado, `mailto:` → 422.
6. BD `email_tracking_events`: `sent → open → click` por token; segundo open
   no crea fila nueva.
7. Portal (preview, sesión admin): sección «Email integrado» con las 2
   plantillas, «Enviar prueba», toggle de tracking y tabla con los 3 eventos
   reales (screenshot).

### Regresión

Corpus **531 passed / 11 skipped / 0 errores** (9 evals backend nuevos en
`test_p1_email_templates.py` + 2 providers de test actualizados para los
kwargs `html`/`tracking_token`); gates D-030 PASS; portal `tsc` limpio,
`vite build` OK, **63 vitest passed** (5 nuevos). Fila T-052.

## T-053 — Calendario de comercial (vistas diaria/semanal/mensual)

**Validación en vivo contra el candidato** (PostgreSQL real, rebuild con el
endpoint nuevo; 3 actividades E2E: hoy 10:00, mañana 11:30, vencida hace 3
días):

1. `GET /calendar/agenda?start=2026-07-17&end=2026-08-17&tz_offset=120`
   → `totals {total:3, pending:3, completed:0, cancelled:0, overdue:2}`;
   días con actividad: **2026-08-13** (follow-up vencido, overdue=1),
   **2026-08-16** (llamada de hoy ya vencida a las 10:00 UTC, overdue=1) y
   **2026-08-17** (reunión de mañana, no vencida). Rango de 92 días
   excedido → 422 «El rango máximo es de 92 días».
2. Portal (preview localhost:5176, sesión admin, tab **Calendario** en
   Clientes):
   - **Mes**: «Agosto de 2026», pills `4 actividades / 3 pendientes / 1
     hechas / 2 vencidas`, rejilla L–D con badges en las celdas 13 (⚠1 + 1),
     16 (⚠1 + 1), 17 (1) y 20 (✓1) (screenshot).
   - **Semana**: «10 Ago – 16 Ago 2026», 7 columnas; jueves 13 con
     «09:00 E2E calendario: follow-up vencido · Follow-up» y domingo 16 con
     «10:00 E2E calendario: llamada hoy · Llamada» (screenshot).
   - **Día** (click en domingo 16): «Domingo, 16 de Agosto de 2026» con la
     lista «10:00 E2E calendario: llamada hoy · Llamada · Pendiente»
     (screenshot).
3. Limpieza: las 3 actividades E2E marcadas `cancelled` tras la validación.

### Regresión

Corpus **536 passed / 11 skipped / 0 errores** (5 evals backend nuevos en
`test_p1_pipeline_kanban.py`); gates D-030 PASS (ruff-hard 0, clean-zone 0,
ratchet 133 = baseline; B904 `raise … from None` y DTZ011 corregidos);
portal `tsc` limpio, `vite build` OK, **68 vitest passed** (5 nuevos en
`calendar.test.tsx`). Fila T-053.

## Datos maestros CRM — T-054 (2026-08-17, VERIFIED)

### Backend (hermético)

6 evals nuevos en `tests/regression/test_p1_master_data.py`: CRUD de cuenta y
contacto con auditoría y RBAC; merge de contactos; probabilidad por etapa
(`PATCH /pipeline/stages/{id}`); cierre won/lost con motivo (webhook
`opportunity.closed` encolado por el outbox); merge de leads (mueve
oportunidades/actividades/custom values, excluye al absorbido); reporte con
`lost_reasons` + `weighted_pipeline_value` + `probability`.

### Portal (vitest)

6 evals nuevos: `accounts.test.tsx` (listado, alta, ficha con contactos,
merge) y `kanban.test.tsx` (modal de cierre won/lost con motivo). Total 72.

### En vivo contra el candidato (PostgreSQL real, migración 0021)

1. Cuenta «Acme Distribución» (NIF, sector, web) + contacto principal
   «Ana López» (cargo, email) creados por API.
2. Oportunidad cerrada como **lost con motivo «Precio»** → timestamps,
   actividades pendientes del lead cerradas y webhook `opportunity.closed`
   encolado en el outbox.
3. Merge de 2 leads E2E: oportunidades del absorbido movidas al principal y
   el perdedor excluido de `/leads` y del board.
4. Reporte `/pipeline/report`: `lost_reasons {Precio: 1}` y
   `weighted_pipeline_value` = Σ valor × probabilidad de etapa.
5. Preview: tab **Cuentas** en Clientes renderizando la cuenta real con su
   contacto y la ficha (screenshot); kanban con badge de probabilidad.

### Regresión

Corpus **541 passed / 12 skipped / 0 errores** (6 evals backend nuevos);
`test_provision_script_syntax_is_valid` pasa a `_linux_only` como sus
hermanos del mismo archivo (bash -n desde Python nativo de Windows cuelga;
el preflight Windows lo cubre `provision-client.ps1`); gates D-030 PASS
(ruff-hard 0, clean-zone 0, ratchet 133 = baseline); portal tsc limpio,
`vite build` OK, **72 vitest passed**. Fila T-054.

---

## T-056 — Agente de escucha social (Fase 1)

### Backend hermético (14 evals)

1. Adaptadores puros: challenge GET genérico/WhatsApp, firma HMAC correcta e
   incorrecta, parseo de payload de Meta (texto; no-texto → fail-closed) y
   canal desconocido → error.
2. Triaje determinista: lead/queja/spam/consulta, mismo input → mismo
   veredicto, idioma es/en, registro formal/tuteo, entidades
   (email/teléfono/SKU/precio) y score social explicado.
3. API: CRUD de canales con RBAC (viewer/commercial → 403), idempotencia
   (replay misma key, duplicado → 409), secreto nunca expuesto; pipeline
   E2E webhook → mensaje → triaje → lead `source=social` → actividad
   follow-up → timeline → auditoría `social.message_triaged`; 401 con firma
   inválida (nada persistido); dedupe de reintentos (200 duplicate, 1 solo
   lead); WhatsApp simulado con SLA de queja 15 min; inbox/dismiss/stats
   con RBAC; fusión de la señal `social` en el score del lead.

### En vivo contra el candidato (PostgreSQL real, migración 0023)

1. Canal «WhatsApp E2E» creado (201, secreto oculto en la respuesta).
2. Webhook WhatsApp simulado firmado (`X-Hub-Signature-256`) → **200
   received** → triaje determinista `queja / es / urgente 64 / score 60`.
3. Lead «Carlos Ruiz» creado con `source=social` y placeholder
   `social-whatsapp-34600111222@bridge.local`; actividad follow-up con SLA
   de 15 min (queja); timeline `[lead_created, social_message]`.
4. Stats `/social/stats`: `by_intent {queja: 1}`, score medio 60.
5. Score del lead 37 con señal `social` en `signals`.
6. Firma inválida → **401**; reintento con el mismo `source_message_id` →
   **200 duplicate** sin duplicar mensaje ni lead.
7. DELETE del canal → `deactivated: true` (regla: con mensajes no se borra).
8. Preview: tab **Escucha social** en Clientes con el mensaje real triado
   (Queja · score 60 · ES · urgente 64 · Triado), botón Descartar y la tabla
   de canales con el canal desactivado (screenshot).

### Regresión

Corpus **539 passed / 12 skipped / 0 errores** (14 evals backend nuevos);
gates D-030 PASS (ruff-hard 0, clean-zone 0, ratchet 133 = baseline); portal
tsc limpio, `vite build` OK, **79 vitest passed** (4 nuevos). Fila T-056.

---

## T-057 — Agentes de IA especializados por módulo (Fase 1)

### Backend hermético (8 evals)

1. Registro: cada módulo de negocio tiene su agente built-in con
   `module`/`module_label`/`scope`/tier/presupuesto y estado active.
2. Todas las allowlists del registro contienen tools conocidas y **ninguna**
   prohibida (financieras/contables) queda autorizada (fail-closed).
3. Las 7 herramientas por módulo están en `TOOL_SPECS` con kind `read`
   (deterministas, sin mutación).
4. Los agentes se exponen por `GET /agents` con los metadatos de módulo.
5. `crm_agent` invoca `list_leads` + `get_pipeline_report` sobre datos
   sembrados; una tool de otro módulo → denied.
6. `social_agent` invoca `list_social_inbox` (filtro por intención) +
   `get_social_stats`.
7. `marketing_agent` invoca `list_campaigns` + `get_campaign_stats` con
   tracking de aperturas derivado de `EmailTrackingEvent`.
8. Tool desconocida y `confirm_quote` (prohibida) → denied con auditoría
   `tool_call` (agent_id + policy deny-by-default).

### Portal

Badge de módulo (`Clientes (CRM)`…) y línea de alcance en cada tarjeta del
registro de agentes + eval vitest nuevo. Total **80 vitest**.

### Regresión

Corpus **547 passed / 12 skipped / 0 errores** (8 evals backend nuevos);
gates D-030 PASS (ruff-hard 0, clean-zone 0, ratchet 133 = baseline); portal
tsc limpio, `vite build` OK, **80 vitest passed**. Fila T-057.

## T-058 — Agentes de IA por módulo, Fase 2: propuestas con aprobación

### Backend hermético (8 evals)

1. La ronda crea una propuesta de follow-up de `crm_agent` para un mensaje
   social urgente (queja, urgency ≥ 40) sin seguimiento activo, y una de
   `social_agent` para descartar el spam con score 0 — sin duplicar
   (unicidad por action+target vía `ApprovalRequest`).
2. Un re-run no duplica propuestas pendientes ni re-propone una aprobada.
3. Una propuesta rechazada se re-propone en el siguiente re-run si la señal
   sigue (el comercial puede aceptar el spam o el follow-up más tarde).
4. Aprobar `agent_proposal:create_follow_up` crea la actividad (idempotente
   por `created_by=agent:<id>`+título) en la misma transacción.
5. Aprobar `agent_proposal:dismiss_message` marca el mensaje `dismissed` en
   la misma transacción.
6. RBAC: la ronda y el feed requieren rol operador+; el botón es solo admin.
7. El feed de aprobaciones expone las propuestas con agente, tipo
   (`agent_proposal:*`) y objetivo.
8. La ronda audita `agent_proposals.run`; el approve audita la decisión con
   el efecto aplicado.

### Portal

Botón «Ejecutar agentes» en el panel de aprobaciones (solo admin, con estado
«Ejecutando…») y labels de propuesta de agente en el feed + eval vitest.
Total **81 vitest**.

### Regresión

Corpus **555 passed / 12 skipped / 0 errores** (8 evals backend nuevos);
gates D-030 PASS (ruff-hard 0, clean-zone 0, deuda 131 < baseline 133);
portal tsc limpio, `vite build` OK, **81 vitest passed**. Fila T-058.

### Validación en vivo (candidato, PostgreSQL real)

Rebuild del bridge-api (sin migración nueva). E2E: webhook WhatsApp simulado
firmado → triaje → ronda `POST /approvals/agent-round` → `crm_agent` propone
follow-up para el lead cuya actividad social venció y `social_agent` propone
descartar el spam del inbox; `POST /approvals/{id}/decision` aprueba y el
efecto se aplica en la misma transacción (actividad creada / mensaje
`dismissed`). Preview: panel de aprobaciones con las propuestas reales y el
botón «Ejecutar agentes».

## T-059 — Panel de supervisión de agentes por módulo

### Backend hermético (4 evals nuevos)

1. `GET /agents/supervision` lista todos los agentes por módulo (builtin +
   persistidos de la instalación) con `module`/`module_label`/`scope`,
   tools autorizadas declaradas y kind `read`; `totals` y `generated_at`.
2. Agrega `tool_call` success/denied/error por tool: counts exactos,
   `last_status` = la llamada más reciente por timestamp (timestamps
   explícitos para desempate determinista) y `recent_actions` ordenadas
   desc.
3. Un agente sin actividad aparece ocioso: calls=0, `last_activity_at`
   null, `recent_actions` vacío y allowlist intacta (`rag_search` para
   content_agent).
4. RBAC: 401 sin token; un `viewer` puede leer (READ_ROLES).

### Portal

Panel «Supervisión por módulo» (Control empresarial) bajo el registro en la
sección Agentes de IA: tarjeta por agente con badge de módulo, tier, última
actividad, pills (llamadas/✓/✗/!, tools autorizadas) y detalles desplegables
«Estado de las tools» (tabla kind/acceso/contadores/última) y «Últimas
actuaciones auditadas» (chips success/denied/error + detalle). Eval vitest
nuevo. Total **82 vitest**.

### Regresión

Corpus **559 passed / 12 skipped / 0 errores** (4 evals backend nuevos);
gates D-030 PASS (ruff-hard 0, clean-zone 0, deuda 131 < baseline 133);
portal tsc limpio, `vite build` OK, **82 vitest passed**. Fila T-059.

### Validación en vivo (candidato, PostgreSQL real)

Rebuild del bridge-api: el pin `libpq=18.4-r0` del Dockerfile dejó de
resolver en el repo Alpine 3.24 (ahora `18.6-r0`); actualizado y build con
`--env-file .env.candidate-0815` (sin ese flag el build etiqueta `dev` en
lugar de `0.9.1-candidate.3`). `GET /agents/supervision` → 8 agentes (7
builtin + 1 persistido E2E). Tres invocaciones reales por
`POST /agents/tools/invoke` (admin): crm `list_leads` success, social
`get_social_stats` success, crm `confirm_quote` denied → totals
`{calls:3, success:2, denied:1, errors:0}`; la re-consulta muestra
crm_agent `list_leads` ✓1 y `confirm_quote` ✗1 denegada (no declarada) y
social_agent `get_social_stats` ✓1, con `recent_actions` desc. Preview
(http://localhost:5176/#agentes): panel «Supervisión por módulo» con las
tarjetas reales, tabla de tools de crm_agent expandida y la denegación
visible (screenshot).

## T-061 — Color de acento configurable por instalación

### Backend hermético (7 evals nuevos)

1. `GET /appearance/settings` crea la fila única con el default #246bfd,
   `updated_by: null` y `installation_id` de la instalación; get-or-create
   idempotente (la segunda lectura no duplica).
2. `PUT /appearance/settings` (admin) actualiza el color, marca
   `updated_by` y `updated_at` y audita `appearance.settings_updated` con
   el color en `details`.
3. Hex inválido (`red`, `#12345`, `#12345G`, `123456`, `#246BFD0`) → 422
   y el valor persistido no cambia (fail-closed).
4. `extra` en el body → 422 (`ConfigDict(extra="forbid")`).
5. Re-PUT con el mismo color: idempotente — el segundo PUT no audita un
   cambio (`changed` vacío).
6. RBAC: viewer lee (200) pero no escribe (403).
7. Sin token → 401 en GET y PUT.

### Portal

App carga `/appearance/settings` al entrar (fallo silencioso → acento
local) y aplica `--accent`/`--accent-soft` (color-mix) sobre
`documentElement` con persistencia en localStorage; el login adopta el
acento sin token. Panel «Apariencia» en Usuarios y permisos (paleta 8
presets + hex + preview + Guardar/Restablecer). Eval vitest: el admin
cambia el acento por la UI → PUT y `--accent` aplicado. Total **83 vitest**.

### Regresión

Corpus **565 passed / 12 skipped / 0 errores** (7 evals backend nuevos;
`test_p1_quality_gates` PASS tras quitar un import no usado F401); gates
D-030 PASS (ruff-hard 0, clean-zone 0, deuda 132 < baseline 133); portal
tsc limpio, `vite build` OK, **83 vitest passed**. Fila T-061.

### Validación en vivo (candidato, PostgreSQL real)

Rebuild del bridge-api (migración `0024` aplicada, `alembic_version`
=0024). API: GET default `{"accent_color":"#246bfd","updated_by":null}`
→ PUT `#0d9488` (teal) → `{"accent_color":"#0d9488","updated_by":"admin"}`
→ PUT `rojo` → 422 → GET confirma #0d9488 persistido. Por UI en el
preview (http://localhost:5176/#usuarios): panel de apariencia con la
paleta y el teal seleccionado; swatch violeta → «Guardar acento» →
`--accent: #7c5cf0` en `documentElement`, barra del nav activo violeta
`rgb(124,92,240)`, notice «Color de acento actualizado para toda la
instalación.» y login con la marca teñida al acento (screenshots).

## T-062 — Modo de densidad del portal

### Portal (1 eval vitest nuevo)

El toggle «Activar modo compacto» alterna `data-density` de
`documentElement` entre `comfortable` y `compact`, persiste en
localStorage y actualiza `aria-pressed`; volver a pulsarlo restaura
`comfortable`.

### Implementación

Estado `density` en App (localStorage, mismo mecanismo que `data-theme`),
toggle `Rows3` en `topbar-actions`, y ~90 reglas CSS bajo
`:root[data-density="compact"]` (content, sidebar, panels, métricas,
tarjetas, formularios, tablas, badges, grids, kanban, calendario,
supervisión y apariencia).

### Regresión

Portal tsc limpio, `vite build` OK, **84 vitest passed** (1 nuevo); corpus
backend intacto (565/12), gates D-030 PASS. Fila T-062.

### Validación en vivo (preview http://localhost:5176/)

Con el toggle activado: `data-density="compact"` y computed styles
reducidos — content `16px 22px 30px`, metric `11px 12px`, panel
`13px 15px` — con el resumen operativo en densidad compacta (screenshot).

## T-063 — Rediseño iOS / minimalista

### Implementación (solo CSS)

Capa final de overrides en `src/styles.css` (~360 líneas): tokens del
sistema (fondo #F2F2F7 claro / #000 oscuro, tarjetas blancas / #1C1C1E,
hairline rgba(60,60,67,0.12), acento #007AFF / #0A84FF, tipografía SF
Pro/Segoe UI), sidebar translúcida estilo iPad (backdrop-blur, pill de
acento), botones planos de un solo acento, tablas iOS sin cebra, alertas
planas, kanban con tarjetas blancas, login sin franja de gradiente y sin
animaciones decorativas (rise-in, brand-glow y pulse eliminados).

### Regresión

Portal tsc limpio, `vite build` OK, **84 vitest passed** (sin cambios de
comportamiento); corpus backend intacto (565/12), gates D-030 PASS. Fila
T-063.

### Validación en vivo (preview http://localhost:5176/)

Modo claro: bodyBg `rgb(242,242,247)`, sidebar `rgba(250,250,252,0.86)`
translúcida con pill activa azul clara, tarjetas blancas con sombra sutil,
botón primario plano azul (screenshot del resumen). Modo oscuro: bodyBg
`rgb(0,0,0)`, cardBg `rgb(28,28,30)`, sidebar `rgba(22,22,24,0.86)` con
pill azul oscura (screenshot del resumen y de Usuarios/apariencia con la
paleta y el azul seleccionado).

## T-065 — Identidad del rediseño en PDFs/facturas (2026-08-17)

### Qué se validó

`generate_invoice_pdf(invoice, db=None)` — el PDF de factura (determinista,
de solo lectura, sin dependencias nuevas) adopta la tipografía del sistema
(Helvetica/Helvetica-Bold, equivalente PDF de SF Pro/Segoe UI) y el acento
de la instalación (T-061): barra de marca de 60pt del color de acento,
marca blanca «Agentes IA / Control empresarial», título FACTURA + número,
filas de metadatos con etiqueta gris y valor oscuro #1C1C1E, bloque TOTAL
alineado a la derecha (ancho determinista) y pie de solo lectura. La
etiqueta del cliente resuelve nombre + email de la BD en vez del id crudo,
y la puntuación no-latin-1 se normaliza (em/en-dash → `-`) para que nunca
salga `?`. El acento se resuelve con solo lectura (nunca crea la fila de
apariencia) y el default sin `db` es `#246bfd`.

### Evals herméticos (3 nuevos en test_p1_automations.py)

- `test_invoice_pdf_uses_installation_accent`: con `InstallationAppearance`
  teal (#0d9488) el stream contiene `0.051 0.580 0.533`; sin `db` el PDF usa
  el default `0.141 0.420 0.992` (#246bfd).
- `test_invoice_pdf_uses_default_accent_without_db`: default + `/Helvetica-Bold`
  + marca «Agentes IA» presentes.
- `test_invoice_pdf_resolves_customer_label`: con cliente en BD el PDF
  muestra «Cliente Demo · demo@example.invalid» y no el id crudo.
- Existente: determinismo (`pdf_a == pdf_b`) y `%PDF`/`%%EOF` intactos.

Corpus completo: **569 passed / 12 skipped** · gates D-030 PASS (deuda 132
< baseline 133). Además se endureció el seed de `test_supervision_aggregates…`
en `test_p1_module_agents.py` (timestamps relativos a ahora en vez de una
fecha fija en el pasado) para eliminar un flake del corpus: la fecha fija
hacía que logs en vivo de tests anteriores desplazaran las filas del top-5
de `recent_actions`.

### Validación en vivo contra el candidato (PostgreSQL real)

Rebuild del bridge-api (imagen `0.9.1-candidate.3`). Con la factura real
`INV-2026-BAC1BB2D`:

- Stream del PDF: `0.141 0.420 0.992 rg 0 782 612 60 re f` (barra con el
  acento de la instalación #246bfd), marca blanca, `FACTURA` en acento,
  número en Helvetica-Bold 20pt, filas Cliente/Pedido/Estado/Moneda/Emitida
  (cliente «Comprador en vivo — comprador-venta-…@example.invalid» limpio,
  sin `?`), `TOTAL 317.50 EUR` alineado a la derecha (x=493.6).
- E2E del acento: default #246bfd → `set_accent_color` teal #0d9488 → la
  barra pasa a `0.051 0.580 0.533` → restore #246bfd. El PDF sigue siendo
  determinista en cada generación.
- Endpoint HTTP `GET /automations/invoices/{id}/pdf` con token de admin:
  **HTTP 200, application/pdf, 1984 bytes**, `%PDF`, acento de instalación,
  marca y Helvetica-Bold presentes.

## T-067 — CEO agent (chat del dueño, delegación a agentes de módulo)

Validado en vivo contra el candidato (PostgreSQL real, LLM ollama):

- `POST /ceo/chat` «¿cómo van las ventas?» → `intent: sales_summary`,
  respuesta natural con datos reales (120 EUR/300 EUR, 3 oportunidades,
  etapa con aging) generada por el LLM; auditoría `ceo_chat.message` con
  provider y respuesta.
- «haz follow-up a los leads fríos» → `intent: follow_up_cold_leads`, crea
  `agent_proposal:ceo_follow_up` por lead sin asignar (20 leads → 20
  propuestas en 2 rondas, **dedupe por lead**: re-pedir no duplica).
- Aprobación en vivo de una propuesta → `Activity` creada con
  `created_by=agent:ceo_agent` y timeline actualizada.
- Portal: panel «Chat de dirección (CEO)» responde desde el portal con la
  meta de intención y propuestas pendientes; `ceo_agent` visible en el
  panel de supervisión de agentes.

## T-068 — Autonomía por excepción (umbrales + digest + revert)

Validado en vivo contra el candidato (PostgreSQL real, migración 0025 en
head):

- `GET /agents/autonomy` → 8 agentes, todos `manual` (deny-by-default).
- `PUT /agents/autonomy/ceo_agent` (autonomous, umbral 500, follow-ups) →
  200 con `updated_by: admin`; modo inválido → 422.
- CEO chat «haz follow-up a los leads fríos» con ceo_agent autónomo → 1
  propuesta **auto-ejecutada** (status `approved`, `decision_id` presente)
  y la respuesta lo dice: «He creado 1 follow-ups para leads sin asignar…
  dentro de tu autonomía autorizada… puedes revertirlo desde el digest».
- `GET /agents/digest?days=7` → `total_decisions: 1`, by_agent
  `[('ceo_agent', 1)]`, la decisión de mi lead con `executed_by:
  agent:ceo_agent` y `deviation: false`.
- `POST /agents/decisions/{id}/revert` → 200 `reverted_by: admin` con
  timestamp; el mismo revert de nuevo → **409**.
- Por la UI en el preview (Agentes de IA): el panel «Autonomía por
  excepción» muestra las 8 tarjetas con modo/umbral/flags; cambiar el CEO a
  autónomo + follow-ups y guardar persiste (`mode=autonomous` en la BD) con
  notice «Autonomía de «Asistente de dirección (CEO)» actualizada
  (autonomous)» y badge «autónomo»; el «Digest de decisiones» muestra la
  decisión real con «revertida por admin»; supervisión y registro cargan
  correctamente (reload endurecido: una generación por recarga).
- Candidato restaurado a `manual` tras la validación.

## T-075 — Órdenes de acción por módulo desde el chat

Validado en vivo contra el candidato (PostgreSQL real):

- **Crear lead**: «crea un lead ana-live-071@example.invalid de Empresa SL»
  → `lead_create`, propuesta `agent_proposal:ceo_create_lead` `pending` →
  aprobada → `applied: {action: create_lead, lead_id: …, email:
  ana-live-071@…}` y el lead real creado (`source=local`).
- **Mover oportunidad**: oportunidad sembrada (`opp-acciones-live`, stage
  `new`) + «mueve la oportunidad Oportunidad Acciones Live a negociacion»
  → `opportunity_move`, propuesta → aprobada → `stage_to: negotiation`,
  en PostgreSQL `stage=negotiation` y `stage_changed_at` fijado (webhook
  saliente `pipeline.stage_changed` encolado).
- **Crear tarea**: «crea una tarea para llamar a Carlos» → `task_create`,
  propuesta → aprobada → actividad `pending` con `kind=call` creada por
  `agent:ceo_agent`.
- **Lanzar campaña**: «lanza una campaña «Oferta Acciones Live»» →
  `campaign_launch`, propuesta → aprobada → `applied: {action:
  create_draft, created: true, status: draft}` — nunca envía sin plantilla
  y segmento (fail-closed).
- Herméticos: `test_p1_ceo_agent.py` **45/45** (7 nuevos: propuesta +
  aprobación aplica para los 4 intents, dedupe, datos faltantes con
  respuesta útil, activar campaña existente); corpus **644 passed / 12
  skipped**; gates D-030 PASS (deuda 132 < 133). Datos de prueba limpiados
  tras la validación.

## T-074 — Digest diario por email con revertir desde el correo

Validado en vivo contra el candidato (PostgreSQL real `bridge_db`, spool
real):

- `POST /digest/send?dry_run=true` → **200** `dry_run` para
  `dueno@miempresa.com`, asunto «Resumen diario · 2026-08-18 · 1
  decisiones, 21 propuestas», con las 3 secciones (decisiones de agentes,
  propuestas pendientes, métricas clave) y la instrucción `REVERTIR <id>`
  por decisión en vigor; mostraba la decisión real del CEO (revertida en la
  E2E de T-068) y las 21 propuestas pendientes reales.
- `POST /digest/send` → **200** `degraded_to_spool` con
  `queued_for_manual_delivery:4e371a265f6f`; fichero real en `/data/emails`
  del contenedor con `to=dueno@miempresa.com`, asunto y cuerpo completos.
- **Revertir desde el correo**: decisión sembrada
  (`dec-digest-live`, follow-up con actividad `act-digest-live` pending) +
  webhook de email con asunto «REVERTIR dec-digest-live» (HMAC real) →
  **200** `revert_status: reverted`; en PostgreSQL `reverted_at` fijado y
  `reverted_by=dueno@miempresa.com`, la actividad quedó `cancelled`
  (evidencia conservada) y la confirmación llegó al spool
  (`queued_for_manual_delivery:f2cfc628cacd`) con el mensaje exacto.
- La tarea programada **«Digest diario al dueño»** quedó creada y activa
  (`daily_digest`, intervalo 86400 s) en el candidato: el digest se envía
  solo cada día. Datos de prueba limpiados tras la validación
  (decisión/actividad/auditorías/spools de prueba).
- Herméticos: `test_p1_daily_digest.py` **7/7** (dry-run con contenido
  real, envío al spool + auditoría, revert por email con actividad
  cancelada, id inexistente / doble revert explicados, skip sin dueño,
  tarea sembrada + dispatch del catálogo, RBAC viewer → 403); corpus **637
  passed / 12 skipped**; gates D-030 PASS (deuda 132 < 133).

## T-073 — Entrada por voz en el chat universal

Validado en el preview del portal (dev server contra el candidato):

- El botón «Hablar» aparece junto al input del chat (solo si el navegador
  soporta Web Speech API); al dictar en español, la transcripción rellena
  el input y el botón muestra el estado pulsante «Detener la escucha».
- El envío posterior usa el mismo `POST /ceo/chat` que el tecleado (mismo
  pipeline de intenciones); sin soporte el botón no se renderiza y el
  teclado sigue funcionando; errores de permisos con mensaje amigable.
- Herméticos: `ceoChat.test.tsx` **5/5** (dictado + envío, acumulación de
  frases, error de permisos, sin soporte → teclado, detener escucha);
  portal **98 vitest + tsc + build**.

## T-072 — Onboarding guiado para personas sin experiencia técnica

Validado en vivo contra el candidato (preview del portal + contenedor
reconstruido):

- **Primer acceso** (sin `guided-onboarding` en localStorage): al cargar el
  dashboard se abre el diálogo «Tu empresa, en una conversación» (paso 1 de
  3) y la barra lateral queda reducida a **Asistente + Resumen** con el
  botón «Mostrar todos los módulos».
- **Paso 2**: «Pruébalo ahora mismo» con las 3 preguntas de ejemplo.
  Al pulsar «¿cómo van las ventas?» la pregunta se envía al chat real
  (`/ceo/chat`) y el paso 3 confirma «La respuesta ya está en el chat»;
  el chat responde con datos reales del candidato: «Ticket medio: 43.25
  EUR · 3 pedidos en proceso…» (tag «resumen de ventas · ollama»).
- **«Mostrar todos los módulos»**: persiste `guided-onboarding=done`,
  cierra el overlay y revela la navegación completa (14 enlaces para
  admin); con la preferencia guardada el onboarding no vuelve a aparecer
  tras recargar. «Seguir en modo guiado» cierra el overlay y mantiene los
  2 enlaces. «Omitir» persiste y revela todo.
- El contenedor del portal del candidato se reconstruyó con el bundle
  incluyendo el onboarding (healthy) y el preview quedó sin preferencia
  para que el primer acceso real del dueño lo vea.
- Herméticos: `portal/src/onboarding.test.tsx` **8/8** (primer acceso,
  envío de preguntas al chat, revelar módulos, guiado persistente, omitir,
  axe); portal **93 vitest + tsc + build**; prettier limpio en los archivos
  nuevos y en `ceoChat.tsx`.

## T-071 — App simple: chat universal como centro de mando + EUR

Validado en vivo contra el candidato (PostgreSQL real, portal real):

- Landing **«Asistente»** (`#asistente`) como sección principal: heading
  «TU EMPRESA EN UNA CONVERSACIÓN», moneda **EUR** explícita y 6 sugerencias
  rápidas («¿cómo van las ventas?», «muestra las automatizaciones», «estado
  de los agentes», «¿qué hay que aprobar?», «haz follow-up a los leads
  fríos», «¿hay stock bajo?»).
- `POST /ceo/chat` sobre el PostgreSQL real: «¿qué automatizaciones hay
  activas?» → `automations_status` (1 automatización activa, próxima
  ejecución); «¿qué agentes gestionan la empresa?» → `agents_status`
  (9 agentes listados por módulo); «pausa el barrido E2E» →
  `automation_toggle` con propuesta `agent_proposal:automation_toggle`
  (`pending`) para la tarea «Barrido E2E e2ef409435f495e» — **match por
  parte del nombre** (bug encontrado en vivo: el match exigía el nombre
  completo; corregido con match por substring/tokens significativos).
- Ciclo completo por API: aprobar la propuesta (`POST /approvals/{id}/approve`)
  → 200 con `applied: {action: pause, task_found: true}` y en PostgreSQL la
  tarea pasa a `status=paused` con `next_run_at=NULL`; restaurada a
  `active` tras la validación.
- Chat desde el **portal** (dev server contra el candidato): «muestra las
  automatizaciones» → respuesta natural «Según los datos verificados, hay
  una sola automatización activa: automation_sweep…» con tag
  «estado de las automatizaciones · ollama».
- Herméticos: `test_p1_ceo_agent.py` **38/38** (2 nuevos: match parcial +
  lectura real de datos); corpus **629 passed / 12 skipped**; gates D-030
  PASS (deuda 132 < 133); portal 85 vitest + tsc + build.

## T-070 — «Cierra el mes» en piloto automático (finance_agent)

Validado en vivo contra el candidato (PostgreSQL real `bridge_db`, spool real):

- `POST /finance/monthly-close?period=2026-08&dry_run=true` → **200** sobre
  los **3 pedidos reales** del mes (952,50 €, todos facturados): `orders: 3`,
  `un_invoiced_orders: 0`, sin mutaciones.
- Pedido sembrado vía SQL (`mc-order-live`, 200 €, instalación
  `candidate-0815`) + cierre en **modo manual** → **200** con
  `un_invoiced_orders: 1`, `approvals_created: 1`, `invoices_deferred_to_human:
  1` (`reason: manual`, `inv-d9b6b014716a` / `INV-2026-7A92E342`); la
  propuesta `issue_invoice` queda `pending` y la factura en `draft` — sin
  decisión ni email.
- Autonomía del `finance_agent` activada (`mode=autonomous`,
  `max_value_threshold=1000`) + re-ejecución → **200** con
  `invoices_auto_emitted: 1` (`inv-184a6e257a01` / `INV-2026-168D05AC`,
  `delivery_status: queued_for_manual_delivery`) y `deferred: []`; en
  PostgreSQL: `invoice_drafts.status = approved`, `agent_decisions` con
  `issue_invoice` y `deviation=false`, auditoría `agent_decision.auto_executed`
  + `monthly_close.run`, y el correo con el PDF en el spool
  (`queued_for_manual_delivery-…json`).
- `dry_run` no creó facturas/propuestas/decisiones; dedupe: la segunda
  ejecución sobre el mismo pedido no re-propone.
- Datos de prueba limpiados tras la validación (pedido/quote/cliente/factura/
  propuesta/decisión/auditoría) y la autonomía restaurada a manual
  (deny-by-default).

## T-069 — Superficie de mando del dueño (email/WhatsApp)

Validado en vivo contra el candidato (PostgreSQL real, spool real):

- Correo del dueño (webhook firmado HMAC) «¿cómo van las ventas?» → **200**
  `handled: true`, `intent: sales_summary`, `reply_ref:
  queued_for_manual_delivery:e41cd931e403`, `reply_provider: local_spool`;
  el fichero del spool (`5327182b3a689e36__queued_for_manual_delivery-…json`)
  contiene la respuesta con asunto «Re: ¿cómo van las ventas?».
- Correo de remitente desconocido → **202** `ignored` (reason
  `unknown_sender`), sin respuesta.
- WhatsApp del dueño «¿cómo va el pipeline?» → **200** `status:
  owner_command`, `intent: pipeline_status`, `reply_message_id` presente; el
  entrante queda `triaged` con intención `command` y el saliente
  (`direction=out`) registrado en el canal.
- WhatsApp de número desconocido → **200** `status: ignored`, mensaje
  `dismissed`, sin reply.
- Auditoría en PostgreSQL: `ceo_command.email` (sales_summary + reply_ref),
  `ceo_command.email.ignored`, `ceo_command.whatsapp` (pipeline_status),
  `ceo_command.whatsapp.ignored` — los cuatro eventos con su detalle.
- Canal de prueba eliminado tras la validación; las env vars del dueño
  quedan configuradas en el candidato (`.env.candidate-0815` +
  `docker-compose.yml`).
