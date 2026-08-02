# Inventario de componentes

## 1. Alcance y criterio de evidencia

Este inventario describe el estado encontrado al inicio de la remediación, no el producto objetivo. La captura se realizó el **2026-08-02** sobre la rama `production-remediation`, con punto de recuperación `ed77056c9d8084ac7c23b587199938fd4cc346fe`.

Se separan tres tipos de evidencia:

- **Código/configuración:** el componente o comportamiento está presente en los archivos revisados.
- **Pruebas:** existe evidencia reproducible previa en `docs/audit/evidence/`; no equivale a una prueba con servicios externos reales si usa SQLite, mocks o proveedores locales.
- **Runtime:** comportamiento observado en la auditoría técnica anterior y, cuando se indica, estado actual leído con `docker compose ps -a`. No se reinició el stack para elaborar este documento.

La estrategia arquitectónica declarada es **multi-instance single-tenant**: una instalación Compose independiente por cliente, con configuración, bases de datos, redes y volúmenes propios. No es una arquitectura SaaS multitenant compartida. Este aislamiento está solo parcialmente demostrado: `installation_id` protege usuarios y tokens, pero la mayoría de tablas de negocio no tiene `tenant_id`; por tanto, la barrera principal sigue siendo la separación física por proyecto y base de datos.

## 2. Resumen de despliegue

| Elemento | Inventario observado | Evidencia | Limitación relevante |
|---|---:|---|---|
| Servicios Compose | 14 | `docker compose --profile full config --services` | El número no acredita disponibilidad funcional |
| Perfiles Compose | `core`, `full` | Configuración resuelta | `core` incluye FlowWink; no existen aún `chat`, `automation`, `development`, `testing`, `staging` ni `production` |
| Redes | `public`, `internal`, `data` | Compose | `internal` y `data` tienen `internal: true`; Bridge y vendors sin red pública carecieron de egress en el runtime auditado |
| Volúmenes | 9 | Compose | No todos están cubiertos por el backup actual |
| Puertos publicados previstos | Uno, proxy `${PROXY_PORT:-9000}:8080` | Compose | En el runtime auditado no hubo binding efectivo y el proxy no tuvo workers funcionales |
| Bases PostgreSQL | 3: Bridge pg15, Chatwoot pg16, Activepieces pg14 | Compose | Tres líneas mayores aumentan coste operativo |
| Redis | 3: Bridge, Chatwoot, Activepieces | Compose | El uso funcional de Bridge Redis no está demostrado en el código propio |
| Estado actual de contenedores | Todos detenidos | `docker compose --profile full ps -a`, 2026-08-02 | No se infiere salud actual; varios terminaron con código 137 durante la parada de seguridad previa |

## 3. Servicios desplegables

