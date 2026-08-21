# Certificación de la integración GoHighLevel — checklist de 8 puntos

**Alcance:** adaptador GHL de entrada (`POST /webhooks/gohighlevel`) y salida
(`GHLAdapter`: upsert de contacto, oportunidad, nota, `send_sms`/`send_email`;
acciones del CEO agent `ghl_send_message`/`ghl_create_contact` con entrega vía
outbox durable). Ver `docs/INTEGRATIONS.md` (sección GoHighLevel) y
`docs/CEO_AGENT_CAPABILITIES.md`.

**Regla del proyecto:** hasta cerrar los ocho puntos en la candidata, la
integración conserva estado **no certificada**. Este documento es el registro
de evidencia: para cada punto, qué hay implementado hoy (con referencia a
código y tests), qué falta y **qué pruebas E2E harían falta para cerrarlo**.

Leyenda de estado: ✅ implementado y con test · 🟡 parcial (hay base, falta
cierre) · ❌ pendiente.

---

## 1. Licencia, DPA, región, retención y subprocesadores

**Naturaleza:** gate legal/de compras, no de código. La certificación exige
documento firmado, no una prueba automatizada.

**Estado actual:** ❌ sin evidencia adjunta. No hay documento de
procesamiento de datos, región de residencia ni retención revisados para GHL.

**Qué falta / decisiones a tomar:**

- DPA de GoHighLevel firmado para el cliente (y revisión de subprocesadores).
- Región de datos de la subcuenta (GHL ofrece residencia US/EU según plan):
  elegir una y fijarla en la config del cliente (`GHL_BASE_URL` por región).
- Retención de datos personales: revisar las políticas de retención de GHL
  frente a la política de retención de la instalación (leads, mensajes,
  oportunidades) y documentar el solapamiento.
- Mapeo de datos enviados a GHL: inventario exacto de campos que salen
  (email, nombre, teléfono, empresa, contenido de SMS/email, referencias
  externas) para la revisión legal — nunca credenciales ni datos de auditoría.

**Pruebas E2E para cerrar (no técnicas):**

- Adjuntar DPA + lista de subprocesadores con fecha de revisión.
- Adjuntar decisión de región y evidencia de que la subcuenta está en ella
  (p. ej. `locationId` de una subcuenta de la región elegida).
- Adjuntar revisión de retención firmada.

---

## 2. Secretos únicos por cliente y mínimo privilegio

**Estado actual:** 🟡. Los secretos son variables de entorno de la
instalación (`GHL_API_TOKEN`, `GHL_WEBHOOK_SECRET` en `app/config.py`),
únicas por despliegue — que en este producto es el modelo por cliente. El
token se usa solo para llamadas salientes y el secreto solo para verificar
firmas de entrada; el adaptador nunca los devuelve ni los audita
(`redact_for_log` en observabilidad). Falta el ciclo de vida.

**Qué falta:**

- Rotación con ventana controlada: soportar dos claves vigentes a la vez
  (una en uso, una entrante) y auditoría de cada rotación.
- Mínimo privilegio demostrado: la clave de GHL debería tener solo los
  scopes necesarios (contactos, oportunidades, mensajes) y estar acotada a
  la `locationId` del cliente — revisar qué scopes permite GHL por API key
  y fijar los mínimos en la guía de aprovisionamiento.
- Verificación de que ningún secreto aparece en logs, respuestas de error,
  métricas ni payloads de outbox (el payload de outbox puede persistir en la
  DLQ: nunca debe contener el token).

**Pruebas E2E para cerrar:**

- Rotación: con `GHL_API_TOKEN` nuevo, el adaptador sigue autenticando tras
  la ventana; la clave antigua deja de funcionar y la rotación queda en el
  audit log (`AuditLog`).
- Escaneo de secretos en el repositorio y en una captura de logs de 24 h con
  GHL activo (grep del prefijo del token en `docker logs`, respuestas de
  `/outbox` y DLQ).
- Test de que un error 401/403 de GHL no expone el token en la respuesta del
  API (contrato del endpoint).

---

## 3. DNS/hosts allowlist y egress negado por defecto

