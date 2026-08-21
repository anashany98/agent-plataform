# Borrador — informe final de seguridad

> **DRAFT / NO CERTIFICADO.** Baseline detallado en [SECURITY.md](SECURITY.md) y amenazas en [THREAT_MODEL.md](THREAT_MODEL.md).

## Identidad de evaluación

| Campo | Valor |
|---|---|
| Versión/commit/imágenes | PENDING |
| Perfil | `production` core |
| Alcance externo | Portal + API detrás de TLS |
| Herramientas/versiones | PENDING |
| Fecha/evaluador | PENDING |

## Controles implementados

- JWT con expiración, `jti`, instalación, rol y `token_version`.
- PBKDF2, política de contraseña y cambio inicial.
- RBAC backend y aislamiento por instalación en ORM/esquema.
- Idempotencia, leases y control optimista `If-Match`.
- Aprobaciones para acciones sensibles y tools de agente deny-by-default.
- HMAC/anti-replay de Chatwoot; allowlist/HMAC para salidas.
- TLS/proxies, contenedores read-only/no-new-privileges y redes segmentadas.
- Core sin egress, LLM externos, vendors, demo o mocks.
- Uploads limitados, raíces permitidas, saneado HTML/CSP y RAG ACL.
- Backup cifrado con HMAC/checksums y validación de identidad/rutas.

Su existencia debe revalidarse en las imágenes finales; no convierte este borrador en PASS.

## Gates de seguridad

| Gate | Estado | Evidencia |
|---|---|---|
| Secret scan árbol e historia | PENDING | |
| Secret scan bundle/capas/logs | PENDING | |
| Trivy OS/deps por imagen final | PARTIAL | Redis 7.2.14: 0 HIGH/CRITICAL; resto PENDING |
| SBOM/firmas/checksums | PENDING | |
| TLS público/SAN/cadena/ciphers | PENDING | |
| Headers/CSP/CORS/hosts | PENDING | |
| RBAC y tenant A/B runtime | PENDING | |
| Webhook firma/replay/SSRF | PENDING | |
| Upload traversal/bomb/content | PENDING | |
| Prompt injection/exfil/tool abuse | PENDING | |
| Backup tamper/cross-client | PENDING | |
| Alerting y respuesta a incidente | PENDING | |
| Licencias/vendors | PENDING | |

## Riesgos residuales obligatorios

| Riesgo | Tratamiento requerido |
|---|---|
| JWT en `sessionStorage`; sin MFA/SSO | CSP estricta, acceso de red, cuentas nominales; roadmap de auth |
| Alertas/métricas solo locales | integrar receptor/SIEM/pager y probar entrega |
| RAG/OCR sin AV/DLP externo | limitar fuentes, revisión humana y sandbox/proceso de malware |
| Email spool sin delivery | custodia/retención/proceso manual explícito |
| Vendors `full` no certificados | mantener fuera de core; gate legal/técnico separado |
| SEO/publicación solo local | comunicación honesta; sin egress |

## Hallazgos/waivers

| ID | Severidad | Activo afectado | Hallazgo | Remediación/waiver | Owner/fecha |
|---|---|---|---|---|---|
| PENDING | | | | | |

## Veredicto Security

**PENDING.** Con Trivy, secret scan y pruebas runtime sin ejecutar no se autoriza producción.
