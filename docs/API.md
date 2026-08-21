# API HTTP

## Convenciones

La API Bridge se publica detrás de TLS. Los ejemplos usan `https://api.example.invalid`; sustituya el host sin copiar credenciales reales. El Portal accede mediante el proxy `/api/bridge/...`; los clientes directos usan las rutas raíz documentadas abajo.

En producción, OpenAPI/Swagger está deshabilitado. En desarrollo controlado puede consultarse `/docs`, que es la referencia de esquemas generada por el código de la versión instalada.

### Autenticación

```http
Authorization: Bearer <jwt>
Content-Type: application/json
```

El JWT está ligado a usuario, rol, instalación, expiración, `jti` y `token_version`. Un token de otra instalación o revocado se rechaza. Las rutas `/live`, `/health` y las dos rutas públicas de contenido tienen contrato especial; el resto requiere autenticación salvo indicación expresa.

### Escrituras seguras

- En las mutaciones que lo exigen, envíe `Idempotency-Key: <uuid-o-identificador-unico>`.
- Repetir la misma clave y el mismo payload devuelve el resultado persistido sin duplicar el efecto.
- Reutilizarla con payload distinto devuelve `409`.
- Omitirla devuelve `428`.
- En ediciones versionadas, envíe `If-Match: <version-entera-positiva>`; una versión obsoleta devuelve `409`.

### Errores relevantes

| Código | Significado operativo |
|---:|---|
| 400 | Payload o transición inválida |
| 401 | Token ausente, expirado o revocado |
| 403 | Rol/instalación no autorizados |
| 404 | Recurso inexistente o invisible para el ámbito |
| 409 | Conflicto de versión/idempotencia/estado |
| 422 | Validación de campos o header incorrecto |
| 428 | Falta `Idempotency-Key` o `If-Match` obligatorio |
| 429 | Límite de petición/coste alcanzado |
| 502 | Proveedor externo falló o respondió inválido |
| 503 | Dependencia esencial no preparada |

Conserve `X-Request-ID`/correlation ID de la respuesta al abrir una incidencia; no registre el bearer ni payloads sensibles.

## Endpoints por dominio

| Dominio | Endpoints principales | Rol general |
|---|---|---|
| Auth | `POST /auth/login`, `/auth/logout`, `/auth/change-password` | usuario autenticado salvo login |
| Usuarios | `GET/POST /users`, `PATCH /users/{id}` | admin |
| Salud | `GET /live`, `/health`, `/ready`, `/health/details`, `/metrics` | detalles/métricas admin |
| Dashboard | `GET /dashboard`, `/provider/dashboard`, `/costs` | lectura; provider/admin según ruta |
| Clientes | `GET/POST /customers` | operativo |
| Presupuestos | `GET/POST /quotes`, `GET /quotes/{id}`, `POST /quotes/{id}/confirm` | operativo |
| Pedidos | `GET /orders`, `GET /orders/{id}` | operativo |
| Facturas | `GET /invoices`, `GET /invoices/{id}`, `POST /invoices/{id}/request-approval` | operativo |
| Aprobaciones | `GET /approvals`, `POST /approvals/{id}/approve` y `/reject` | lectura operativa; decisión admin |
| RAG | `POST /rag/ingest`, `/rag/upload`, `/rag/query`; `GET /rag/documents`; `DELETE /rag/documents/{id}` | ingesta/borrado admin; consulta lectura |
| Agentes | `GET/POST /agents`, `PATCH /agents/{id}`, solicitud de activación, run/tools | lectura/operativo/admin según acción |
| Wiki | CRUD/preview/solicitud y `GET /public/wiki/{slug}` | admin/lectura; público solo publicado |
| SEO | proyectos, edición, `analyze-html`, historial | admin/operativo |
| Landing | CRUD/preview/solicitud y `GET /public/landing-pages/{slug}` | admin/lectura; público solo aprobado |
| Tareas | CRUD, solicitud de activación, `run-due` | admin |
| CRM | `GET/POST /leads`, `GET /opportunities` | operativo |
| Import | `POST /import/{entity_type}`, `/import-file/{entity_type}` | admin |
| Workflows | `POST /workflows/trigger` | operativo |
| Lifecycle | estado, export, erase, legal-hold, process-due-erases | admin |
| Outbox | listar, procesar, reintentar | admin/operativo según acción |
| Integraciones | PrestaShop productos/sync/historial; GHL leads | lectura/admin/operativo |
| Webhooks | Chatwoot y Activepieces | contrato específico; ver WEBHOOKS |

## Ejemplos mínimos

### Login

```powershell
$body = @{ username = "admin"; password = "<desde-gestor-de-secretos>" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "https://api.example.invalid/auth/login" -ContentType "application/json" -Body $body
```

No guarde la respuesta en historial de shell compartido. Tras recibir el token, úselo solo durante su TTL y cierre sesión.

### Alta idempotente de cliente

```http
POST /customers HTTP/1.1
Authorization: Bearer <jwt>
Idempotency-Key: onboarding-customer-20260815-001
Content-Type: application/json

{"name":"Cliente ejemplo","email":"contacto@example.invalid"}
```

### Consulta RAG

```http
POST /rag/query HTTP/1.1
Authorization: Bearer <jwt>
Content-Type: application/json

{"query":"¿Cuál es el plazo indicado?","top_k":5}
```

La aplicación consumidora debe mostrar las citas devueltas y no convertir una respuesta sin evidencia en hecho confirmado.

## Paginación, búsquedas y compatibilidad

Los listados aplican límites del esquema de la versión y filtros específicos del dominio. No dependa de orden implícito ni de campos no documentados por OpenAPI. Integre contra la versión SemVer/commit del manifiesto y ejecute contract tests antes de actualizar.

No existe compromiso público de compatibilidad ilimitada entre builds `dev`. La release productiva debe identificar `0.9.1-<sha12>` y conservar su manifest para soporte y rollback.
