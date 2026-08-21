# Propuesta de arquitectura — Agente de escucha social (Instagram, WhatsApp, Facebook, LinkedIn, X)

**Estado:** propuesta de diseño (sin implementar).
**Fecha:** 2026-08-17.
**Origen:** idea recogida en sesión de producto («molaría un agente que revise el
Instagram, WhatsApp, Facebook, LinkedIn, X…») y registrada como módulo de
adquisición en `docs/MANUAL_RECORRIDO_APP.pdf` (§6, módulos futuros).
**Referencias:** `docs/HANDOFF_CONTINUACION_CRM.md` (§5 patrones, §8 definición
de «hecho»), `docs/BUSINESS_MODULES.md`, `docs/PRODUCT_PLAN_CRM_B2B.md`,
`docs/PITCH_COMERCIAL.md`, `docs/ARCHITECTURE_SAAS_MULTI_TENANT.md`.

---

## 1. Resumen ejecutivo

**Qué es:** un módulo que convierte las menciones y los mensajes directos de las
redes sociales en **leads, actividades y seguimientos dentro del CRM existente**,
con triaje automático y priorización en el pipeline.

**Qué NO es:** no es un bot que contesta en nombre de la empresa ni un social
media manager. Es un **receptor de escucha + orquestador de trabajo comercial**:
trae el mensaje al portal, lo clasifica, crea/actualiza el lead, programa la
actividad y lo prioriza para que el comercial responda desde el CRM. La
respuesta al cliente puede ser manual (recomendada v1) o asistida con borrador
IA (v2, siempre con aprobación humana).

**Por qué encaja:** el pipeline del CRM ya se alimenta de transacciones reales
(chat, web, formularios). Las redes son la **última fuente sin conectar**:
menciones de marca, DMs con intención de compra, quejas públicas, leads de
WhatsApp. La infraestructura necesaria YA existe (webhook HMAC, outbox durable,
idempotencia, DLP, `_lead_score`, actividades, spool de email, RBAC): el módulo
es una capa de ingesta + triaje sobre ella, no un rewrite.

**Principio de honestidad (igual que el resto del producto):** los canales que
requieren cuentas de vendor, revisión de Meta o certificación se venden como
fase con criterios de salida, nunca como «conectado y certificado» hoy. En
concreto: X ya **no tiene free tier** (API de pago por uso desde 2026) y
LinkedIn restringe el acceso a DMs; WhatsApp y Meta requieren app de
desarrollador y revisión de permisos. El módulo se diseña **driver-agnóstico**:
un canal puede estar activo y otro pendiente sin bloquear el resto.

---

## 2. Objetivo y alcance

| Dimensión | Definición |
|---|---|
| **In** | Mensajes entrantes por canal: WhatsApp, Instagram (DMs + menciones), Facebook (Messenger + publicaciones de la página), LinkedIn (DMs de página/empresa), X (menciones + DMs) |
| **Proceso** | Deduplicación → DLP/seguridad → triaje (intención, idioma, sentimiento, entidades) → crear/actualizar lead → actividad de seguimiento → priorizar en la cola del kanban → (v2) borrador de respuesta con aprobación |
| **Out** | Lead con `source=social`, `score` con señales sociales, actividad de tipo `follow_up`, timeline en la ficha, evento saliente `social.message_triaged` por webhook, alerta por email/spool al comercial asignado |
| **Fuera de alcance (v1)** | Publicación/planificación de contenido, métricas de alcance/engagement histórico, bots autónomos, respuesta automática sin aprobación, ingestión de mensajes de clientes ajenos a la instalación |
| **Modelo de entrega** | Igual que el resto: por instancia gestionada, canales activados por el admin de la instalación con credenciales del cliente |

---

## 3. Estado actual y patrones que se reutilizan (no reinventar)

