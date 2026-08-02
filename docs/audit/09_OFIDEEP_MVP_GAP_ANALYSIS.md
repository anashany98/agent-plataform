# 09 - Gap analysis del MVP de Ofideep

## Veredicto

**MVP: BROKEN. NO está preparado para un piloto con clientes.** Ningún tramo externo del recorrido solicitado se ejecutó end-to-end y cuatro invariantes comerciales pueden fallar aun con credenciales: procedencia de catálogo, precio, stock y consentimiento.

## Recorrido solicitado frente a realidad

| Paso | Realidad | Estado | Evidencia/gap |
|---|---|---|---|
| Cliente pregunta | No existe widget/account/inbox real configurado | BROKEN | Chatwoot DB vacía y web reiniciando |
| Agente interpreta necesidad | Heurísticas de palabras/regex | NOT IMPLEMENTED | LLM y `allowed_tools` no participan en chat |
| Consulta PrestaShop real | Adapter existe | BROKEN | Sin credenciales/egress; fallback local demo |
| Recomienda productos verificables | Busca todos los productos Bridge | BROKEN | `source=demo` no se filtra |
| Precio y stock real | Usa snapshot local | BROKEN | Ignora precio específico/variante/impuesto y reserva oficial |
| Solicita datos | Mensaje fijo | CONFIGURED ONLY | No procesa la respuesta posterior si falta email |
| Crea/actualiza contacto GHL | Adapter existe | BROKEN | Sin credenciales/egress; idempotencia no atómica |
| Crea oportunidad | Código existe | IMPLEMENTED BUT NOT TESTED | Siempre create, sin retry ni contrato real |
| Transfiere a persona | Cambia status a `open` | BROKEN | No asigna equipo/agente ni comprueba visibilidad |

## PrestaShop

### Implementado

- Cliente HTTP con timeout, autenticación por API key, filtros, normalización de idiomas y sanitización HTML.
- Producto, características, categoría, combinaciones, stock por combinación y precios específicos.
- Configuración de shop ID, límites y sincronización a Bridge.
- Fail-closed sin credenciales.

### No verificado o defectuoso

- Todos los tests del contrato usan `monkeypatch`; no hay sandbox ni versión PrestaShop declarada.
- Paginación está limitada y no existe barrido robusto/cursor; el sync tiene techo y llamadas secuenciales N+1.
- Multitienda, moneda, grupos, país, cliente, cantidad y ventanas temporales de `specific_prices` no se resuelven en la cotización.
- Combinaciones se almacenan en `attributes`, pero el flujo no selecciona variante ni suma `price_impact`.
- El IVA se sustituye por `DEFAULT_VAT_RATE`, no por reglas fiscales de PrestaShop.
- No hay rate-limit handling, retry/backoff, cache TTL, ETag, circuit breaker ni métrica de frescura.
- No se desactivan productos eliminados/inactivos durante sync.
- No se escribe pedido/reserva en PrestaShop.

## GHL

### Implementado

- Búsqueda/upsert de contacto por email, create/update, oportunidad y nota.
- Headers y location/pipeline/stage configurables.
- Referencia externa en custom fields, demostrada solo con mock.

### No verificado o defectuoso

- Token/location/pipeline/stage vacíos; red sin egress.
- Secuencia `check DB -> efectos GHL -> insert idempotency` no es atómica. Una caída tras contacto/oportunidad duplica en retry.
- No hay idempotency key del proveedor, lock, outbox, retry, backoff, circuit breaker ni reconciliación.
- La oportunidad se crea siempre; no hay deduplicación/update por referencia.
- Nota fallida después de oportunidad deja estado parcial.
- No hay webhooks GHL, refresh de token ni pruebas de scopes/rate limits.
- No se verificó que el identificador de custom field usado exista en la cuenta real.

## Chatwoot

- La versión vendor genera secreto y firma HMAC con el mismo esquema que Bridge: contrato estático compatible.
- El script de configuración puede crear el webhook y guardar el secreto, pero la instancia activa no tiene cuenta/token/webhook operativo.
- No hay widget real, contacto, inbox, conversación, mensaje visible ni respuesta real.
- `chatwoot-web` no arranca tras reboot por PID obsoleto.
- Chatwoot/Bridge no pueden salir a APIs externas; las respuestas Bridge->Chatwoot carecen de token.
- No hay retry/outbox. El handoff no asigna agente/equipo ni SLA.

## Agente y anti-alucinación

- El flujo de chat no usa modelo; no puede llamarse “agente” en sentido tool-calling.
- La ruta LLM independiente acepta prompt libre y no impone herramientas, fuentes o citas.
- `allowed_tools` no se ejecuta y el registro se pierde al reiniciar.
- La abstención RAG existe para baja similitud, pero no alimenta el chat comercial.
- La lista de palabras para secretos no protege frente a paráfrasis, prompt injection en documento ni exfiltración indirecta.
- La recomendación ambigua busca términos en catálogo local y puede devolver demo.

## Defectos de consentimiento y transacción

- `no acepto` contiene `acepto` y confirma.
- El pedido se crea directamente con status `confirmed`, no como intención pendiente de validación.
- Se reserva stock de un snapshot que puede estar obsoleto.
- Se crea un borrador de factura/aprobación sin integrar emisión legal.
- La idempotencia por quote evita repetición secuencial en tests, pero no prueba concurrencia multiworker.

## Criterios mínimos de aceptación

1. Cero productos demo en rutas de cliente; procedencia y frescura visibles.
2. Suite contractual contra sandbox PrestaShop para variante, precio específico, IVA, stock y pedido.
3. Máquina de estados de conversación con negación, confirmación explícita y expiración.
4. Upsert GHL y oportunidad idempotentes, con retry/outbox y reconciliación.
5. Chatwoot real: widget → webhook firmado → respuesta visible → asignación humana.
6. Evals de consultas ambiguas, abstención, inyección y no invención.
7. Auditoría y métricas que permitan rastrear cada efecto.

## Archivos revisados, riesgos y pendiente

Se revisaron webhook principal, servicios deterministas, todos los adapters, router LLM, RAG, modelos, tests contractuales y vendor Chatwoot focalizado. Riesgo central: cotizar/confirmar datos inventados o incorrectos. Pendiente: credenciales y sandboxes ficticios, red corregida y un e2e reproducible.