| Componente | Perfil | Responsabilidad real encontrada | Persistencia | Dependencias | Evidencia de código/configuración | Evidencia de runtime y pruebas | Estado de preparación |
|---|---|---|---|---|---|---|---|
| `reverse-proxy` | `core`, `full` | Entrada HTTP por vhosts para Portal, Bridge, Chatwoot, FlowWink y Activepieces | Ninguna | Portal y Bridge saludables; redes `public` e `internal` en Compose | Nginx 1.25, plantilla de upstreams y cabeceras del Portal | Auditoría: master sin workers por falta de `SETUID`; sin publicación efectiva. Actualmente detenido | Flujo de entrada roto hasta corregir capacidades, health y binding |
| `portal` | `core`, `full` | Login, cambio de contraseña, resumen, costes y decisiones de aprobación | `sessionStorage` para token/usuario; `localStorage` para tema | Bridge por `/api/bridge` | React 18 + TypeScript + Vite; una SPA | Typecheck y build previos correctos; prueba visual dinámica bloqueada | Parcial; la navegación anuncia áreas sin pantalla funcional |
| `bridge-api` | `core`, `full` | API propia: auth/RBAC, usuarios, catálogo local, chat/orquestación comercial, importación, RAG, aprobaciones, costes e integraciones | Bridge PostgreSQL y volumen `bridge_uploads`; Redis configurado | Bridge DB/Redis; APIs externas; proveedores LLM/embedding | FastAPI, SQLAlchemy, Alembic y adaptadores HTTP | Login local y 31 tests backend previos; integraciones reales no ejecutadas | Núcleo funcional parcial; contiene defectos P0/P1 descritos en la auditoría |
| `bridge-db` | `core`, `full` | Persistencia transaccional propia y vectores RAG | `bridge_db_data` | Ninguna de aplicación | pgvector sobre PostgreSQL 15 | Auditoría: 15 tablas, 1 usuario, 25 clientes demo, 100 productos demo y sin transacciones reales | Persistencia operativa observada, pero esquema inicial y downgrade destructivo |
| `bridge-redis` | `core`, `full` | Caché/infraestructura declarada | `bridge_redis_data` | Ninguna | Redis 7 con AOF y contraseña | Health previo de contenedor; no se demostró consumo relevante por Bridge | Configurado, no justificado funcionalmente todavía |
| `flowwink-app` | `core`, `full` | SPA vendorizada para diseño/capa de agentes | Supabase externo previsto; ningún volumen propio | Supabase fuera de Compose | Build desde `vendor/flowwink`; variables Supabase de build/runtime | Auditoría: SPA servida, variables Supabase vacías y sin backend | No aporta capacidad de negocio demostrada; además impide que `core` sea realmente mínimo |
| `chatwoot-db` | `full` | Datos de Chatwoot | `chatwoot_db_data` | Ninguna de aplicación | pgvector sobre PostgreSQL 16 | Auditoría: 98 tablas, DB ~19 MB y sin datos de negocio | Almacén presente; sin flujo de conversación real validado |
| `chatwoot-redis` | `full` | Caché/colas de Chatwoot | `chatwoot_redis_data` | Ninguna | Redis 7 con AOF y contraseña | Health previo de contenedor | Infraestructura presente, no acredita el canal E2E |
| `chatwoot-web` | `full` | UI/API/widget de conversaciones | Chatwoot DB, Redis y `chatwoot_storage_data` | DB y Redis | Build vendorizado, Rails en producción | Auditoría: reinicios por PID antiguo y `A server is already running`; actualmente detenido | Roto en el runtime auditado |
| `chatwoot-worker` | `full` | Sidekiq, jobs y entrega de webhooks | Chatwoot DB, Redis y storage compartido | `chatwoot-web` saludable | Imagen compartida con Chatwoot web | Llegó a estar healthy, pero sin egress y sin E2E; actualmente detenido | Solo parcialmente demostrado |
| `activepieces-db` | `full` | Estado de proyectos, flujos y ejecuciones de Activepieces | `activepieces_db_data` | Ninguna de aplicación | pgvector 0.8 sobre PostgreSQL 14 | Auditoría: 79 tablas, DB ~13 MB y 0 filas | Almacén vacío; no existen automatizaciones demostradas |
| `activepieces-redis` | `full` | Colas/cache de Activepieces | `activepieces_redis_data` | Ninguna | Redis 7 con AOF y contraseña | Auditoría: tráfico/CPU anómalos durante reconexiones | Necesita diagnóstico y límites antes de activarse |
| `activepieces-app` | `full` | UI/API del motor de automatización | Activepieces DB y `activepieces_cache` | DB y Redis | Imagen `ghcr.io/activepieces/activepieces:0.86.3` | Auditoría: saludable en un momento, sin API key, proyectos ni flujos; actualmente detenido | Componente instalado, capacidad de negocio no probada |
| `activepieces-worker` | `full` | Ejecutor de flujos | Activepieces DB, Redis y cache compartida | App saludable | Misma imagen, modo `WORKER` | Auditoría: sin flujos y con errores de conexión/reintentos; actualmente detenido | No probado con automatización real |

## 4. Componentes lógicos propios de Bridge

