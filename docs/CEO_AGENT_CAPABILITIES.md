# CEO agent — 27 capacidades (validación en vivo)

El **CEO agent** es el «mando en lenguaje natural» del dueño (T-067): se le habla
por el chat del portal (`POST /ceo/chat`) y resuelve la petición de forma
**determinista** (sin LLM para el enrutado), delega en los **datos reales de los
módulos** y, cuando la petición es una acción, crea **propuestas auditadas**
(`AgentProposal`) pendientes de aprobación en el panel — deny-by-default.

La arquitectura se documenta en `docs/AGENTES_POR_MODULO.md`. Este documento es
el catálogo de las **27 intenciones** y su **evidencia de validación en vivo**
contra el stack candidato de preview (2026-08-19). Las 2 últimas (`ghl_send_message`,
`ghl_create_contact`) son el canal GoHighLevel (T-083), implementadas tras la
validación en vivo de las 25 originales.

## Cómo funciona (en una frase)

```
mensaje → resolve_intent() (keywords + verbos, sin LLM)
        → lectura: _GATHERERS consultan la BD real (datos verificados)
        → acción: _resolve_* + propose_* crean AgentProposal (pendiente)
        → respuesta: plantilla determinista, o LLM local (ollama) redacta
          usando SOLO el bloque de datos verificados
        → todo se audita como ceo_chat.message y queda en la conversación
```

- **Lectura** = solo consulta la BD; nunca muta.
- **Acción** = propuesta pendiente; al aprobarla en el panel se aplica en la
  misma transacción (auditada y reversible vía `AgentDecision` + digest).
- **Autonomía (T-068/T-082)**: si el `ceo_agent` está en modo `autonomous` y la
  acción está en `allowed_actions` bajo `max_value_threshold`, la propuesta se
  auto-ejecuta al instante. Las acciones financieras (`ceo_update_price`) NUNCA
  entran en `allowed_actions`; solo se auto-ejecutan bajo el umbral de valor.

## Las 27 capacidades

| # | Intent | Capacidad | Tipo | Seguridad | Ejemplo real probado |
|---|--------|-----------|------|-----------|----------------------|
| 1 | `greeting` | Saludo y presentación | Conversación | — | «hola» |
| 2 | `help` | Catálogo de capacidades | Conversación | — | «¿qué puedes hacer?» |
| 3 | `sales_summary` | Resumen de ventas (oportunidades, win-rate, ticket medio, pedidos) | Lectura | — | «¿cómo van las ventas?» |
| 4 | `pipeline_status` | Estado del pipeline por etapa (importe + aging) | Lectura | — | «¿cómo va el pipeline?» |
| 5 | `leads_summary` | Resumen de leads (totales, por estado, sin asignar) | Lectura | — | «¿cuántos leads hay?» |
| 6 | `activities_due` | Actividades pendientes y vencidas | Lectura | — | «¿qué actividades tengo pendientes?» |
| 7 | `approvals_pending` | Aprobaciones pendientes de decisión | Lectura | — | «¿qué hay que aprobar?» |
| 8 | `social_inbox` | Bandeja social (mensajes urgentes, triage) | Lectura | — | «¿hay mensajes urgentes en la bandeja social?» |
| 9 | `stock_alert` | Alertas de stock bajo / agotado | Lectura | — | «¿hay stock bajo?» |
| 10 | `automations_status` | Estado de las automatizaciones programadas | Lectura | — | «muestra las automatizaciones» |
| 11 | `agents_status` | Estado de los agentes de IA y su autonomía | Lectura | — | «estado de los agentes» |
| 12 | `weekly_report` | Resumen semanal de toda la empresa (T-082) | Lectura | — | «resumen de la semana» |
| 13 | `aging_report` | Oportunidades más tiempo abiertas (T-082) | Lectura | — | «¿qué oportunidades llevan más tiempo abiertas?» |
| 14 | `top_products` | Productos más vendidos (T-082) | Lectura | — | «¿qué productos se venden más?» |
| 15 | `social_sla` | Mensajes sociales fuera de SLA (T-082) | Lectura | — | «¿hay mensajes sin atender?» |
| 16 | `automation_toggle` | Pausar/activar una automatización | Acción | Propuesta + autonomía segura | «pausa el sync Digest diario al dueño» |
| 17 | `follow_up_cold_leads` | Follow-up de leads fríos/sin asignar | Acción | Propuesta + autonomía segura | «haz follow-up a los leads fríos» |
| 18 | `lead_create` | Crear un lead | Acción | Propuesta + autonomía segura | «crea un lead {email} de Empresa Demo» |
| 19 | `opportunity_move` | Mover oportunidad de etapa | Acción | Propuesta + autonomía segura | «mueve la oportunidad {name} a negociacion» |
| 20 | `task_create` | Crear una tarea/actividad | Acción | Propuesta + autonomía segura | «crea una tarea para llamar a Carlos» |
| 21 | `campaign_launch` | Lanzar campaña (borrador) | Acción | Propuesta + autonomía segura | «lanza una campaña «Campaña demo CEO»» |
| 22 | `lead_assign` | Asignar lead a un comercial (T-082) | Acción | Propuesta + autonomía segura | «asigna el lead de {email} a {comercial}» |
| 23 | `opportunity_close` | Cerrar oportunidad ganada/perdida (T-082) | Acción | Propuesta + autonomía segura | «cierra la oportunidad {name} como ganada» |
| 24 | `stock_adjust` | Ajustar stock de un producto (T-082) | Acción | Propuesta + autonomía segura (nunca baja de lo reservado) | «ajusta el stock de {sku} a 25» |
| 25 | `product_price_update` | Actualizar precio de producto (T-082) | Acción | **Financiera**: solo umbral `max_value_threshold`, nunca en `allowed_actions` | «actualiza el precio de {sku} a 45,90» |
| 26 | `ghl_send_message` | Enviar SMS/email/whatsapp a un lead vía GHL (T-083) | Acción | Propuesta + autonomía si se autoriza; entrega durable vía outbox (`ghl.send_message`), DLQ sin GHL | «envía un sms a {email} que diga: tu pedido está listo» |
| 27 | `ghl_create_contact` | Dar de alta un contacto en GHL (T-083) | Acción | Propuesta + autonomía si se autoriza; entrega durable vía outbox (`ghl.create_contact`) | «añade a GHL {email}» |

