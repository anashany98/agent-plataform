# 02 - Inventario de componentes

**Fecha:** 2026-08-02  
**Criterio:** el estado describe evidencia de esta auditoría, no intención documental.

## Inventario maestro

| Componente | Propósito y datos | Dependencias | Estado real | Tests/evidencia | Acoplamiento, sustitución y riesgo |
|---|---|---|---|---|---|
| Reverse proxy | Único punto de entrada HTTP; no posee datos | Nginx 1.25, Portal, Bridge, Chatwoot, FlowWink, Activepieces | BROKEN | Sin workers por `setuid(101) failed`; sin puerto publicado efectivo | SPOF. Sustituible por Caddy/Traefik/Nginx corregido. Falta TLS real |
| Portal | Login, resumen, costes y aprobaciones | React 18, Bridge API | PARTIALLY VERIFIED | Typecheck y build pasan; runtime visual BLOCKED | Acoplamiento bajo. Navegación anuncia módulos inexistentes |
| Bridge API | Auth/RBAC, catálogo replicado, presupuestos, pedidos, RAG e integraciones | FastAPI, PostgreSQL, Redis declarado, APIs externas | PARTIALLY VERIFIED | Login/runtime y 31 tests locales; flujo real externo roto | Monolito de 1.192 líneas; núcleo propietario y difícil de sustituir sin contrato |
| Bridge PostgreSQL | Datos comerciales locales, usuarios, auditoría y vectores | pgvector/pg15 | VERIFIED | Consultas reales: 15 tablas, migración `0001`, 100 productos demo | Fuente local no reconciliada con PrestaShop; aislamiento depende del volumen |
| Bridge Redis | Declarado para caché/infraestructura | Redis 7 | CONFIGURED ONLY | Health de contenedor; el código propio no demuestra uso relevante | Prescindible en MVP actual salvo rate limit/colas futuros |
| FlowWink | UI estática vendorizada para agentes/operación | Vite SPA, Supabase externo | BROKEN | Nginx servía la SPA, pero URL/clave/proyecto Supabase vacíos y no hay backend | No aporta capacidad operativa actual; candidato a eliminar del MVP |
| Chatwoot Web | Widget, inbox y conversaciones | Rails, PostgreSQL, Redis, storage | BROKEN | Reinicio por PID obsoleto; DB con 98 tablas y 0 filas estimadas | Vendor pesado; útil solo si se completa onboarding y e2e |
| Chatwoot Worker | Colas y webhooks | Sidekiq, DB, Redis | PARTIALLY VERIFIED | Healthy antes del cierre; webhook firmado compatible por revisión vendor | Sin egress no puede entregar webhooks externos |
| Chatwoot DB/Redis | Conversaciones, contactos, trabajos | PostgreSQL 16, Redis 7 | VERIFIED | Health real; DB 19 MB/98 tablas, sin datos | Independientes por proyecto Compose |
| Activepieces App | UI/API de automatización | Imagen oficial 0.86.3, DB, Redis | PARTIALLY VERIFIED | Healthy, pero 0 filas, sin API key ni flujos; CPU/tráfico anómalos | Complejidad alta para MVP; sustituible por jobs propios |
| Activepieces Worker | Ejecución de flujos | App, Redis, DB | PARTIALLY VERIFIED | Healthy; errores Socket.IO/poll y sin flujos reales | Sin egress no ejecuta conectores externos |
| Activepieces DB/Redis/cache | Proyectos, ejecuciones, colas y paquetes | PostgreSQL 14, Redis, volumen cache | PARTIALLY VERIFIED | DB 13 MB/79 tablas/0 filas; Redis con tráfico elevado | Cache compartida app-worker no incluida en backup |
| PrestaShopAdapter | Lectura de catálogo, variantes, atributos, precios y stock | API Webservice PrestaShop | IMPLEMENTED BUT NOT TESTED | Tests contractuales mock; credenciales vacías y sin ruta de red | Solo lectura; contrato real, multitienda y rate limit sin validar |
| GHLAdapter | Contactos, oportunidades y notas | LeadConnector API | IMPLEMENTED BUT NOT TESTED | Test mock; credenciales vacías y sin ruta de red | No hay reintentos ni idempotencia atómica |
| ChatwootAdapter | Responder y abrir conversación | Chatwoot API | IMPLEMENTED BUT NOT TESTED | Contrato de firma emisor-receptor compatible; API sin credenciales | “Handoff” no asigna agente/equipo |
| ActivepiecesAdapter | Disparo HTTP de webhooks | Activepieces | BROKEN | Puede fabricar `execution_id`; sin API key/flujos | Superficie privilegiada por ruta suministrada por operador |
| Router LLM | Selección de modelo y auditoría de uso | Ollama/OpenAI/Anthropic/compatibles | BROKEN | Ollama configurado pero contenedor sin ruta; mock solo en tests | Coste estimado siempre 0; sin tool calling ni circuit breaker |
| RAG | Ingesta, OCR, embeddings, ACL y búsqueda | pgvector, pypdf, Pillow, Tesseract, Ollama | PARTIALLY VERIFIED | Tests con TF-IDF local; runtime sin documentos ni embeddings remotos | Carga todos los chunks; filtro de secretos evadible; sin reranker |
| Importador | CSV/XLSX/JSON de productos, clientes, stock y tarifas | openpyxl, Bridge DB | PARTIALLY VERIFIED | Tests locales de dry-run/duplicados; no prueba de volumen real | Máx. 10.000; no upsert ni exportación |
| Scripts de provisión | Instancia por cliente y secretos | Bash/PowerShell, Docker Compose | IMPLEMENTED BUT NOT TESTED | Revisión estática; instalación actual no usa `.env.<cliente>` | Generan recibo con contraseña; TLS prometido pero no configurado |
| Backup/restore | Tres DB y dos volúmenes, cifrado y checksums | Docker, pg_dump, tar, OpenSSL | IMPLEMENTED BUT NOT TESTED | No hubo restauración; convención de proyecto no coincide con instancia actual | Snapshot no consistente y omite Redis/cache/configuración |
| Update/rollback | Checkout, backup, rebuild y restauración | Git, scripts anteriores | BROKEN | Workspace no es repositorio Git | Checkout global impide actualización realmente independiente |
| Tests backend | Integración local FastAPI/SQLite | Pytest, mocks/stubs | VERIFIED | 31/31 pasan, cobertura 67 % | No cubren servicios reales ni concurrencia |
| Tests frontend | Calidad visual/funcional | No definidos | NOT IMPLEMENTED | No hay runner ni archivos de test | Riesgo alto de regresión de portal |

