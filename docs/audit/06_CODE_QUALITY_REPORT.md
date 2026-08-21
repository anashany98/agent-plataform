> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# 06 - Calidad de código

## Resultado ejecutivo

La base propia es legible y contiene controles útiles —RBAC, HMAC, transacciones de reserva, límites de upload y abstención RAG—, pero la calidad de entrega es **SECURITY/QUALITY GATE FAILED**. Compila y sus tests locales pasan, mientras lint, formato y tipos fallan; varios defectos de negocio quedan fuera de las pruebas.

## Herramientas ejecutadas

| Comando | Resultado | Estado |
|---|---|---|
| `ruff check bridge-api/app tests` | 297 incidencias; 179 autofixables. Dominan UP006 (120), B008 (90), UP007 (34); además F401/I001/F811 | BROKEN |
| `black --check bridge-api/app tests` | 21 archivos se reformatearían; 1 queda igual | BROKEN |
| `mypy bridge-api/app --ignore-missing-imports` | 71 errores en 5 archivos; 51 en `main.py` | BROKEN |
| `bandit -r bridge-api/app` | 0 altas, 0 medias, 2 bajas; una es falso positivo `bearer`, otra PRNG demo | PARTIALLY VERIFIED |
| `pytest` + coverage en contenedor Python 3.12 | 31 passed; 67 % total; 2 warnings de arnés | VERIFIED |
| `npm ci` | 200 paquetes instalados desde lock | VERIFIED |
| `npm run typecheck` | código 0 | VERIFIED |
| `npm run build` | código 0; JS 160,65 kB, CSS 7,46 kB | VERIFIED |
| `npm run format:check` | 5 archivos con formato incorrecto | BROKEN |
| `npx eslint src` | ESLint 10.8 sin `eslint.config.*`; código 2 | BROKEN |
| Tests/cobertura frontend | No existen | NOT IMPLEMENTED |

## Hallazgos de código propios

### Negocio y consistencia

1. **P0 - catálogo demo como verificado.** `seed.py` crea 100 productos aleatorios `source=demo`. `search_products` no filtra origen y el webhook llama al resultado “verificado”.
2. **P0 - confirmación por substring.** La condición acepta cualquier texto que contenga `acepto` o `confirmar`; `no acepto` confirma pedido, reserva y borrador.
3. **P0 - precio no contractual.** El adapter recupera combinaciones y `specific_prices`, pero `calculate_price` usa precio/IVA local y una tarifa porcentual propia.
4. **P0 - stock no reservado en la autoridad.** La reserva vive solo en Bridge, sin expiración, liberación ni escritura PrestaShop.
5. **P1 - aprobación concurrente.** Lectura de estado y actualización no usan `SELECT FOR UPDATE` ni compare-and-swap.
6. **P1 - idempotencia GHL no atómica.** Efecto externo antes de confirmar el registro local; una caída/reintento puede duplicar.
7. **P1 - bajas y frescura de catálogo.** Sync actualiza/crea pero no desactiva ausentes ni publica edad del dato.

### Integraciones y agentes

- El chat es una heurística, no un agente con tool calling. `allowed_tools` se almacena en memoria y no se aplica.
- `/agents/run` entrega prompt libre a un modelo; no está conectado al flujo Chatwoot ni anclado a catálogo/RAG.
- Router y adapters carecen de retry con backoff, circuit breaker y outbox.
- Activepieces devuelve éxito con cualquier 2xx y crea un ID `exec-*` si el servidor no lo devuelve.
- El handoff Chatwoot solo abre la conversación; no asigna agente/equipo.
- Captura de lead no procesa un email/teléfono enviado en mensajes posteriores.
- Presupuesto/pedido local nunca se crea en PrestaShop.

### Seguridad y robustez

- `uvicorn --forwarded-allow-ips=*` y rate limit confía en `X-Real-IP`; `TRUSTED_PROXY_COUNT` no se usa.
- `/health` devuelve HTTP 200 incluso si DB está degradada; Compose no usa `/ready`.
- OpenAPI/docs quedan públicos y health filtra identificador de instalación.
- RAG valida extensión/tamaño y zip bombs, pero no magic bytes/antivirus; el filtro de secretos es una lista de palabras evadible.
- Logs de auditoría pueden almacenar payload/respuesta con PII; no hay redacción, retención ni inmutabilidad.
- Seguridad estricta solo se activa en `production/staging`; la instancia piloto está en `development`.
- Modelos Pydantic no prohíben campos extra ni todas las transiciones de estado.

### Mantenibilidad y rendimiento

- `main.py`: 1.192 líneas y responsabilidades múltiples.
- Modelos SQLAlchemy usan API declarativa antigua, causando gran parte de los errores MyPy.
- `AGENT_REGISTRY` es memoria de proceso y se pierde al reiniciar.
- Costes: `_estimate_cost` devuelve siempre 0; el límite diario nunca se activa.
- `/costs` carga todos los logs. RAG carga todos los chunks y consulta documentos N+1.
- Una única migración llama `Base.metadata.create_all`; su downgrade usa `drop_all`, por lo que no es una historia evolutiva segura.
- Imports de hasta 10.000 registros hacen consultas por fila y no ofrecen upsert/export.

## Dependencias

- `pip-audit`: 53 dependencias resueltas, 2 paquetes vulnerables, 60 identificadores agregados/duplicados: `pypdf 5.9.0` y `Pillow 11.3.0`. Son parsers de contenido subido y requieren priorización.
- `npm audit`: 2 vulnerabilidades, 1 alta (`vite`) y 1 moderada (`esbuild`); el fix sugerido exige salto mayor a Vite 8.2.0.
- Python no tiene lock/hash; npm sí tiene lock.
- Versiones de `THIRD_PARTY_NOTICES.md` no coinciden con lo resuelto actualmente.

## Dockerfile/Compose

- Bridge: usuario `app`, root FS read-only y capabilities eliminadas: positivo.
- Portal: root FS read-only/capabilities reducidas, pero Nginx ejecuta como root y conserva `SETGID`.
- Chatwoot, Activepieces, FlowWink, DB y Redis corren como root por defecto.
- Proxy elimina `SETUID`, impidiendo workers; su health deja procesos `wget` huérfanos.
- Sin límites CPU/memoria/PID. Imágenes por tags y bases flotantes; no digests.
- Hadolint no está instalado. Escaneo de imágenes/SBOM quedó BLOCKED por memoria > 90 %.

## Archivos revisados

Todo el código propio Python/TypeScript/CSS, migración, tests, scripts, Dockerfiles, Compose/proxy, locks y adaptadores; vendor solo en rutas justificadas.

## Riesgos y trabajo pendiente

- Un pipeline actual no bloquearía defectos: no hay CI local visible y todos los quality gates salvo tests/typecheck/build fallan.
- Añadir pruebas de regresión antes de corregir P0; luego separar dominio, actualizar ORM typing y fijar dependencias.
- Ejecutar escaneo de imagen/SBOM en una ventana con RAM segura.