| Patrón existente | Dónde está | Uso en este módulo |
|---|---|---|
| Webhook entrante con firma HMAC | `main.py` (`verify_hmac_signature`, patrón Chatwoot `X-Chatwoot-Signature`) | Verificación de cada canal (Meta `X-Hub-Signature-256`, WhatsApp same, X `X-Twitter-Webhooks-Signature`, LinkedIn `X-Li-Signature`) |
| Outbox durable + DLQ + reintentos | `app/services/outbox.py` (`OutboxService.enqueue`, claim CAS, backoff) | El mensaje social se encola en la **misma transacción** que la mutación del lead; un crash nunca lo pierde ni lo duplica |
| Idempotencia por clave | `_begin_idempotent_mutation` / `IdempotencyRecord` | Dedupe por `source_message_id` del canal (retry de Meta/X llega repetido) |
| DLP y clasificación en ingesta | `app/services/rag_security.py` (normalize/effective_classification) | Escanear el texto del mensaje social (tarjetas, DNI, secretos) y no persistir/redactar |
| Modelo Lead + dedupe | `models.py::Lead` (email único, `external_reference` única, merge T-054) | El mensaje crea lead si no existe el contacto; merge reutilizable si el mismo usuario llega por otro canal |
| Scoring determinista | `main.py::_lead_score` + cola ordenada del board | Añadir señales sociales (canal, intención, sentimiento, urgencia) manteniendo el score determinista |
| Actividades de comercial | `models.py::Activity` + recordatorio por email/spool | La triage crea `follow_up` con `due_at` y `remind_at` para el comercial |
| Timeline de interacción | `GET /leads/{id}/timeline` (T-046) | El mensaje social entra como evento «mensaje social: texto + canal + enlace» |
| RBAC + auditoría | `_audit`, `require_roles` | Lectura del inbox y configuración de canales por rol; cada mensaje triageado queda auditado |
| Ciclo de vida / RGPD | export/erase/legal hold + `email_opt_out` (T-055) | El canal social respeta el opt-out y entra en la exportación/borrado de la instalación |
| Endpoints idempotentes | patrón `create_customer`/`create_campaign` | `POST /social/webhook/{channel}` y `POST /social/channels` |
| Portal por sección | `portal/src/*.tsx` + tabs en Clientes | Nueva sección «Escucha social» (admin: canales; operadores: inbox) |

---

## 4. Arquitectura

```
 Redes sociales
   WhatsApp Cloud API ─┐
   Instagram Graph API ─┤   webhooks HTTPS firmados
   Facebook Messenger ─┼────────────────────────────┐
   LinkedIn API        ─┤                           │
   X API v2            ─┘                           ▼
                                    ┌────────────────────────────────┐
                                    │ POST /social/webhook/{channel} │
                                    │  · verify_hmac_signature       │
                                    │  · deserializar payload canal  │
                                    └──────────────┬─────────────────┘
                                                   ▼
                                    ┌────────────────────────────────┐
                                    │ Ingesta (misma transacción)    │
                                    │ 1. dedupe por source_message_id │
                                    │ 2. DLP: redactar/descartar      │
                                    │ 3. persistir SocialMessage      │
                                    │ 4. outbox.enqueue(triage)       │
                                    └──────────────┬─────────────────┘
                                                   ▼
                                    ┌────────────────────────────────┐
                                    │ Triaje (worker outbox)         │
                                    │ · intención: lead / queja /     │
                                    │   consulta / spam / otra        │
                                    │ · idioma + registro             │
                                    │ · entidades (email, tel, marca) │
                                    │ · sentimiento + urgencia        │
                                    │ · score social determinista     │
                                    └──────────────┬─────────────────┘
                                                   ▼
                                    ┌────────────────────────────────┐
                                    │ Orquestador CRM                │
                                    │ · upsert Lead (source=social)  │
                                    │ · Activity follow_up + remind  │
                                    │ · timeline event               │
                                    │ · webhook saliente             │
                                    │   social.message_triaged       │
                                    └──────────────┬─────────────────┘
                                                   ▼
                                    Cola del kanban (priorizada por score)
                                    + alerta email/spool al comercial
                                    + portal «Escucha social» (inbox)
```

**Decisiones clave de diseño:**

1. **El webhook solo persiste; la triage va por el outbox.** El handler del
   canal responde 200 lo antes posible (Meta/X reintentan si tardamos) y encola
   el trabajo; el worker procesa con reintentos y DLQ. Un crash entre persistir
   y triagear se recupera (mismo patrón que Chatwoot/GHL).
2. **La triage es determinista primero, LLM opcional después.** La intención
   base, el idioma y el score salen de reglas deterministas (invariante del
   proyecto: el score del CRM nunca depende de la red). El LLM (si está
   configurado, con `ALLOW_MOCK_LLM`/proveedor estándar) enriquece: resumen,
   entidades, matiz de sentimiento. La salida del LLM se **valida con
   restricciones** (longitud, formato) y nunca decide financiero.
3. **Un contacto, un lead.** La deduplicación cruza `email`/`phone` con los
   leads existentes; si ya existe, el mensaje se añade como evento de timeline y
   actividad, sin duplicar. Si el mismo usuario llega por dos canales, el merge
   de T-054 lo unifica.
