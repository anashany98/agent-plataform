# Integraciones y proveedores

## Política de despliegue

El perfil `production` core debe operar sin PrestaShop, GoHighLevel, Chatwoot, FlowWink ni Activepieces. No habilite `full` para resolver una carencia del core: cada integración añade egress, secretos, superficie legal y modos de fallo que requieren un gate separado.

| Dominio | Proveedor core | Alternativas presentes | Estado de candidata |
|---|---|---|---|
| Catálogo | local | PrestaShop | Local cubierto; PrestaShop no certificado |
| CRM | local | GoHighLevel | Local cubierto; GHL no certificado |
| Embeddings/RAG | `local_tfidf` | Ollama/OpenAI compatibles según configuración | Local cubierto parcialmente; externos no certificados |
| LLM | `none` | Ollama/OpenAI/Anthropic según router | Generación desactivada; externos no certificados |
| Email | spool local | Entrega externa futura | El spool no entrega mensajes |
| Conversaciones | ninguno | Chatwoot | `full` no certificado |
| Automatización visual | motor local limitado | Activepieces/FlowWink | `full` no certificado |
| Observabilidad | endpoints/logs locales | Prometheus/SIEM/pager | Destinos externos pendientes |

## Proveedores locales

Los proveedores local de catálogo y CRM persisten datos en la base de la instalación y permiten que el core sea funcional sin SaaS. RAG TF-IDF mantiene sus índices/corpus en el ámbito de la instalación. El email local escribe JSON en un spool con ruta derivada mediante hash del tenant y retención configurada; devuelve `accepted=false` y estado `queued_for_manual_delivery`.

El operador debe implementar una cola humana de entrega o aceptar que no saldrá correo. Nunca interpretar la creación de un archivo de spool como entrega, aceptación SMTP o lectura del destinatario.

## Chatwoot

- Entrada `POST /webhooks/chatwoot` autenticada con HMAC y ventana temporal.
- La firma cubre `<timestamp>.<raw_body>`; los headers son `X-Chatwoot-Signature` y `X-Chatwoot-Timestamp`.
- Deduplicación por identidad estable del evento/conversación.
- Procesamiento principal de `message_created`; otros eventos pueden reconocerse sin ejecutar el flujo conversacional.
- Respuesta/handoff dependen de API token y team/assignee configurados.

En core, `CHATWOOT_ENABLED=false`. La variante vendor contiene componentes con condiciones de licencia distintas y necesita revisión legal, SSRF/egress, secretos, carga y E2E.

## Activepieces

`POST /webhooks/activepieces` es una entrada autenticada con JWT de rol operativo y `Idempotency-Key`; no usa el esquema HMAC de Chatwoot. `POST /workflows/trigger` crea un disparo idempotente hacia el adaptador y propaga una clave de correlación. El API key de Activepieces es un secreto independiente.

La imagen está fijada por digest en infraestructura, pero el perfil `full`, su licencia efectiva y el recorrido completo no están certificados.

## FlowWink

El código vendor está fijado al commit `0cd4e9b8af0d432c9a942a692d8f1fa4a04ec67b` y declara MIT en el checkout auditado. Su pin evita deriva, pero no demuestra build, seguridad ni compatibilidad del perfil `full` final.

## PrestaShop

Expone consulta de productos, sincronización e historial. La activación exige URL permitida, credenciales, timeout/retry, prueba de paginación, mapeo de IDs externos, reconciliación y límites de egress. La identidad local por `source/external_id` evita mezclar fuentes, pero debe probarse con datos del cliente.

## GoHighLevel

El adaptador (T-083) cubre entrada y salida:

- **Entrada**: `POST /webhooks/gohighlevel` recibe eventos `ContactCreate`,
  `ContactUpdate`, `FormSubmit` y `OpportunityCreate`/`OpportunityUpdate`
  firmados con `X-Hub-Signature-256` (HMAC-SHA256 del body crudo con
  `GHL_WEBHOOK_SECRET`; sin secreto → 401 fail-closed). Alimentan el CRM
  local (leads/oportunidades idempotentes por `external_reference` = id GHL)
  con anti-replay por clave de idempotencia.