| Módulo | Responsabilidad observada | Almacén/fuente | Dependencias | Evidencia y límite |
|---|---|---|---|---|
| Configuración y arranque | Lee entorno, valida seguridad en entornos tipo producción, ejecuta migración desde entrypoint | Variables de entorno y Alembic | PostgreSQL | Presente en código; el runtime auditado estaba en `development`, por lo que no ejercitó todas las guardas |
| Autenticación y RBAC | PBKDF2, token HMAC, revocación por `token_version`, roles y cambio obligatorio de contraseña | `users` | Bridge DB | Login real observado y tests locales; no hay MFA ni matriz granular completa |
| Rate limiting | Cuotas por IP y ruta | Memoria del proceso | Cabeceras de proxy | No usa Redis; no es consistente con varios workers y requiere una cadena de proxies confiable |
| Catálogo local | Productos, stock local, tarifas y búsqueda | `products`, `pricelists` | Imports y sincronización PrestaShop | Existe; la búsqueda no excluye `source=demo` y no modela combinaciones de forma transaccional |
| Motor determinista comercial | Cálculo con `Decimal`, presupuesto, pedido, reserva y borrador de factura | `quotes`, `orders`, `stock_reservations`, `invoice_drafts` | Catálogo/customer local | Tests locales; precio/IVA/stock oficiales y concurrencia externa no están validados |
| Estado conversacional | Relaciona cuenta/conversación con cliente, presupuesto y pedido | `conversation_states` | Chatwoot webhook y motor comercial | Persistencia mínima; Chatwoot E2E no ejecutado |
| Aprobaciones | Solicitud, aprobación o rechazo de acciones | `approval_requests` | Portal/API | Flujo secuencial probado; la auditoría detectó carrera read-then-write |
| Idempotencia | Reclamo y respuesta por clave | `idempotency_records` | Webhooks y algunos flujos externos | Presente; cobertura no uniforme y no probada con múltiples workers/concurrencia real |
| Auditoría y costes | Registra ejecuciones/eventos, tokens, latencia y coste estimado | `audit_logs` | LLM y acciones internas | Persistencia presente; coste estimado fue siempre cero en la implementación auditada |
| Router LLM | Selecciona perfiles/proveedores OpenAI, Anthropic, Ollama o compatible | Configuración + auditoría | Servicios externos/host | Código presente; Ollama fue inalcanzable y no se probó proveedor real |
| Registro de agentes | Dos configuraciones de agente y endpoint de actualización | Diccionario en memoria | Router LLM | No persiste, no versiona y `allowed_tools` no gobierna un loop real de herramientas |
| RAG | Upload, extracción, OCR opcional, chunks, embeddings, búsqueda, ACL por rol y citas | `rag_documents`, `rag_chunks`, `bridge_uploads` | pgvector, parsers, proveedor embedding | Tests con TF-IDF local; corpus runtime y embeddings reales no probados; ACL por defecto no es fail-closed |
| Importación | CSV/XLSX/JSON para productos, clientes, tarifas y stock | Bridge DB | `openpyxl` y validaciones propias | Pruebas locales de validación/dry-run; sin prueba de volumen o exportación |
| Adaptador PrestaShop | Lee productos, categorías, combinaciones, precios específicos y stock; sincroniza copia local | PrestaShop -> Bridge DB | API Webservice | Contrato revisado y mocks; sin credenciales, egress ni sandbox real |
| Adaptador GHL | Upsert de contacto, oportunidad y nota | GHL + referencias/idempotencia local | API LeadConnector | Código y tests mock; sin prueba real y con atomicidad incompleta |
| Adaptador Chatwoot | Responde mensaje y abre conversación | Chatwoot | REST y webhook HMAC | Firma compatible por revisión focalizada; no asigna agente/equipo y no hubo E2E |
| Adaptador Activepieces | Dispara webhook y recibe callback | Activepieces + idempotencia/auditoría local | API interna | Código presente; la auditoría detectó un `execution_id` sintético y no hay flujo real |

## 5. Componentes operativos y de entrega