4. **El canal es una fuente más del score.** `_lead_score` gana señales
   «sociales» (intención de compra +15, queja pública +10, canal WhatsApp +10,
   urgencia +5) con pesos fijos documentados; el orden de la cola del kanban
   sigue siendo determinista y explicado.
5. **Consentimiento y opt-out.** Un mensaje social NO autoriza email marketing:
   la creación del lead respeta `email_opt_out` y el recordatorio se envía solo
   si el lead no optó fuera. La exportación/erase del ciclo de vida incluye los
   mensajes sociales.

---

## 5. Modelo de datos (propuesta, migración `0023_social`)

```text
social_channels                social_messages              social_triage
-----------------              -----------------           ----------------
id (pk)                        id (pk)                      id (pk)
installation_id                installation_id              installation_id
channel (whatsapp|instagram|   channel_id (fk blanda)       message_id (fk blanda)
  facebook|linkedin|x)         thread_id (fk blanda)        intent (lead|queja|consulta|
name (etiqueta local)          source_message_id (único      spam|otra)
external_account_id              por canal e instalación)   language (es|en|…)
is_active                      direction (in|out)           register (formal|tuteo)
webhook_secret (hash)          sender_handle                sentiment (-1..1)
scopes (json)                  sender_name                  urgency (1..5)
last_webhook_at                email (extraída, opc.)       entities (json)
created_by                     phone (extraída, opc.)       score_social (0..100)
created_at                     body (texto, ya DLP)         summary (opc., LLM)
updated_at                     media_urls (json, opc.)      created_at
                               lead_id (fk blanda)          decided_by (deterministic|llm)
                               created_at
                               updated_at
```

- Índices únicos compuestos por instalación: `uq_social_message_source`
  (`installation_id, channel_id, source_message_id`) — la clave de dedupe.
- `webhook_secret` guardado **hasheado** (nunca plano), igual que los secretos
  de `WebhookSubscription`.
- `social_threads` (opcional v1.1): agrupa mensajes de un hilo de WhatsApp/DM
  para no crear una actividad por cada mensaje del mismo cliente.
- Sin FKs duras a `leads` (patrón del proyecto): `lead_id` blanda.

---

## 6. Conectores (hechos reales a 2026)

| Canal | API real | Auth | Webhooks | Coste real (2026) | Esfuerzo | Honestidad de venta |
|---|---|---|---|---|---|---|
| **WhatsApp** | WhatsApp Business Cloud API (Meta) | Token del número + verify token | Sí (`X-Hub-Signature-256`) | Capa API gratis; **inbound en ventana de 24 h gratis** (nov 2025); plantillas de salida por categoría (~$0.003–0.025) | M | «Inbound gratis; las respuestas manuales dentro de 24 h no cuestan» |
| **Instagram** | Instagram Graph API (mensajes + menciones) | OAuth Meta app + revisión | Sí | Gratis; requiere app de Meta con permiso `instagram_business_messaging` | M | «Requiere cuenta de negocio y revisión de la app (2–4 semanas típico)» |
| **Facebook** | Messenger Platform / Graph API página | OAuth Meta app + revisión | Sí | Gratis | M | Ídem Instagram |
| **LinkedIn** | LinkedIn API (mensajes de página/empresa) | OAuth 2.0 + scopes restringidos | Sí (webhooks de eventos, acceso limitado) | Gratis; **DMs de página con acceso aprobado** | M–L | «DMs de página sujetos a aprobación de LinkedIn» |
| **X** | X API v2 (mentions + DMs) | OAuth 2.0 (PKCE) + acceso a DMs | Sí | **Sin free tier desde feb 2026**: pago por uso (~$0.005–0.015/llamada, cap ~2M lecturas/mes) o suscripción legacy | M | «El más caro y restringido: se cotiza como add-on, no incluido en el plan base» |
| **Genérico (probar sin vendor)** | Webhook JSON plano con HMAC (fixture/estándar) | Secreto compartido | — | Gratis | S | «Útil para simular y para integraciones tipo Zapier/Make» |

**Capa de adaptador común** (`app/services/social_adapters.py`): interfaz
`SocialChannelAdapter` con `verify(payload, headers)`, `parse(payload) ->
SocialEnvelope` y `(v2) reply(thread_id, text)`. Cada canal implementa solo
`verify`/`parse` al principio; `reply` se añade en v2 con aprobación humana. Un
canal mal configurado falla cerrado (nunca afecta a los demás).

---

## 7. Triaje IA

### 7.1 Determinista (siempre activo, sin red)

