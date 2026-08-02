# 12 - Evaluación de seguridad

## Clasificación

# SECURITY BASELINE FAILED

No se declara certificación. Existen controles positivos, pero los P0 de datos/transacción, el runtime de red/proxy, dependencias vulnerables y controles de coste/RAG impiden una baseline aceptable.

## Controles positivos verificados o parciales

| Control | Estado | Evidencia |
|---|---|---|
| Auth bearer y password policy | VERIFIED | Login real; PBKDF2 310k, 12 caracteres y complejidad |
| Revocación | VERIFIED | `token_version`; tests cambio/logout |
| RBAC básico | PARTIALLY VERIFIED | Tests admin/viewer; no matriz total/concurrencia |
| HMAC Chatwoot | PARTIALLY VERIFIED | Firma/timestamp tests; emisor vendor compatible; no e2e |
| Idempotencia webhook | PARTIALLY VERIFIED | Message ID secuencial; no delivery/concurrencia multiworker |
| CORS | PARTIALLY VERIFIED | Allowlist configurada; entorno real no probado |
| CSRF | NOT APPLICABLE | API usa Authorization header, no cookie de sesión propia |
| SQL injection | PARTIALLY VERIFIED | ORM/queries parametrizadas; sin DAST |
| XSS | PARTIALLY VERIFIED | React escapa y descripción Presta se limpia; sin browser test |
| Upload path/size | PARTIALLY VERIFIED | Roots, extensiones, tamaño y zip bomb; falta MIME/AV |
| Bridge container | VERIFIED | Usuario `app`, read-only, cap drop ALL, no-new-privileges |

## Hallazgos críticos/altos

### Integridad comercial

- **P0:** producto/precio/stock demo puede mostrarse como verificado.
- **P0:** `no acepto` puede crear pedido confirmado, reserva y borrador.
- **P0:** precio específico/variante/IVA no se aplica; stock oficial no se reserva.
- **P1:** aprobación y GHL idempotency tienen condiciones de carrera/estado parcial.

### Identidad, red y sesiones

- Runtime `development` evita validaciones de secretos/modos inseguros propias de staging.
- Rate limiter en memoria confía en `X-Real-IP`; `forwarded-allow-ips=*` permite spoof desde redes internas.
- No hay rate limit distribuido, account lock durable, MFA, `iss`/`aud` ni rotación de `AUTH_SECRET`.
- Token del portal en `sessionStorage`: cualquier XSS en el mismo origen lo puede leer. El portal no cierra sesión automáticamente tras 401.
- Proxy sin TLS real; configuración prod de ejemplo no monta certificado ni listener 443 funcional.
- Las redes internas bloquean egress por completo. Reduce SSRF accidental, pero no es una política allowlist utilizable.

### Contenedores/supply chain

- Proxy sin `SETUID` está roto y acumula procesos de health.
- Vendor, DB, Redis y Nginx Portal ejecutan como root por defecto; sin límites PID/CPU/RAM.
- Tags no son digests; override Ollama usa `latest`; no hay firma/provenance.
- `pypdf 5.9.0` y `Pillow 11.3.0` acumulan advisories actuales; procesan contenido subido.
- Vite/esbuild tienen 1 alta y 1 moderada en npm audit.
- Sin lock/hashes Python, SBOM o escaneo de imagen completado.

### RAG, prompt/tool injection y exfiltración

- Bloqueo de secretos por substrings es evadible con sinónimos/idiomas. Un documento permitido sin `allowed_roles` es legible por todos los roles de lectura.
- No hay sanitización de instrucciones dentro del documento, policy enforcement, DLP, clasificación ni reranker.
- `/agents/run` acepta prompt libre; no hay system policy ni output validation demostrados.
- `allowed_tools` no se aplica. Activepieces permite una ruta interna suministrada por operador y una API key potencialmente privilegiada.

### Secretos, logs y backup

- `.env` está ignorado, pero los secretos se guardan plaintext; ACL Windows no verificada y no hay secret manager.
- Scripts generan un recibo plaintext con contraseña inicial; PowerShell no endurece ACL explícitamente.
- Auditoría puede incluir payload/respuesta/PII sin redacción, inmutabilidad ni retención.
- Backup AES-CBC+checksum no equivale a integridad autenticada; no hay restore, offsite ni gestión de passphrase.

### Kill switches y observabilidad

- Coste estimado siempre 0: presupuesto diario no puede dispararse.
- No existe kill switch global durable para agentes/pedidos; el registro de agentes en memoria se pierde.
- Health DB degradado sigue devolviendo 200; no hay alertas ni SIEM/tracing.

## CSP y headers

- La plantilla proxy añade CSP y headers al portal, pero otros vhosts carecen de política equivalente.
- El Nginx interno del portal no añade CSP/Permissions-Policy; si se expone directamente pierde la defensa.
- OpenAPI/docs públicos amplían superficie e inventario de rutas.

## Priorización

1. Invariantes de catálogo/consentimiento/precio/stock.
2. Staging seguro, proxy/egress allowlisted, TLS y rate limit confiable.
3. Actualizar parsers/dependencias y generar SBOM/scan.
4. Idempotencia/outbox/locks y kill switches durables.
5. RAG/LLM policy, DLP, logs redactados y observabilidad.

## Archivos revisados, exclusiones y pendiente

Se aplicaron guías FastAPI y React, Bandit, pip/npm audit y revisión Docker. No hubo pentest, DAST, escaneo de imágenes ni pruebas ofensivas externas. Esas actividades están BLOCKED por runtime/recursos y requieren entorno aislado autorizado.
