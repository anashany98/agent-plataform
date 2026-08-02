# Evidencia de reproducción — Fase 1

## Alcance y reglas

- **Captura principal:** 2026-08-02, Europe/Madrid.
- **Baseline Git:** `4d4a6e915916467ca45c76a89af058cf7d219a27`.
- **Runtime:** los 14 contenedores del proyecto permanecieron detenidos; solo se consultaron metadatos/logs históricos y se ejecutó un contenedor Python efímero sin red para leer versiones instaladas.
- **Datos:** exclusivamente fixtures sintéticos y la SQLite temporal de tests.
- **Servicios externos:** no se enviaron mensajes ni se contactaron PrestaShop, GHL, Chatwoot, Activepieces, Supabase o proveedores LLM reales.
- **Fase:** no se modificó código de producción; los tests de regresión están intencionadamente rojos.

`RED` significa que una aserción de seguridad/negocio falla por el comportamiento observado. `OBSERVED` significa que código, configuración, metadatos o logs actuales prueban la condición. `NOT OBSERVED` descarta la afirmación concreta dentro del alcance ejecutado. `PARTIAL` y `BLOCKED` impiden cerrar el defecto.

## Entorno de tests y deriva del harness

Python del `PATH` apuntaba a un entorno Hermes sin `pytest`. Se utilizó explícitamente:

```text
C:\Users\PC\AppData\Local\Programs\Python\Python311\python.exe
pytest 8.3.3
fastapi 0.136.0
sqlalchemy 2.0.36
```

La primera ejecución heredó `ALLOWED_HOSTS` desde el `.env` local porque `tests/conftest.py` no lo fija. No se leyó ni imprimió ese archivo. Resultado: `7 passed, 9 failed, 15 errors`; todos los fallos HTTP mostraban `Invalid host header`. Al fijar solo el valor sintético de test, sin tocar `.env`, la suite heredada volvió a su resultado esperado:

```powershell
$env:PYTHONPATH=(Resolve-Path bridge-api).Path
$env:ALLOWED_HOSTS='testserver,localhost,127.0.0.1'
& 'C:\Users\PC\AppData\Local\Programs\Python\Python311\python.exe' `
  -m pytest tests\integration -q --disable-warnings
```

```text
31 passed, 1 warning in 2.00s
```

Esto verifica la ejecución histórica en su alcance simulado, no el producto: usa SQLite, demo, mock LLM, stubs, TF-IDF local y rate limiting desactivado.

## Reproducciones rojas

Comando consolidado:

```powershell
$env:PYTHONPATH=(Resolve-Path bridge-api).Path
$env:ALLOWED_HOSTS='testserver,localhost,127.0.0.1'
& 'C:\Users\PC\AppData\Local\Programs\Python\Python311\python.exe' `
  -m pytest tests\regression -q --tb=short --disable-warnings
```

Resultado reproducido:

```text
19 failed, 1 warning in 1.04s
```

| Grupo | Tests rojos | Condiciones confirmadas |
|---|---:|---|
| Catálogo/confirmación | 2 | 20 productos demo visibles; `No acepto` crea pedido |
| Pricing/stock | 4 | Variante no soportada, IVA autoritativo ignorado, reserva externa local, sin release |
| Migración | 1 | Downgrade elimina 14 tablas |
| Aislamiento/startup | 2 | 12 tablas sin contexto de instalación; no existe `ALLOW_DEMO_DATA` fail-closed |
| Integraciones/atomicidad | 6 | Duplicado GHL, carrera de aprobación, handoff sin asignación y tres adapters sin retry |
| Safety contracts | 4 | ID Activepieces inventado, coste cero, RAG público abierto y health 200 con DB caída |

Archivos:

- `tests/regression/test_p0_catalog_confirmation.py`
- `tests/regression/test_p0_commerce_authority.py`
- `tests/regression/test_p0_isolation_startup.py`
- `tests/regression/test_p0_migrations.py`
- `tests/regression/test_p1_integration_atomicity.py`
- `tests/regression/test_p1_safety_contracts.py`

## Checklist específico de la misión