## Imágenes, redes y volúmenes

- Imágenes observadas: Chatwoot local 685,5 MiB; Activepieces 369,3 MiB; Bridge 207,1 MiB; pgvector 146–149 MiB; FlowWink 40,3 MiB; Portal 19,6 MiB; Nginx 19,5 MiB; Redis 15,5 MiB.
- Redes: `public`, `internal` y `data`. `internal` y `data` tienen `internal: true`. Bridge, Chatwoot y Activepieces carecen de ruta por defecto.
- Nueve volúmenes: tres PostgreSQL, tres Redis/cache, `bridge_uploads`, `chatwoot_storage_data` y `activepieces_cache`.
- Solo el proxy debería publicar puerto. En el runtime observado no lo hizo porque el 9000 estaba ocupado por otro proyecto.
- No existen límites de CPU, memoria o PID por servicio.

## APIs y webhooks propios

- 39 operaciones HTTP aproximadas: auth/usuarios, health/readiness/metrics, Chatwoot y Activepieces, RAG, herramientas de producto/precio, agentes, aprobaciones, costes, importación, workflows, PrestaShop y GHL.
- Chatwoot 4.16.2 firma webhooks con `X-Chatwoot-Timestamp`, `X-Chatwoot-Signature` y `X-Chatwoot-Delivery`; Bridge verifica timestamp y HMAC.
- No hay API propia completa para categorías, clientes, stock, presupuestos, pedidos, reservas, facturas, exportación, backups o alertas.

## Variables y modelos

- La instalación activa está en `development`, `PILOT_MODE=true`, `AUTO_SEED_DEMO_DATA=true`.
- Credenciales externas de PrestaShop, GHL, Chatwoot API y proveedores cloud están vacías. Activepieces se marca falsamente como configurado por tener URL base.
- Modelos configurados: Ollama `qwen2.5:3b`, `qwen2.5:7b` y embedding `nomic-embed-text`; disponibilidad y licencias locales BLOCKED.
- No hay reranker. El fallback TF-IDF solo está permitido en desarrollo/test.

## Licencias inventariadas

- FlowWink: MIT.
- Chatwoot: MIT salvo `enterprise/`, sujeto a licencia separada; ese directorio está presente y entra en el contexto de build.
- Activepieces: MIT salvo `packages/ee/` y rutas EE; están presentes en vendor.
- Código propio: no existe `LICENSE` raíz; la afirmación “client-owned” no tiene instrumento de licencia verificable.
- Dependencias: predominan MIT/BSD/Apache/PostgreSQL; falta SBOM completo reproducible.

## Archivos revisados

Compose, Dockerfiles, manifiestos Python/npm, código propio, migraciones, scripts, tests, README/licencias/manifiestos vendor y configuración de proxy.

## Defectos y riesgos

- Inventario documental anterior asignaba funciones a componentes que no las ejecutan.
- FlowWink y Redis Bridge incrementan complejidad sin capacidad MVP demostrada.
- Fuentes de verdad múltiples y componentes sin egress invalidan el recorrido comercial.

## Trabajo pendiente

- SBOM y escaneo de imágenes: BLOCKED por RAM > 90 % tras el build.
- Inventario de modelos efectivamente descargados: BLOCKED por red interna y Ollama inaccesible.
- Pruebas reales de APIs externas: requieren credenciales/sandboxes y topología corregida.

