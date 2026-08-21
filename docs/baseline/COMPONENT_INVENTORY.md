# Inventario de componentes actual

**Corte:** 2026-08-15. La existencia de código o un health check no implica certificación E2E.

## Core propio

| Componente | Responsabilidad real | Persistencia | Estado |
|---|---|---|---|
| `bridge-api` | Auth/RBAC, aislamiento, catálogo/CRM, comercio determinista, aprobaciones, RAG, agentes, Wiki, SEO estático, landing local, scheduler, integraciones, auditoría y ciclo de vida | PostgreSQL; volúmenes de uploads y spool de email; Redis para rate limit/locks | Implementado y cubierto por corpus; imagen/E2E final PENDING |
| `portal` | Administración y operación en español: login, dashboard, aprobaciones, catálogo/import, documentos, agentes, clientes, ventas, contenido/SEO, tareas, automatizaciones y usuarios | Token/rol en `sessionStorage`; tema en `localStorage` | 25/25 y build PASS; validación visual final PENDING |
| `bridge-db` | Fuente de verdad transaccional de la instancia | `bridge_db_data` | PostgreSQL 15 + pgvector, cadena Alembic `0001…0013` |
| `bridge-redis` | Rate limit fail-closed, locks y coordinación de workers | `bridge_redis_data`, AOF | Redis 7.2.14 Alpine 3.21 BSD-3 por digest; runtime y Trivy 0 HIGH/CRITICAL verificados |
| `reverse-proxy` | Enrutamiento interno Portal/API | Sin datos | Nginx 1.30.4, usuario 101, read-only |
| `tls-proxy` | Único borde público HTTP/HTTPS del perfil production | Certificado y clave como secrets de Compose | Configuración verificada; certificado real PENDING |

## Capacidades de Bridge

| Dominio | Implementación actual | Límite explícito |
|---|---|---|
| Identidad | JWT HS256, PBKDF2-SHA256, cambio obligatorio de contraseña, revocación por `token_version` | Sin MFA/SSO; token de Portal accesible a JS en `sessionStorage` |
| Aislamiento | `installation_id` en entidades, FKs/uniques compuestas, filtros ORM y rechazo de escrituras cruzadas | Arquitectura soportada: una instancia/DB por cliente, no SaaS compartido |
| Catálogo | Local/import, CSV/XLSX/JSON, búsqueda SQL/semántica y adaptador PrestaShop | PrestaShop opcional y no certificado en production core |
| CRM | Clientes, leads, oportunidades y proveedor local; GHL opcional | No es un CRM enterprise completo |
| Comercio | Presupuestos, confirmación tokenizada, pedidos, reservas y borradores de factura; cálculo con `Decimal` | No emite factura fiscal ni confirma automáticamente por defecto |
| Aprobaciones | CAS/versionado para factura, agente, Wiki, landing y tarea | Requiere administrador humano |
| RAG | Ingesta, OCR básico, chunks, ACL por rol, citas, abstención, pgvector o TF-IDF local | Sin AV/DLP externo; TF-IDF es léxico y acotado |
| Wiki | Borrador, preview, aprobación y publicación local saneada | Sin editor colaborativo, diff/restauración avanzada o publicación externa |
| SEO | Proyecto y analizador determinista de HTML suministrado, historial append-only | Sin crawler, monitorización web ni publicación externa |
| Landing | Borrador, preview y publicación local tras aprobación | Sin dominio/hosting externo, formularios, analytics o rollback avanzado |
| Scheduler | Tarea persistida `automation_sweep`, activación aprobada y worker durable | No es un orquestador genérico; no hace crawls SEO |
| Email | Spool JSON por instalación para entrega manual | `accepted=false`; no entrega por SMTP/API |
| Observabilidad | Logs JSON, correlación, métricas internas, health/readiness y reglas locales | Sin backend externo de métricas, trazas o paginación de alertas |

## Vendors opcionales (`full`)

| Componente | Pin | Uso previsto | Estado de producción |
|---|---|---|---|
| FlowWink | `0cd4e9b8af0d432c9a942a692d8f1fa4a04ec67b` | UI/diseño experimental de agentes | No certificado; no es fuente de verdad |
| Chatwoot | `b05f22da8df103a349c3e820afcb76acb129692a` | Conversaciones y handoff humano | No certificado; riesgo SSRF/configuración y licencia Enterprise separada |
| Activepieces | imagen `0.86.3@sha256:2085…c6c` | Automatizaciones externas | No certificado; flujo real y licencia/uso comercial requieren revisión |

`full` no forma parte de la candidata core de producción. Ningún vendor puede autorizar ni escribir directamente una operación financiera crítica sin validación de Bridge.

## Artefactos de operación

- `scripts/production-preflight.py`: preflight fail-closed.
- `scripts/create-release-manifest.py`: fija image ID, repo digests y etiquetas OCI.
- `scripts/backup-restore-integral.py`: backup/restore formato 4 cifrado y autenticado.
- `scripts/verify-*.py`: contratos de perfiles, red, proxy, backup y pins.
- `.github/workflows/production-gates.yml`: gates CI definidos; ejecución remota de la release PENDING.