| Comprobación requerida | Resultado actual | Evidencia |
|---|---|---|
| Productos demo visibles como reales | RED | D-001; 20 resultados demo en la consulta dirigida |
| Falta de filtro por origen | RED | `search_products` puntúa todos los `Product`; test API falla |
| Falta de aislamiento entre clientes | RED | D-031; 12 tablas sin clave explícita de instalación/tenant/cliente |
| Confirmaciones mediante substrings | RED | D-002; rama `any(term in lowered ...)` |
| `No acepto` interpretado como aceptación | RED | Pedido y quote `confirmed` persistidos |
| Precio incorrecto por variantes | RED | `calculate_price` rechaza `combination_id` |
| Precios específicos ignorados | RED | Datos en `attributes` no participan en el cálculo |
| IVA fijo o incorrecto | RED | Sync recibe 0,10 y persiste 0,21 |
| Stock local divergente | RED | Producto `source=prestashop` se reserva solo en Bridge |
| Reservas inconsistentes | RED | No existe liberación/cancelación/TTL; test de release falla |
| Migraciones con `drop_all` | RED | Fixture pasa de 14 tablas a cero |
| Nginx sin workers funcionales | OBSERVED | 72 `setuid(101) EPERM` y 72 workers fatales |
| Chatwoot reiniciando | OBSERVED | `RestartCount=6`, policy activa y 56 abortos Rails |
| Archivos PID antiguos | OBSERVED | `docker diff` muestra `/app/tmp/pids/server.pid`; comando no lo gestiona |
| Workers con errores | PARTIAL | Proxy demostrado; Chatwoot/Activepieces live siguen bloqueados y detenidos |
| Servicios healthy que no funcionan | RED/PARTIAL | Bridge health devuelve 200 con DB caída; otros estados históricos no son prueba live |
| Dependencia de mocks | OBSERVED | Conftest activa integration stubs y mock LLM; producción los rechaza si es production-like |
| LLM simulado | OBSERVED/BLOCKED | Test devuelve provider `mock` explícito; ningún provider real/local contractual validado |
| Embeddings simulados/locales | OBSERVED/BLOCKED | Tests usan `local_tfidf`; runtime con proveedor real no fue ejecutado |
| RAG sin proveedor real | BLOCKED | Solo TF-IDF de test; además un test rojo demuestra ACL abierta |
| Backup nunca restaurado | BLOCKED | Scripts presentes, sin recibo actual de restore/fixture/RPO/RTO |
| Documentación contradictoria | OBSERVED | README dice “código remediado” y downgrade correcto frente a tests P0 rojos |
| Falta de pruebas E2E | OBSERVED | Cero Playwright/Cypress/Vitest; integraciones reales no ejecutadas |
| Activepieces sin flujos funcionales | PARTIAL/RED | Runtime detenido/DB histórica vacía; 2xx sin ID se convierte en éxito ficticio |
| FlowWink sin backend funcional | PARTIAL | Vendor contiene Supabase, pero Compose despliega solo SPA y ningún servicio Supabase |
| Webhooks sin autenticación | NOT OBSERVED/PARTIAL | Chatwoot HMAC rechaza unsigned; callback Activepieces exige bearer, pero no hay contrato service-to-service E2E |
| Falta de idempotencia | RED | GHL repite efecto; aprobación pierde CAS; Activepieces inventa ID; Chatwoot básico sí deduplica |
| Secretos predeterminados | NOT OBSERVED/BLOCKED | Guard production-like rechaza marcadores/mocks; template development sigue inseguro y `.env` real no se leyó |
| Contenedores ejecutándose como root | OBSERVED/PARTIAL | Solo Bridge declara `user=app`; 13 contenedores no fijan usuario, aunque algunos entrypoints pueden bajar privilegios |
| Puertos innecesariamente públicos | NOT OBSERVED | Compose publica únicamente reverse proxy; existe colisión 9000 con otro proyecto |
| Dependencias vulnerables | OBSERVED | Pip/npm audits actuales fallan; detalle abajo |

## Runtime, operaciones y evidencia estática

La reproducción completa y sanitizada está separada para mantener trazabilidad:

- `docs/remediation/RUNTIME_REPRODUCTIONS.md`: egress, Chatwoot PID/restarts y Nginx workers/capabilities.
- `docs/remediation/STATIC_OPERATIONS_REPRODUCTIONS.md`: puerto, backup/restore, update/rollback, FlowWink, perfiles, licencias, recursos y observabilidad.
- `docs/remediation/PRODUCT_QA_REPRODUCTIONS.md`: dependencias, documentación, portal, privacidad y quality gates.

Hechos operativos de mayor señal:

- Los 14 contenedores siguen `exited`; nueve volúmenes permanecen presentes.
- El puerto 9000 pertenece actualmente al proxy de otro proyecto.
- Los 14 servicios carecen de límites CPU, memoria y PID; la rotación de logs sí está configurada.
- El backup cubre tres DB y dos volúmenes, pero no Redis/cache/configuración y nunca se restauró con evidencia actual.
- Git existe desde la Fase 0; update/rollback siguen usando checkout global y builds mutables.

## Dependencias y quality gates

Comandos no mutantes:

```powershell
# bridge-api
python -m pip_audit -r requirements.txt --format json --progress-spinner off
python -m ruff check app --output-format json
python -m black --check app
python -m mypy app

# portal
npm audit --json --package-lock-only --ignore-scripts
```

| Control | Resultado actual |
|---|---|
| `pip-audit` | Exit 1; `pypdf 5.9.0` con 35 IDs únicos y `Pillow 11.3.0` con 18; los límites `<6`/`<12` impiden alcanzar versiones corregidas |
| `npm audit` | Exit 1; una vulnerabilidad high en Vite y una moderate en esbuild |
| Ruff | Exit 1; 286 violaciones |
| Black | Exit 1; 15 archivos serían reformateados |
| MyPy | Exit 1; 80 errores en 5 archivos |
| Portal tests | Cero archivos/runner de test; cinco de siete anchors sin destino |

No se aplicó `--fix`, no se actualizaron locks y no se instalaron dependencias.

## Controles observados que no deben reabrirse sin evidencia

- Chatwoot HMAC ausente/inválido devuelve 401 en tests dirigidos.
- Login, revocación básica y rechazo viewer/admin pasan en la suite simulada.
- PrestaShop/GHL sin credenciales devuelven errores explícitos en la suite actual.
- El mock LLM se identifica como `mock`/`simulated`, no como OpenAI real.
- Staging y production comparten `validate_runtime_security`; el provisioning actual usa staging.
- Compose declara un único puerto publicado, el reverse proxy.
- Los logs Docker tienen rotación `10m × 5`.

Estos controles son parciales y no convierten la capacidad asociada en producción.

## Conclusión de Fase 1

Se contrastaron los 30 defectos heredados, se añadieron D-031 (aislamiento explícito) y D-032 (harness no hermético), y se preservó evidencia negativa/positiva sin corregir producción. Hay seis P0, 21 P1 y cinco P2 abiertos. La Fase 2 debe comenzar por D-031, D-001–D-005 y después los P1 del núcleo; ninguna función nueva está autorizada antes de cerrarlos.