**Estado actual:** 🟡. `GHL_BASE_URL` es configurable (default
`services.leadconnectorhq.com`) y el adaptador llama siempre a esa URL; el
motor de webhooks salientes sí tiene allowlist explícita
(`WEBHOOK_OUTBOUND_ALLOWED_HOSTS` + `_assert_outbound_url_allowed`), pero el
adaptador GHL **no** valida su base URL contra una allowlist propia.

**Qué falta:**

- Validar `GHL_BASE_URL` al arranque contra una allowlist explícita (host
  exacto de GHL de la región elegida) y fallar cerrado si no coincide
  (misma política que los webhooks salientes: sin IPs privadas, loopback,
  link-local, multicast ni redirecciones fuera de destino).
- Egress de red: en el despliegue del cliente, firewall/allowlist a nivel de
  red que solo permita salida a los rangos/hosts de GHL de la región
  (documentar los rangos en el runbook de despliegue).

**Pruebas E2E para cerrar:**

- Con `GHL_BASE_URL` apuntando a una IP privada, loopback o host ajeno
  (`http://127.0.0.1`, `http://192.168.x.x`, `http://malicioso.invalid`), el
  arranque o la primera llamada fallan cerrado sin tocar la red (extender el
  patrón de `test_ghl_adapter_open_circuit_fails_without_network`).
- Con la allowlist correcta, una llamada real al sandbox de GHL
  (`GET /locations/{id}` o un upsert de prueba) funciona.
- Verificación en el entorno del cliente de que el egress de red solo
  permite el destino GHL elegido (captura de conexiones o firewall policy).

---

## 4. Firma/autenticación, anti-replay e idempotencia verificadas

**Estado actual:** ✅ con gaps documentados.

- Entrada: firma `X-Hub-Signature-256` (HMAC-SHA256 del body crudo) verificada
  con `GHL_WEBHOOK_SECRET`; sin secreto o firma inválida → 401 fail-closed
  (`verify_ghl_signature`). Anti-replay por clave de idempotencia
  `ghl-inbound:<evento>:<id>`: un replay devuelve la respuesta cacheada sin
  repetir el efecto (test: `test_ghl_contact_create_webhook_creates_lead_and_is_idempotent`).
- Salida: autenticación Bearer; idempotencia por **reconciliación** D-010
  (GHL no acepta claves de idempotencia): oportunidades y notas se buscan
  por referencia externa antes de crearlas
  (`find_opportunity_by_reference`/`find_note_by_body`, tests en
  `test_p1_ghl_reconciliation.py`); `upsert_contact` es idempotente por email
  en GHL; los envíos de mensaje checkpointean el contacto y el envío en el
  outbox.

**Gap conocido (documentar, no ocultar):** en `send_sms`/`send_email` no hay
reconciliación previa del mensaje (GHL no la ofrece), así que un crash entre
el envío y el checkpoint puede **duplicar** un mensaje. La microventana es
pequeña y la duplicación es idempotente en el sentido de que un SMS repetido
es visible para el cliente — debe aceptarse explícitamente o mitigarse.

**Qué falta:**

- Decisión documentada sobre el doble envío (aceptar el riesgo residual con
  mitigación, p. ej. dedupe por contenido/ventana de tiempo en el portal) y
  su justificación.
- Probar el anti-replay de entrada con eventos con el mismo `id` pero
  payload distinto → 409 (ya lo cubre `_claim_idempotency` con fingerprint;
  falta el test GHL concreto).

**Pruebas E2E para cerrar:**

- Replay del mismo evento firmado → misma respuesta cacheada, un solo lead
  (test existente).
- Replay con mismo `id` y payload modificado → 409.
- Webhook sin firma / con firma caducada / con secreto equivocado → 401.
- Inyección de crash entre `create_opportunity`/`add_note` y su checkpoint →
  el reintento reutiliza el efecto existente (tests existentes); añadir el
  mismo fault-injection para `send_sms` y documentar el resultado (esperado:
  posible duplicado, registrado como desviación en `AgentDecision`).

---

## 5. Timeouts, retry con backoff y circuit breaker sin duplicados

**Estado actual:** ✅ con ajustes pendientes.

- Timeout HTTP 20 s por llamada (`httpx.AsyncClient(timeout=20.0)` en
  `ghl_adapter.py`).
- Retry acotado con backoff exponencial + jitter y honor de `Retry-After`
  (`request_with_retry`; reintenta 408/425/429/5xx; los 4xx cuentan como
  liveness del proveedor). Tests: `test_ghl_retries_rate_limit_before_failing`,
  `test_ghl_adapter_open_circuit_fails_without_network`.
