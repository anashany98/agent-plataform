# Evidencia de pruebas de producción

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

El conteo coincide con el corpus documentado: 136 tests en `tests/` + 23 en `bridge-api/tests`. La reverificación no arrancó servicios del proyecto ni contactó proveedores externos. El estado sigue siendo `NOT PRODUCTION READY — CRITICAL RISK`.

## Próxima evidencia obligatoria — P1 restante de Fase 2

1. Reconciliación/outbox/DLQ y fault injection de webhooks/GHL en cada frontera ambigua.
2. Executor de herramientas deny-by-default, clasificación/DLP y corpus de exfiltración/prompt injection.
3. Egress, proxy, Chatwoot, perfiles, límites y observabilidad verificados en runtime seguro.
4. Backup/restore en instalación vacía y release/rollback trazable.
5. Dependencias, SBOM, licencias y pruebas E2E/UI.