| Señal | Regla | Peso en `score_social` |
|---|---|---|
| Intención | keywords/patrones: «presupuesto/quiero/precio» → lead; «error/no me llega» → queja; pregunta → consulta; spam → descartar | lead +25 · queja +15 · consulta +10 · spam 0 (no pasa a CRM) |
| Canal | WhatsApp y DMs > menciones públicas (privacidad) | +10 / +5 |
| Entidades | email o teléfono presentes | +10 |
| Urgencia | «urgente/hoy/mañana» o queja pública con @marca | +5 |
| Sentimiento | léxico positivo/negativo determinista | ajuste ±5 |

`score_social` (0–100, cap) se **fusiona** en `_lead_score` como señal
`kind: "social"` con pesos fijos; el board ordena por score como hoy.

### 7.2 LLM (opcional, si `STANDARD_LLM_PROVIDER` está configurado)

- **Resumen** del mensaje (1 línea) para la ficha del lead.
- **Entidades** libres (nombres de producto, cantidades, plazos).
- **Matiz** de sentimiento cuando el léxico no alcanza.

Guardrails: el LLM **nunca** decide la mutación (crear lead, asignar, enviar
email); solo enriquece campos `summary/entities` con validación de tipo y
longitud. Con LLM desactivado el módulo funciona completo en modo determinista
(igual que el chat comercial con catálogo local).

### 7.3 Salida de la triage (contrato del worker)

```json
{
  "message_id": "…",
  "intent": "lead",
  "lead_upsert": {"email": "…", "first_name": "…", "source": "social", "channel": "whatsapp"},
  "activity": {"kind": "follow_up", "due_at": "…", "remind_at": "…", "assigned_to": null},
  "timeline": {"kind": "social_message", "text": "…", "url": "…"},
  "score_social": 42,
  "alert_email": true
}
```

---

## 8. Priorización en el pipeline CRM

1. El lead entra con `source=social` y aparece en la **cola de leads sin
   asignar** del kanban, ordenado por score (las señales sociales empujan hacia
   arriba una queja pública o una intención de compra con teléfono).
2. El worker crea la actividad `follow_up` con `due_at = ahora + SLA_canal`
   (configurable por canal: WhatsApp 30 min, queja pública 15 min, resto 2 h) y
   `remind_at` para el email de alerta vía spool.
3. Si la instalación tiene **webhooks salientes**, se emite
   `social.message_triaged` (nuevo evento del catálogo) para que el cliente
   reaccione en su propio sistema.
4. La cola del kanban muestra un badge de canal social (ícono de la red) para
   distinguir el origen de un vistazo.

---

## 9. Flujo de trabajo y casos

**Caso A — WhatsApp con intención de compra:** el cliente escribe «hola, ¿me
hacéis presupuesto de 10 cajas del modelo X?». El webhook persiste, la triage
clasifica `lead` con entidad «X» y teléfono; crea el lead (o lo une al
existente), crea `follow_up` en 30 min, alerta al comercial por spool, el lead
aparece arriba en la cola con badge WhatsApp y el timeline muestra el mensaje.

**Caso B — queja pública en X:** mención con @marca y tono negativo. Triaje
`queja` + urgencia alta → lead con score alto (prioridad de respuesta),
actividad en 15 min, y el mensaje en el timeline con enlace al tweet. El
comercial responde desde el portal (v1) o con borrador IA aprobado (v2).

**Caso C — spam / irrelevante:** la triage descarta (no crea lead) y lo deja en
el inbox social como «archivado», sin ensuciar el CRM.

**Caso D — mismo usuario en dos canales:** llega por WhatsApp y después por
Instagram. La dedupe por teléfono/email une ambos mensajes al mismo lead; el
merge de T-054 unifica si hace falta; el timeline muestra los dos canales.

---

## 10. Seguridad y gobierno

| Control | Diseño |
|---|---|
| Firma de webhooks | `verify_hmac_signature` por canal; `webhook_secret` hasheado en BD; reenvío de Meta/X con `source_message_id` deduplicado |
| SSRF/egreso | Los adaptadores solo hablan con dominios de la API del canal (allowlist); sin URLs del atacante |
| DLP | El texto pasa por la clasificación/DLP de `rag_security` antes de persistir: tarjetas/DNI/secretos se redactan o descartan |
| RBAC | Configuración de canales: solo admin; lectura del inbox: operador+; respuesta: operador+ (v2 con aprobación) |
| Auditoría | Cada webhook (hash del cuerpo), triage y mutación queda en `AuditLog` con correlation_id |
| RGPD | Los mensajes entran en export/erase/legal hold; `email_opt_out` respeta el consentimiento; retención configurable |
| Aislamiento | `installation_id` en las 3 tablas nuevas; matriz cross-tenant como el resto |

