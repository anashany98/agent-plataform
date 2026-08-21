# Propiedad y autoridad de datos

## Modelo de aislamiento

La arquitectura soportada es **multi-instance single-tenant**. Cada cliente usa un proyecto `agent-<client-id>`, `INSTALLATION_ID`, PostgreSQL, Redis, redes, volúmenes, secrets, dominio, release manifest y backups propios.

Bridge añade defensa en profundidad: las entidades operativas heredan `InstallationOwnedMixin`; SQLAlchemy inyecta `installation_id` en lecturas/escrituras, rechaza mutaciones cruzadas y usa FKs/uniques compuestas donde existe relación. Esto no autoriza compartir una base entre clientes.

## Matriz de autoridad

| Dominio | Autoridad en production core | Copias/consumidores | Regla |
|---|---|---|---|
| Usuarios, roles y sesiones | Bridge PostgreSQL | Portal consume API | El backend decide; ocultar UI no concede permiso |
| Clientes, leads y oportunidades | Bridge PostgreSQL | Adaptador GHL opcional | Local por defecto; GHL es proyección hasta ADR/contrato específico |
| Catálogo local | Bridge PostgreSQL | Chat, herramientas, Portal | `source` obligatorio; demo prohibido |
| Catálogo PrestaShop | PrestaShop para precio/stock vivo; Bridge conserva proyección | Herramientas comerciales | Verificar autoridad remota al confirmar; fail-closed si no está disponible |
| Presupuestos y pedidos locales | Bridge PostgreSQL | Portal/agentes | Cálculo servidor, snapshot, token e idempotencia |
| Borrador de factura | Bridge PostgreSQL | Portal/aprobador | No es factura fiscal emitida; aprobación no equivale a envío fiscal |
| Aprobaciones | Bridge PostgreSQL | Portal | Decisión CAS por admin, auditada |
| Agentes/prompts/tools | Bridge PostgreSQL (`agent_definitions`) | Runner/Portal | Allowlist deny-by-default; activación aprobada |
| Wiki y landing local | Bridge PostgreSQL | Rutas públicas locales | Solo estados aprobados/publicados; contenido saneado/escapado |
| SEO | Bridge PostgreSQL + `AuditLog` | Portal | Análisis del HTML recibido; no crawl ni publicación externa |
| Documentos/chunks | Volumen uploads + Bridge PostgreSQL | RAG | ACL por rol, citas, eliminación coordinada |
| Idempotencia/outbox/auditoría/costes | Bridge PostgreSQL | Operación | Una instalación; nunca persistir secretos en detalles |
| Rate limit/locks | Bridge Redis | Workers/API | Contraseña, AOF y fail-closed en producción |
| Email pendiente | `bridge_automation_email` | Operador/relay futuro | Spool local, entrega manual, retención configurada |
| Configuración de despliegue | `.env.<cliente>` fuera de Git | Compose/preflight | No copiar a otra instalación; permisos restrictivos |
| Release | Manifest local de imágenes | Preflight/backup | Debe coincidir con versión, commit, image ID y labels OCI |
| Backup | Archivo cifrado + HMAC + checksums | Operador de restore | Pertenece a un único `client_id`, proyecto, perfil y configuración |

## Clasificación mínima

| Clase | Ejemplos | Tratamiento |
|---|---|---|
| Secreto | contraseñas DB/Redis, JWT, HMAC, API keys, clave TLS | Fuera de Git/logs/docs; rotación y acceso mínimo |
| PII | nombre, email, teléfono, conversación | Minimización, RBAC, retención y export/erase controlado |
| Comercial | catálogo, precio, presupuesto, pedido | Autoridad explícita y cálculo determinista |
| Financiero | impuestos, total, borrador | `Decimal`, aprobación, sin afirmar cumplimiento fiscal |
| Documental | binarios, OCR, chunks, embeddings | Allowlist, tamaño, ACL, citas; AV/DLP externo pendiente |
| Operativo | logs, métricas, auditoría, backups | Redacción, retención, integridad y acceso admin |

## Invariantes

1. Toda consulta propia opera dentro de un `installation_id` válido.
2. El token debe pertenecer a la instalación y a un usuario activo con la misma versión/rol.
3. El frontend, un LLM o un vendor nunca es autoridad financiera.
4. Toda mutación reintentable usa `Idempotency-Key`; toda edición versionada usa `If-Match`.
5. Una publicación, activación o factura sensible requiere aprobación humana.
6. Un backup solo es válido después de restaurarlo y probarlo en un destino controlado.
7. La eliminación de una instalación respeta legal hold y debe abarcar DB, archivos, índices, spool y copias gobernadas.

La prueba final de dos instalaciones, restore integral y borrado sin residuos permanece `PENDING` para la candidata.
