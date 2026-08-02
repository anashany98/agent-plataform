# Evidencia de pruebas de producción

## Regla de evidencia

Una prueba solo se marca `VERIFIED` si es reproducible, comprueba efectos reales y no sustituye el componente objetivo por mocks. Build, arranque, health e integración son niveles distintos.

## Evidencia heredada contrastada

| Fecha | Prueba | Resultado observado | Alcance real | Estado actual |
|---|---|---|---|---|
| 2026-08-02 | Pytest backend aislado | 31 passed; 2 warnings; 4,96 s | SQLite, demo, mocks/stubs, TF-IDF local, rate limit desactivado | BLOCKED |
| 2026-08-02 | Coverage backend | 67 % total | No cubre rutas críticas reales ni concurrencia suficiente | BLOCKED |
| 2026-08-02 | Portal typecheck/build | TypeScript y build Vite correctos | Sin tests frontend ni UX runtime | FIXED |
| 2026-08-02 | Compose config | Código 0; 14 servicios, 3 redes, 9 volúmenes | Valida sintaxis, no runtime | VERIFIED |
| 2026-08-02 | Runtime heredado | 12 healthy; Chatwoot restart; proxy unhealthy | Demuestra fallos, no funcionalidad | BLOCKED |
| 2026-08-02 | Build `--no-cache --pull` | Cancelado al 95,3 % de RAM | Sin resultado de build | BLOCKED |
| 2026-08-02 | Backup restore | No ejecutado | Sin RPO/RTO | BLOCKED |
| 2026-08-02 | UX Playwright | No ejecutada | RAM, proxy y wrapper incompatible | BLOCKED |

Los resultados `BLOCKED` pueden contener una ejecución histórica correcta, pero no constituyen evidencia de producción por usar dobles, cubrir solo una capa o demostrar un fallo. Toda la suite se volverá a ejecutar en la Fase 1 y se añadirán primero reproducciones rojas para cada P0/P1.

## Gate G01 — baseline

| Fecha | Control | Resultado | Alcance |
|---|---|---|---|
| 2026-08-02 | `docker compose --profile '*' config --quiet` | VERIFIED, código 0 | Renderizado estático de 14 servicios, 3 redes y 9 volúmenes; no acredita runtime |
| 2026-08-02 | Integridad de registros | VERIFIED | 37 tareas con estados autorizados; 30 criterios PR completos; 24 gates ordenados |
| 2026-08-02 | Enlaces Markdown de control/baseline | VERIFIED | Ningún destino local ausente en los 13 documentos del gate |
| 2026-08-02 | `git diff --check` | VERIFIED | Sin errores de whitespace; los avisos CRLF son informativos |
| 2026-08-02 | Patrones de secretos de alta señal | VERIFIED | Cero archivos coincidentes fuera de vendor/artefactos; `.env` ignorado y no trazado |

El gate G01 no arrancó servicios, no leyó valores de `.env`, no inspeccionó el contenido de volúmenes y no convierte ningún criterio funcional en `VERIFIED`.

## Próxima evidencia obligatoria

1. Negaciones y confirmación concurrente.
2. Exclusión de demo y startup fail-closed en producción.
3. Pricing `Decimal` por variante/impuesto y stock con TTL/release.
4. Migración clean install/upgrade/rollback sin pérdida.
5. Tenant isolation e ID enumeration.
6. Webhooks duplicados, replay y outbox.
7. Providers locales sin stubs y fallos externos explícitos.
8. Restore en instalación vacía.