- Circuit breaker por proveedor (`ghl`) con threshold, half-open y
  recuperación (tests en `test_p1_resilience.py`).
- Outbox durable: reintentos acotados con backoff determinista y DLQ tras
  `max_attempts` (tests: `test_outbox_transient_failures_schedule_backoff_then_dlq`,
  `test_outbox_permanent_failure_goes_directly_to_dlq`).

**Qué falta / decisiones:**

- Revisar el timeout de 20 s frente a la latencia observada de GHL en la
  región elegida (ajustar si la cola de mensajes de GHL es lenta) y fijar
  los valores de `INTEGRATION_RETRY_*` por despliegue.
- Confirmar que un fallo del breaker del proveedor nunca silencia el
  reintento del outbox (el outbox gobierna cuándo, el breaker solo acorta la
  llamada) — ya es el diseño; falta la prueba de integración combinada.

**Pruebas E2E para cerrar:**

- GHL responde 429 con `Retry-After` → el retry espera ese tiempo y no antes
  (test existente, ampliarlo con el valor de `Retry-After`).
- GHL caído (conexión rechazada) durante N llamadas → el breaker abre, la
  siguiente llamada falla rápido sin red y el outbox programa el reintento
  (test existente `test_webhook_ghl_outage_queues_lead_and_outbox_recovers`).
- Sin duplicados: tras un reintento exitoso de `upsert_contact` +
  `create_opportunity`, en GHL hay exactamente un contacto y una oportunidad
  (tests D-010 existentes).
- Soak corto: 100 operaciones mixtas (contactos, oportunidades, mensajes)
  contra el sandbox con latencias registradas — sin errores no reintentables
  y sin duplicados en contactos/oportunidades.

---

## 6. Métricas, alertas, DLQ/reconciliación y runbook

**Estado actual:** 🟡.

- Métricas: eventos del circuit breaker por proveedor
  (`bridge_circuit_breaker_events_total{provider="ghl"}`) y regla de alerta
  `circuit_breaker_open` (in-memory; Prometheus pendiente por política core).
- DLQ del outbox con reencolado manual (`retry_dead`) y auditoría
  (`outbox_dead`, `outbox_requeued`).
- Runbook: existe `docs/INCIDENT_RESPONSE.md` general; falta el específico de
  GHL.

**Qué falta:**

- Métricas GHL específicas: latencia y tasa de error por endpoint
  (upsert/create/send), contador de DLQ por topic `ghl.*`, y alerta cuando
  la DLQ de GHL tenga mensajes (no solo el breaker abierto).
- Runbook `GHL` dentro del plan de incidentes: síntomas (breaker abierto,
  DLQ creciente, webhooks 401), diagnóstico (revisar `all_breaker_states`,
  `/outbox?state=dead&topic=ghl.send_message`), y acciones
  (reencolar DLQ, rotar token, fallback a proveedor local).
- Documentar la reconciliación como operación: qué pasos existen (D-010 en
  creación de oportunidad/nota) y cuál es el proceso manual de
  reconciliación de leads cuando hay que re-sincronizar.

**Pruebas E2E para cerrar:**

- Inyectar fallo en GHL → confirmar métrica `bridge_circuit_breaker_events_total`
  incrementada con `provider="ghl"` y alerta `circuit_breaker_open` emitida
  (patrón de `test_p1_observability.py` aplicado a GHL).
- Llevar un mensaje `ghl.send_message` a DLQ (GHL no configurado) → aparece
  en `/outbox?state=dead` con `last_error` claro; `retry_dead` lo reencola y
  entrega al configurar GHL.
- Ensayo del runbook: recrear los tres síntomas (breaker abierto, DLQ,
  webhooks 401) y ejecutar el runbook de principio a fin en staging,
  registrando el tiempo de recuperación.

---

## 7. Prueba A/B de aislamiento y payload malicioso

**Estado actual:** 🟡.

- Aislamiento: leads/oportunidades/outbox/aprobaciones son
  `InstallationOwnedMixin`; el endpoint de webhook aplica dentro de la
  instalación activa (`installation_scope`). Falta la prueba A/B de dos
  instalaciones con GHL.
