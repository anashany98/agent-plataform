# Limitaciones conocidas

**Corte:** 2026-08-15. Estas limitaciones forman parte del contrato; no son funciones implícitas. La decisión vigente está en [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md).

## Limitaciones que bloquean la promoción actual

- No existe todavía un commit/tag limpio con imágenes, manifest, SBOM y checksums finales.
- No se ha ejecutado el perfil production final con certificado público/DNS/secretos del cliente.
- El E2E final de todos los módulos, restore integral, rollback y soak siguen pendientes.
- Quedan solo 16,9 GiB libres en `C:` durante la captura; 30 GiB es el margen recomendado.
- El scan final de secretos (incluida historia) y de todas las imágenes aún no está adjunto; Redis 7.2.14 sí tiene Trivy 0 HIGH/CRITICAL.

## Producto core

| Área | Limitación | Consecuencia/operación segura |
|---|---|---|
| Sesión Portal | JWT en `sessionStorage`, accesible a JavaScript del mismo origen | CSP estricta y XSS minimizan riesgo, pero una cookie HttpOnly/BFF sería preferible |
| MFA/SSO | No implementados | Usar contraseñas robustas, TTL corto y acceso de red restringido |
| Roles | Siete roles agrupados en admin/operator/read; no permisos por recurso | No asumir granularidad enterprise; revisar asignaciones |
| Facturación | Solo borrador y estado aprobado; sin emisión fiscal/contable | No enviar como factura legal ni afirmar cumplimiento fiscal |
| Pedidos | Registro local; automático desactivado | Confirmación humana/tokenizada; integrar autoridad externa por proyecto separado |
| Email | `EMAIL_PROVIDER=local` escribe JSON en spool; `smtp` (SMTP real) y `ghl` (GoHighLevel, T-083) entregan de verdad | Con `local`, `accepted=false`, entrega manual; `smtp`/`ghl` requieren credenciales y egress aprobado |
| SEO | Analiza estáticamente HTML proporcionado | Sin crawler, robots/sitemap remoto, monitoring continuo o Core Web Vitals |
| Wiki | Página única por slug, draft/preview/aprobación/publicación local | Sin espacios/colecciones, diff, restore de versiones o colaboración avanzada |
| Landing | Render determinista local tras aprobación | Sin hosting externo, dominio, formularios, analytics, A/B o rollback de sitio |
| Scheduler | Solo `automation_sweep`, intervalo 60s–30d | No scheduler/crawler genérico; toda activación requiere aprobación |
| RAG local | TF-IDF léxico, límite de chunks/corpus/features | Menor cobertura semántica; requiere corpus acotado y evaluación por cliente |
| OCR | Tesseract básico para imagen/PDF | No garantiza tablas, manuscrito, diagramas ni exactitud documental |
| Upload security | Path/size/type y parsers controlados | Sin antivirus/DLP externo; revisar documentos sensibles |
| Observabilidad | Métricas/alertas dentro del proceso y logs Docker | Reinicio pierde alert sink; no hay Prometheus/Grafana/SIEM/pager en core |
| Escalado | Un único proceso Uvicorn por contenedor | No certificado multiworker/multi-réplica; escalar solo tras pruebas de concurrencia |
| Almacenamiento | Volúmenes Docker locales | Sin object storage, replicación geográfica o HA |
| Alta disponibilidad | PostgreSQL/Redis únicos por instancia | Un fallo de host causa indisponibilidad hasta recuperación |
| Backups | Herramienta disponible; restore final pendiente | No declarar RPO/RTO hasta ensayo real |
| Privacidad/fiscalidad | Controles técnicos, sin certificación formal | Revisión legal, fiscal y de protección de datos por cliente/país |

## Integraciones y perfil `full`

- `production` no tiene egress ni proveedores LLM externos. Activarlos exige proxy/allowlist, DPA, precios, retries y E2E.
- PrestaShop y GHL son opcionales y no están certificados en la candidata core.
- Chatwoot, FlowWink y Activepieces del perfil `full` no están certificados para producción.
- Chatwoot contiene código `enterprise/` con licencia separada; no usar esas funciones sin licencia válida.
- Chatwoot requiere una excepción SSRF para alcanzar webhooks privados en algunos despliegues; el production core mantiene `CHATWOOT_ENABLED=false` y no concede esa excepción.
- Activepieces no tiene un flujo real de negocio certificado; Bridge debe seguir siendo autoridad de validación/aprobación.
- FlowWink es UI/diseño experimental y no es fuente de verdad.

## Restricciones explícitas de seguridad

- No publicar automáticamente Wiki, landings, SEO o contenido externo.
- No confirmar pedidos ni emitir facturas automáticamente.
- No tratar precio/stock sincronizado como tiempo real sin verificar la autoridad elegida.
- No presentar el spool de email como correo enviado.
- No usar datos demo, mocks, SQLite, `latest`, CORS abierto o secretos de ejemplo en producción.
- No mezclar `.env`, volúmenes, backups o manifests entre clientes.

Las limitaciones solo pueden cerrarse con implementación más evidencia; una decisión comercial no convierte un control pendiente en verificado.
