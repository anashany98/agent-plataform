# Seguridad de la plataforma

## Postura actual

El core adopta defensa en profundidad y fail-closed, pero **no declara certificación formal**. Redis 7.2.14 tiene runtime y Trivy 0 HIGH/CRITICAL verificados; el scan del resto de imágenes, secretos, E2E desplegado y restore todavía están pendientes. Por ello, la decisión sigue siendo `NOT PRODUCTION READY — REMEDIATION INCOMPLETE`.

## Controles implementados

| Superficie | Control |
|---|---|
| Identidad | JWT HS256 con `exp/iat/jti`, secreto requerido, instalación/rol/usuario/version verificados en cada request |
| Contraseña | PBKDF2-SHA256, 310.000 iteraciones, sal aleatoria, política de 12 caracteres y cambio inicial obligatorio |
| Revocación | Logout/cambio/desactivación incrementa o verifica `token_version` |
| RBAC | Backend: admin/operator/read; provider_admin separado; Portal deriva capacidades del dashboard y falla cerrado |
| Tenant | `installation_id` en entidades, filtros ORM automáticos, writes cruzados rechazados, DB/volumen por cliente |
| Rate limiting | Login y tráfico; Redis obligatorio y fail-closed en production; proxy chain/CIDR explícitos |
| HTTP | Hosts/CORS explícitos, OpenAPI deshabilitado en staging/production, límites Pydantic, errores no convertidos en éxito |
| Webhooks | Chatwoot HMAC SHA-256 + timestamp; Activepieces bearer/RBAC + `Idempotency-Key`; replay/conflict controlado |
| Idempotencia | Payload fingerprint, lease, estados processing/completed/failed, respuesta replay y conflicto 409 |
| Concurrencia | `If-Match` y CAS para recursos/aprobaciones; constraints/FKs transaccionales |
| Finanzas | `Decimal`, recálculo servidor, stock autoritativo, token/TTL, draft/aprobación; automático prohibido |
| Agentes | Tool allowlist deny-by-default, esquema de argumentos, presupuesto/timeout/provider controlado |
| RAG | Root allowlist, límites, ACL por rol, detector de prompt injection, abstención/citas y eliminación de chunks |
| Publicación | Wiki allowlist HTML; landing escapada; CSP sandbox; aprobación y ruta local solamente |
| SSRF/egress | Production Bridge sin default route; outbound webhook bloquea IP privadas/loopback y usa allowlist/HMAC |
| Contenedores | Digests, no `latest`, non-root donde viable, cap-drop, no-new-privileges, read-only/tmpfs, límites y health |
| TLS | Terminación dedicada; preflight valida fecha, par cert/key, SAN, leaf y prohíbe self-signed en release |
| Logs | JSON, correlación y redacción por clave/patrón; no bodies documentales completos |
| Backups | AES-256-CBC + PBKDF2, HMAC-SHA256, checksums, allowlist de entradas y manifest cliente/perfil/config |

## Configuración production obligatoria

- `ENVIRONMENT=production`, `PILOT_MODE=false`, `DEBUG=false`.
- Demo, mocks y stubs `false`.
- DB PostgreSQL; nunca SQLite.
- Redis, outbox worker y scheduled worker `true`.
- `RATE_LIMIT_BACKEND=redis`, `REDIS_RATE_LIMIT_FAIL_OPEN=false`.
- Confirmación de pedido, emisión de factura y publicación automáticas `false`.
- `ALLOWED_ORIGINS`/`ALLOWED_HOSTS` exactos; `TRUSTED_PROXY_COUNT=2` para la cadena TLS.
- Proveedores LLM `none`, embedding `local_tfidf`, email `local` mientras no exista egress aprobado.
- Imágenes versionadas/digest y app images con labels OCI coincidentes con manifest.

## Riesgos residuales

1. JWT en `sessionStorage`; XSS del mismo origen podría leerlo.
2. Sin MFA/SSO ni permisos por objeto.
3. Sin AV/DLP externo para uploads.
4. Alertas no salen del proceso y no existe SIEM/pager en el core.
5. DB/Redis son single-instance; no HA.
6. Vendors/full no certificados y con licencias/configuraciones adicionales.
7. Scan final del conjunto de imágenes/historia aún pendiente; solo Redis está cerrado.
8. Revisión fiscal, privacidad y legal es externa a esta auditoría técnica.

## Verificación antes de exponer

1. Ejecutar preflight release sobre checkout limpio.
2. Escanear Git/artefactos/imágenes; resolver críticos/altos o aceptar por escrito con fecha.
3. Probar 401/403, acceso A/B, replay, conflicto, concurrencia y inputs maliciosos.
4. Validar TLS desde cliente externo y ausencia de puertos internos publicados.
5. Probar caída de Redis/DB/workers y confirmar 503/readiness.
6. Restaurar backup y rotar secrets de bootstrap.
7. Configurar logs/alertas en un sistema externo con acceso restringido.

Consultar [`THREAT_MODEL.md`](THREAT_MODEL.md), [`SECRET_MANAGEMENT.md`](SECRET_MANAGEMENT.md) e [`INCIDENT_RESPONSE.md`](INCIDENT_RESPONSE.md).