---

## 11. Portal (vista en la app)

- **Sección «Escucha social»** (nav, admin): lista de canales con estado
  (activo / pendiente de revisión Meta / error de webhook), alta de canal
  (asistente OAuth), prueba de webhook (patrón «test ping» de WebhookSubscription).
- **Inbox social** (dentro de Clientes, operador+): bandeja de mensajes
  triageados con filtros por canal/intención/urgente, y acción «Ver lead» /
  «Crear actividad». El mensaje aparece también en el **timeline** del lead.
- **Badges**: fuente `social` en la tabla de leads y en las tarjetas del kanban.

---

## 12. Definición de «hecho» (sección 8 del handoff)

1. Invariantes de la sección 3 (hermetismo D-032, auditoría, RBAC, idempotencia,
   migraciones idempotentes con downgrade no destructivo).
2. `PYTHONPATH=bridge-api python -m pytest tests bridge-api/tests -q` verde.
3. Portal: `typecheck`, `build` y `vitest` verdes.
4. `python scripts/quality_gates.py --with-portal` → D-030 OK.
5. Filas nuevas en `TASKS.md` / `STATUS.md` / `CHANGELOG.md`.
6. Validación en vivo contra el candidato: al menos **2 canales reales**
   (WhatsApp Cloud API con número de prueba de Meta + el adaptador genérico) con
   ciclo webhook → triage → lead → actividad → timeline → cola priorizada.

**Plan de tests herméticos (propuesta):** verificación de firma por canal y
firma inválida → 401; dedupe por `source_message_id` (retry de Meta no duplica);
DLP redacta/desecha; triage determinista por intención/idioma/urgencia con y sin
LLM; upsert de lead por email/teléfono sin duplicar; actividad con SLA por
canal; opt-out no genera alerta; RBAC (viewer 403 en inbox, no-admin 403 en
canales); aislamiento entre instalaciones; crash del worker recuperable por
outbox; webhook saliente `social.message_triaged` firmado.

---

## 13. Hoja de ruta y esfuerzo

| Fase | Alcance | Esfuerzo |
|---|---|---|
| **Fase 1 (P2)** | Adaptador genérico + WhatsApp Cloud API (inbound) + triage determinista + lead/actividad/timeline + cola priorizada + portal inbox | 3–4 semanas |
| **Fase 2 (P2/P3)** | Instagram + Facebook (revisión Meta) + LinkedIn; triage LLM con guardrails; respuesta asistida con aprobación; threads | 4–6 semanas |
| **Fase 3 (P3/add-on)** | X API v2 (cotizado por consumo) + métricas de escucha + reglas de ruteo por canal + SLA de primera respuesta con alerta externa (SS-07) | 3–4 semanas |

**Reuso:** las 3 fases son capas sobre el pipeline existente; no hay modelo de
negocio nuevo que migrar.

---

## 14. Riesgos y límites honestos (para la venta)

| Riesgo | Mitigación en la propuesta |
|---|---|
| X sin free tier (pago por uso) | Se vende como add-on cotizado por consumo, nunca incluido por defecto |
| Revisión de app de Meta (2–4 semanas) | Fase 2 con fecha de entrega por criterio de salida de Meta, declarado en la propuesta |
| LinkedIn restringe DMs de página | Fase 2 condicionada a aprobación de scopes |
| Coste de plantillas de WhatsApp | v1 solo inbound (gratis en ventana 24 h); salida siempre manual |
| LLM en el loop | El score y la decisión son deterministas; el LLM solo enriquece con validación |
| Privacidad de terceros | DLP + retención + export/erase; los mensajes ajenos a la instalación no se ingieren |

---

## 15. Cómo se vende (gancho por segmento)

| Segmento | Gancho |
|---|---|
| Distribuidor B2B | «Cada DM de WhatsApp con «¿precio?» entra solo a tu pipeline y agenda al comercial; nada se queda en el móvil» |
| Fabricante con red | «La queja pública de tu marca llega antes a tu equipo que al community manager; respuesta en 15 min» |
| Marketplace | «Cada vendedor escucha solo su canal; el aislamiento se demuestra con el mismo test que el resto del CRM» |

Precio sugerido: incluido en **Pro** (1 canal, WhatsApp o genérico) y
**Enterprise** (hasta 4 canales + LLM); X e Instagram/Facebook con revisión de
Meta se cotizan como add-on por canal. Regla de venta: nunca «conectado a X» ni
«bot automático» sin declarar costes y aprobaciones.
