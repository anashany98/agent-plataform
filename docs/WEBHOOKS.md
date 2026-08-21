# Webhooks

## Principios comunes

- TLS válido y secreto único por instalación.
- Verificar autenticación antes de parsear o actuar sobre el evento.
- Rechazar replay o duplicados mediante timestamp/idempotencia.
- Registrar identificador y estado, nunca secretos ni cuerpo sensible completo.
- Responder rápido; efectos reintentables deben usar outbox/DLQ cuando aplique.
- No conceder permisos por campos del payload: la instalación y el rol proceden del contexto autenticado.

## Entrada desde Chatwoot

**Ruta:** `POST /webhooks/chatwoot`

**Disponibilidad:** solo al habilitar y certificar Chatwoot; `CHATWOOT_ENABLED=false` en core.

Headers obligatorios:

```http
X-Chatwoot-Timestamp: <unix-seconds>
X-Chatwoot-Signature: <hmac-sha256>
Content-Type: application/json
```

La firma se calcula sobre los bytes exactos:

```text
<timestamp>.<raw_body>
```

usando `CHATWOOT_WEBHOOK_SECRET`. El backend usa comparación constante y rechaza timestamps fuera de `WEBHOOK_TIMESTAMP_TOLERANCE_SEC` (300 s por defecto). Un proxy no debe reserializar el cuerpo antes de la verificación.

El flujo conversacional procesa principalmente `message_created`. La deduplicación se deriva de campos estables y autenticados del evento; un reintento no debe crear dos respuestas. Eventos no accionables pueden reconocerse sin ejecutar herramientas.

### Rotación

Coordine la rotación en una ventana corta: configure el nuevo secreto en emisor y receptor, envíe un evento canario y retire el anterior. La implementación actual expone un secreto primario; una rotación sin solapamiento puede causar rechazos, por lo que requiere ventana operativa.

## Entrada desde Activepieces

**Ruta:** `POST /webhooks/activepieces`

**Autenticación:** bearer JWT de un rol operativo.

**Idempotencia:** header obligatorio `Idempotency-Key`.

```http
POST /webhooks/activepieces
Authorization: Bearer <jwt>
Idempotency-Key: ap-run-<id-estable>
Content-Type: application/json
```

Esta ruta no utiliza la firma HMAC de Chatwoot. Repetir clave+payload debe devolver el resultado previo; cambiar el payload con la misma clave produce `409` y omitirla produce `428`.

Activepieces y su perfil `full` no están certificados en la candidata core.

## Disparo hacia un workflow

**Ruta:** `POST /workflows/trigger`

**Autenticación:** bearer de rol operativo.

**Idempotencia:** obligatoria.

El adaptador propaga la clave de idempotencia/correlación al destino. El caller debe tratar timeout como resultado desconocido y reintentar con la misma clave, nunca generar una nueva sin reconciliar.

## Salidas de automatización

Las salidas genéricas deben firmarse con `WEBHOOK_OUTBOUND_SECRET` e identificar la clave mediante `WEBHOOK_OUTBOUND_KEY_ID`. `WEBHOOK_OUTBOUND_ALLOWED_HOSTS` debe contener únicamente hosts aprobados. Bloquee direcciones loopback, link-local, metadata cloud, redes privadas no requeridas y redirecciones fuera de allowlist.

Contrato recomendado para un receptor:

```http
X-Bridge-Key-Id: primary
X-Bridge-Timestamp: <unix-seconds>
X-Bridge-Signature: <hmac-sha256>
X-Request-ID: <correlation-id>
```

El nombre exacto de headers y payload debe congelarse con un contract test de la versión antes de incorporar un receptor externo; no asumir este ejemplo como certificación del perfil `full`.

## Respuestas y retry

| Resultado | Conducta del emisor |
|---|---|
| 2xx | Confirmar procesamiento/deduplicación |
| 400/401/403/422 | No repetir ciegamente; corregir contrato/secretos |
| 409 | Reconciliar idempotencia o versión |
| 429 | Reintentar con backoff y jitter respetando `Retry-After` |
| 5xx/timeout | Reintentar con la misma clave y límite; luego DLQ/incidente |

Antes de habilitar un webhook real, pruebe firma inválida, timestamp viejo/futuro, cuerpo modificado, duplicado concurrente, timeout después del commit, 429, 5xx y aislamiento entre dos instalaciones.
