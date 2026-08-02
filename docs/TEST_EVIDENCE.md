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

## Próxima evidencia obligatoria — Fase 2

1. Negaciones y confirmación concurrente.
2. Exclusión de demo y startup fail-closed en producción.
3. Pricing `Decimal` por variante/impuesto y stock con TTL/release.
4. Migración clean install/upgrade/rollback sin pérdida.
5. Tenant isolation e ID enumeration.
6. Webhooks duplicados, replay y outbox.
7. Providers locales sin stubs y fallos externos explícitos.
8. Restore en instalación vacía.