## Evidencia de validación en vivo (2026-08-19)

- **Backend**: stack candidato de preview `http://127.0.0.1:8005` corriendo el
  código ACTUAL del checkout (ver nota más abajo sobre la imagen 0815).
- **Usuario**: `admin` (rol `provider_admin`, el admin inicial de
  `.env.candidate-0815`).
- **Resultado**: **25/25 intenciones resueltas correctamente** (HTTP 200, intent
  esperado, respuesta no vacía). Evidencia completa (mensajes, respuestas,
  proveedor, propuestas) en `.freebuff/evidence_ceo_capabilities.json`.
  Reproducible con `python .freebuff/live_ceo_capabilities.py`.

### Respuestas con datos reales del stack (extractos)

- **sales_summary**: «25 oportunidades abiertas, ticket medio 43.25 EUR, 3 pedidos».
- **pipeline_status**: «1 etapa con 1124.6 EUR abiertos: 26 oportunidades por
  1124.6 EUR (aging máx 3.3 días)».
- **leads_summary**: «33 leads en total» (32 sin asignar).
- **activities_due**: «11 actividades pendientes, 9 vencidas».
- **approvals_pending**: «21 aprobaciones pendientes» (issue_invoice…).
- **social_inbox**: «3 mensajes urgentes en la bandeja social».
- **stock_alert**: «10 productos con stock bajo (agotado)».
- **agents_status**: «9 agentes de IA (0 en modo autónomo)».
- **top_products**: «la válvula industrial certificación E2E (SKU-E2EF…) con 6 uds».
- **social_sla**: «3 mensajes urgentes sin atender (Carlos Ruiz: Pedido roto…)».

### Acciones → propuestas pendientes (deny-by-default)

8 de las 10 acciones generaron su `AgentProposal` pendiente:
`automation_toggle`, `lead_create`, `opportunity_move`, `task_create`,
`campaign_launch`, `lead_assign`, `opportunity_close`, `product_price_update`.

**`stock_adjust`** se probó con una cantidad vacía en el mensaje y el agente
respondió correctamente pidiendo el dato faltante («He localizado … pero dime la
cantidad»): el flujo de **entrada incompleta → pide el dato** funciona. Con
cantidad presente crea la propuesta (ver tests
`tests/regression/test_p1_ceo_omnimodule.py`).

**`follow_up_cold_leads`** respondió «No he encontrado leads fríos… nada que
proponer»: sin candidatos no propone nada (no spamea propuestas vacías).

### Proveedor de respuesta

- 10 intents redactados por el **LLM local** (`ollama`/`deepseek-r1:8b`,
  latencia 3–60 s por ser modelo de razonamiento), siempre con el bloque de
  datos verificados.
- El resto (`greeting`, `help`, `pipeline_status`, `approvals_pending`,
  `automations_status`, `agents_status`, `weekly_report` y todas las acciones)
  respondieron con la **plantilla determinista** (el intent de `weekly_report`
  incluye la tabla completa del resumen).

## Hallazgos de la validación

1. **La imagen del candidato predata T-082.** El contenedor
   `agent-candidate-0815-bridge-api-1` (imagen 2026-08-15) NO resolvía las 8
   intenciones nuevas («resumen de la semana» → `unknown`). Para validar y para
   que el preview sirva el código actual se usa el override
   `docker-compose.preview-code.yml` (bind mounts read-only de `bridge-api/app`
   y `bridge-api/alembic`; ver run doc).
2. **La llamada LLM no tiene timeout.** Cuando el proveedor está «up pero
   colgado» (observado: modelo `deepseek-r1:8b` en estado *Stopping* en Ollama),
   `/ceo/chat` se queda esperando indefinidamente — el `try/except` captura
   errores pero no timeouts. Recomendación: timeout explícito en
   `LLMRouterService.generate_response` con fallback a la plantilla
   determinista.
3. **Rate limit de login en Redis.** `LOGIN_RATE_LIMIT_REQUESTS` (8/15 min) vive
   en Redis con clave `{ip}:/auth/login`; un `docker restart` del bridge NO lo
   limpia. Para resetear: `redis-cli del` sobre esa clave (o esperar la ventana).
   Los /ceo/chat se limitan por minuto (60/min) y no afectan a la validación.