| Área | Activos encontrados | Evidencia | Pendiente principal |
|---|---|---|---|
| Aprovisionamiento por cliente | `provision-client.sh` y `.ps1`, plantilla de configuración y proyecto `agent-<cliente>` | Revisión estática | Ensayo limpio, TLS, preflight de puertos, ACL equivalente en Windows y perfil mínimo |
| Backup/restore | Scripts Bash/PowerShell con dumps de 3 DB, uploads Bridge, storage Chatwoot, checksum y cifrado | Revisión estática; nunca restaurado en la auditoría | Consistencia, Redis/cache/configuración/object storage, restore aislado y RPO/RTO |
| Update/rollback | Scripts Bash/PowerShell basados en Git, backup y rebuild | Revisión estática; Git existe ahora, pero flujo no ejecutado | Evitar checkout compartido entre clientes y usar releases/imágenes inmutables |
| Health operativo | Scripts `check-health` y healthchecks Compose | Revisión y runtime previo | Separar liveness/readiness, validar workers y evitar falsos positivos |
| Tests backend | `tests/integration/` | 31 tests pasaron, 67 % de cobertura en auditoría | PostgreSQL/Redis reales, concurrencia, integraciones, migraciones y E2E |
| Tests frontend | No hay runner ni archivos de test | Inventario de `portal/package.json` y `portal/src` | Unitarios, integración, Playwright y accesibilidad |
| CI/CD | No se encontró pipeline en el inventario revisado | Búsqueda del árbol propio | Quality gates, SBOM, secretos, imágenes, release y rollback |

## 6. Riesgos de inventario que condicionan la remediación

1. **Aislamiento incompleto en profundidad.** La topología por instancia es adecuada como estrategia inicial, pero reutilizar una DB, volumen o credencial puede mezclar datos porque casi todas las entidades comerciales carecen de contexto de instalación.
2. **Capacidades declaradas superiores a las demostradas.** FlowWink, Activepieces, agentes, RAG remoto y Chatwoot están presentes o configurados, pero no completan un recorrido real probado.
3. **Fuentes de verdad duplicadas.** Bridge, PrestaShop, GHL y Chatwoot solapan producto, stock, cliente y estado comercial sin reconciliación robusta.
4. **Perfil `core` no mínimo.** Incluye FlowWink y no separa todavía chat/automatización/desarrollo/producción.
5. **Runtime histórico roto y runtime actual detenido.** No se debe interpretar una imagen construida, una DB existente o un healthcheck previo como disponibilidad actual.

## 7. Archivos revisados

- `docker-compose.yml`, `README.md` y configuración de proxy.
- `bridge-api/app/main.py`, configuración, base de datos, seguridad, rate limit, seed, modelos y servicios propios.
- `bridge-api/alembic/versions/0001_initial_schema.py`, Dockerfile y entrypoint.
- `portal/package.json`, `portal/src/App.tsx`, Dockerfile y Nginx.
- `scripts/` de provisión, health, backup/restore, update/rollback y configuración de integraciones.
- `infrastructure/compose/` y `infrastructure/proxy/`.
- Tests propios y evidencia de `docs/audit/02`, `03`, `04`, `05`, `07`, `08`, `12`, `18` y `docs/audit/evidence/`.
- Vendor solo mediante referencias ya auditadas y sus puntos de integración; no se realizó lectura exhaustiva.

## 8. Revisión pendiente o excluida en esta fase

- No se levantó ni modificó el stack; todos los contenedores permanecieron detenidos.
- No se leyó ni reprodujo el contenido sensible de `.env`; se usaron únicamente estados sanitizados de la auditoría.
- No se probaron PrestaShop, GHL, Chatwoot, Activepieces, Ollama ni proveedores cloud con credenciales reales.
- No se reejecutaron builds pesados, carga, DAST, escaneo de imágenes, SBOM ni restore.
- No se revisó vendor completo, por instrucción de alcance; las licencias y modificaciones focalizadas continúan sujetas al informe de auditoría.
- El árbol de trabajo compartido contenía cambios concurrentes fuera de estos documentos; este inventario queda anclado al commit y a los archivos citados.