- **Salida**: el CEO agent propone (deny-by-default) crear contactos y
  enviar SMS/email; al aprobarse (humano o autonomía autorizada) el efecto
  se encola en el outbox durable (`ghl.create_contact`/`ghl.send_message`)
  con reintentos, circuito y DLQ, y el dispatcher entrega con el patrón
  D-010 (upsert del contacto + checkpoint).
- **Email**: con `EMAIL_PROVIDER=ghl` el router de email (plantillas,
  campañas, notificaciones de automatizaciones) entrega de verdad por la
  API de mensajes de GHL (`GhlEmailProvider`: upsert del contacto por email
  + `type=email`). El tracking de apertura/clic del portal funciona igual
  que con SMTP (el HTML lleva el pixel y los clics reescritos). Sin GHL, el
  proveedor falla cerrado (`ghl_not_configured`) y, si está activo
  `EMAIL_FALLBACK_TO_LOCAL_SPOOL`, la degradación al spool local es auditada
  — el spool sigue existiendo y nunca se usa como entrega primaria.
- **Notificaciones de automatización con HTML+tracking (T-083b)**: los
  recordatorios de presupuesto, dunning, alerta de stock y carrito
  abandonado salen por defecto con plantilla HTML de marca (acento de la
  instalación, pixel de apertura y clics reescritos) y evento `sent` por
  token cuando `EMAIL_PROVIDER=ghl` y hay `EMAIL_TRACKING_BASE_URL` con el
  tracking activo en el panel. Sin base URL o con tracking desactivado el
  envío GHL sigue ocurriendo en texto plano y se audita
  `automation.email.tracking_skipped` (motivo explícito). Con `local`/`smtp`
  el comportamiento no cambia.
- **Reintento con backoff y DLQ en envíos de campaña (T-083c)**: si GHL
  falla a mitad del envío, los destinatarios con error transitorio
  (`ghl_error:*`) se reencolan en el outbox durable (`campaign.deliver`, en
  la misma transacción), la campaña pasa a `pending_retry` y el worker
  reintenta con backoff exponencial; al entregar, el destinatario pasa a
  `sent` y la campaña vuelve a `sent`. Al agotar el presupuesto de
  intentos, el mensaje cae a la DLQ con motivo claro (reencolable por
  `POST /outbox/{id}/retry`) y el destinatario queda `failed`. Un error
  permanente (GHL sin configurar, plantilla eliminada) falla de inmediato y
  honesto sin ocupar la cola. El reenvío de una campaña en `pending_retry`
  es idempotente. Las campañas no usan la degradación a spool local
  (`provider_fallback=False`): su resiliencia es el reintento/DLQ.

Requiere secreto, endpoint autorizado, idempotencia, tratamiento de
4xx/5xx/timeout y reconciliación. El CRM local sigue siendo la ruta de
rollback. La integración sigue **no certificada** hasta cerrar el checklist
de los ocho puntos; el estado punto por punto y las pruebas E2E necesarias
están en [`GHL_CERTIFICATION_CHECKLIST.md`](GHL_CERTIFICATION_CHECKLIST.md).

## Webhooks salientes

El motor de automatizaciones incluye secreto HMAC, identificador de clave y allowlist de hosts para salidas. En producción, la allowlist debe ser explícita, sin IPs privadas/metadata ni redirecciones fuera de destino; la rotación debe admitir una ventana controlada y quedar auditada.

## Checklist de certificación por integración

1. Licencia, DPA, región, retención y subprocesadores aprobados.
2. Secretos únicos por cliente y mínimo privilegio.
3. DNS/hosts allowlist y egress negado por defecto.
4. Firma/autenticación, anti-replay e idempotencia verificadas.
5. Timeouts, retry con backoff y circuit breaker sin duplicados.
6. Métricas, alertas, DLQ/reconciliación y runbook.
7. Prueba A/B de aislamiento y payload malicioso.
8. Carga, restore y rollback al proveedor local.

Hasta cerrar los ocho puntos en la candidata, la integración conserva estado **no certificada**.