- Payload malicioso: `parse_ghl_webhook` es tolerante (tipos, campos
  ausentes) y no evalúa nada; falta la batería de payloads hostiles.

**Qué falta / pruebas E2E para cerrar:**

- **A/B de aislamiento**: dos instalaciones (A y B) en el mismo despliegue;
  enviar el mismo evento GHL a la instalación A → el lead aparece solo en A
  (extender el patrón de `isolated_api` con dos instalaciones). Repetir con
  oportunidad, outbox y aprobación.
- **Payload malicioso** (todos con firma válida):
  - Evento desconocido (`FunnelCreated`) → `ignored` auditable (test
    existente).
  - `data` con tipos erróneos (`monetaryValue: "abc"`, `data` como lista,
    `email` numérico) → 200 con `status=ignored`/`reason`, nunca 500 ni
    efectos a medias.
  - Campos con URLs/scripts en `customFields` o `companyName` → se
    almacenan como datos, nunca se interpretan (sin XSS en el portal por
    render de estos campos — verificar el render en el portal).
  - Cuerpo gigante (> límite) → 413/400 controlado sin OOM.
  - JSON con `type` ausente → `ignored` o 400, nunca crash.
- Verificar que un payload con `email` de otra instalación no cruza el
  aislamiento (dedupe por instalación, no global).

---

## 8. Carga, restore y rollback al proveedor local

**Estado actual:** 🟡.

- Rollback: el proveedor local (`LocalCRMProvider`) es el default sin GHL y
  cubre el mismo contrato (`CRM_PROVIDER=auto` → GHL si está configurado,
  si no local); el core funciona sin GHL (política `production`). Tests:
  `test_p1_local_providers.py`.
- Carga: no hay ensayo de carga ni de ráfagas de webhooks.
- Restore: la herramienta de backup existe; el ensayo de restore con datos
  GHL no se ha hecho.

**Qué falta / pruebas E2E para cerrar:**

- **Carga / ráfaga**: enviar 1 000 webhooks GHL en ráfaga (p. ej. 100/s
  durante 10 s) contra el endpoint → todos procesados o encolados sin
  pérdida; la idempotencia mantiene un efecto por evento; la DLQ no crece
  sin causa; medir latencia p95 del endpoint y del outbox.
- **Restore**: backup cifrado integral → restore en instalación vacía →
  los leads/oportunidades de origen GHL siguen referenciados por su
  `external_reference` (sin duplicar al re-sincronizar con GHL).
- **Rollback / failover**: con GHL configurado y caído → la lectura del CRM
  sirve desde el proveedor local (o falla cerrado según política elegida) y
  las escrituras quedan en el outbox; al restaurar GHL, el outbox drena y
  **no** hay duplicados de contactos/oportunidades (reconciliación D-010).
- **Conmutación a local**: desactivar GHL (`GHL_API_TOKEN=""`) → todo el
  flujo CRM funciona con `LocalCRMProvider` sin cambios de comportamiento
  (tests existentes) y sin mensajes GHL huérfanos en la DLQ.

---

## Resumen de estado

| # | Punto | Estado | Bloquea certificación |
|---|-------|--------|----------------------|
| 1 | Licencia/DPA/región/retención | ❌ sin evidencia | Sí |
| 2 | Secretos por cliente y rotación | 🟡 base, falta ciclo de vida | Sí |
| 3 | Allowlist y egress | 🟡 falta validar `GHL_BASE_URL` | Sí |
| 4 | Firma/anti-replay/idempotencia | ✅ (gap de doble envío a decidir) | Sí (decisión documentada) |
| 5 | Timeouts/retry/breaker | ✅ (afinar valores por región) | No |
| 6 | Métricas/alertas/DLQ/runbook | 🟡 falta runbook y métricas GHL | Sí |
| 7 | Aislamiento y payload malicioso | 🟡 falta batería de tests | Sí |
| 8 | Carga/restore/rollback | 🟡 faltan ensayos | Sí |

**Definición de «cerrada»:** cada punto ✅ con evidencia adjunta (test en el
repo o artefacto firmado) y un ensayo E2E ejecutado contra el sandbox/candidata
del cliente. Hasta entonces, el estado oficial de la integración es **no
certificada** (`docs/INTEGRATIONS.md`) y el perfil `production` debe operar sin
GHL.
