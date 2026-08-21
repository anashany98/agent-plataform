# Estado autoritativo del proyecto

> **Endurecimiento de arranque, dev-ops y modularización (2026-08-21):**
> filas **T-076→T-079** — B-03/B-04/B-05 cerrados (INSTALLATION_ID
> fail-closed, seed a lifespan, logging en excepciones tragadas), B-06
> dev en Python 3.12.10 con suite verde, B-07 pins de vendor en gates,
> D-01/D-02 docs sincronizadas, push a origin y primer run de CI en
> GitHub. B-01 iniciado: `app/routers/` con `common.py`, `appearance.py`
> y `system.py`. Corpus **750 passed / 12 skipped**; portal 113 vitest +
> tsc; gates D-030 PASS.

> **Órdenes de acción por módulo en el chat (2026-08-18):** fila
> **T-075**, VERIFIED — el CEO agent **actúa** desde el chat: crear un
> lead, mover una oportunidad de etapa, crear una tarea y lanzar una
> campaña. Cada orden genera una **propuesta auditada**
> (`agent_proposal:ceo_*`) que solo se aplica al aprobarla (deny-by-
> default; auto-ejecución solo dentro de la autonomía autorizada, T-068) y
> ejecuta la mutación real en la misma transacción (lead, stage + webhook
> saliente, actividad, campaña draft/activa). 7 evals nuevos; corpus **644
> passed / 12 skipped**; gates D-030 PASS. Validado en vivo contra el
> PostgreSQL real: los 4 intents con aprobación aplicada (lead creado,
> `new → negotiation` con webhook, actividad `call`, campaña borrador) y
> datos de prueba limpiados.

> **Digest diario por email y voz en el chat (2026-08-18):** filas
> **T-074** y **T-073**, VERIFIED — el dueño recibe cada día el resumen
> (decisiones de agentes con «REVERTIR <id>», propuestas pendientes y
> métricas clave) por la tarea programada `daily_digest` y puede **anular
> una decisión respondiendo al propio correo** con la misma trazabilidad
> del portal; además puede **preguntar y dar órdenes hablando** en el chat
> universal (Web Speech API, mismo pipeline de intenciones). Corpus **637
> passed / 12 skipped**; gates D-030 PASS; portal **98 vitest + tsc +
> build**. Validado en vivo contra el PostgreSQL real: digest dry-run y
> envío real al spool con datos reales, decisión revertida por email
> (actividad `cancelled`, `reverted_by` del dueño) y tarea diaria activa.

> **Onboarding guiado para personas sin experiencia (2026-08-18):** fila
> **T-072**, VERIFIED — al primer acceso se abre un asistente paso a paso
> que explica la landing, invita a probar **3 preguntas de ejemplo** enviadas
> al chat universal real y activa un **modo guiado** (solo Asistente y
> Resumen visibles hasta que el usuario se sienta cómodo, con botón
> «Mostrar todos los módulos» en el overlay y en la barra lateral). La
> preferencia persiste en localStorage (`guided-onboarding`). 8 evals
> nuevos; portal **93 vitest + tsc + build**. Validado en vivo contra el
> candidato (preview + contenedor del portal reconstruido): flujo completo
> con respuesta real del chat y navegación revelada al terminar.

> **App simple con chat universal y moneda EUR (2026-08-18):** fila
> **T-071**, VERIFIED — la app es manejable por **una sola persona** desde
> una conversación: nueva landing **«Asistente»** con el chat como centro
> de mando (`CeoChat` reutilizable), y el chat **gestiona agentes y
> automatizaciones** en lenguaje natural: `automations_status`,
> `agents_status` y `automation_toggle` (pausar/activar → propuesta
> `agent_proposal:automation_toggle` aplicada al aprobar). Moneda **EUR**
> explícita en landing y respuestas. Bug corregido en vivo: el toggle ahora
> hace match por parte del nombre («pausa el barrido E2E»). 2 evals nuevos;
> corpus **629 passed / 12 skipped**; gates D-030 PASS (deuda 132 < 133);
> portal 85 vitest + tsc. Validado en vivo contra el candidato: los 3
> intents sobre el PostgreSQL real, ciclo propuesta → aprobación → pausa
> aplicada (tarea restaurada a `active`), y chat desde el portal con EUR
> visible.

> **«Cierra el mes» en piloto automático (2026-08-17):** fila **T-070**,
> VERIFIED — primer proceso completo con agente coordinador
> (`finance_agent`): `POST /finance/monthly-close` ejecuta en un solo
> disparo reconciliar ventas (solo lectura), emitir facturas (cada pedido
> sin factura → `ApprovalRequest` `issue_invoice` con `value_eur`; si la
> autonomía del agente lo autoriza — autónomo y bajo umbral — se emite y
> envía al instante con PDF, `AgentDecision` y auditoría; si no, queda
> pendiente de aprobación humana), disparar dunning (solo en modo autónomo;
> manual → diferido) y generar el reporte al dueño (`OWNER_COMMAND_EMAIL`,
> degradación al spool). `dry_run=True` no muta nada. 7 evals nuevos;
> corpus **620 passed / 12 skipped**; gates D-030 PASS. Validado en vivo
> contra el PostgreSQL real: dry-run sobre los 3 pedidos reales del mes;
> pedido sembrado (200 €) → modo manual = propuesta pendiente; autonomía
> activada con umbral 1000 € → factura auto-emitida (`approved`),
> `AgentDecision` sin desviación, auditoría y email con PDF en el spool;
> datos de prueba limpiados y autonomía restaurada a manual.

> **Superficie de mando del dueño por email/WhatsApp (2026-08-17):** fila
> **T-069**, VERIFIED — el propietario consulta y da órdenes a los agentes
> desde el canal que ya usa, reutilizando el spool de email y la escucha
> social. Email: `POST /commands/email/webhook` (HMAC con
> `OWNER_COMMAND_EMAIL_WEBHOOK_SECRET`) → el remitente debe coincidir con
> `OWNER_COMMAND_EMAIL` → intención resuelta con el CEO agent (misma memoria
> por conversación) → respuesta por `send_email` (SMTP real o spool local
> con degradación auditada). WhatsApp: en el webhook de escucha social, el
> número del dueño (`OWNER_COMMAND_PHONE`) se intercepta antes del triaje
> comercial → CEO chat → respuesta como mensaje saliente
> (`direction="out"`) en el mismo canal, entrante `triaged` con intención
> `command`. Fail-closed: identidad vacía = desactivada; desconocidos →
> ignorados auditados sin respuesta; sin secreto/firma inválida → 401.
> Auditoría `ceo_command.email`/`ceo_command.whatsapp` (+ `.ignored`).
> 7 evals nuevos; corpus **613 passed / 12 skipped**; gates D-030 PASS
> (deuda 132 < 133). Validado en vivo: correo del dueño → `sales_summary`
> con reply en el spool real, WhatsApp del dueño → `owner_command` con
> `pipeline_status` y reply outbound, desconocidos ignorados, auditoría en
> PostgreSQL.

> **Autonomía por excepción (2026-08-17):** fila **T-068**, VERIFIED — la
> aprobación por caso se convierte en **supervisión por excepción**: cada
> agente tiene una configuración por instalación (`AgentAutonomy`, modo
> `manual`/`autonomous`, umbral EUR, flags de follow-ups/descarte de spam,
> avisar solo si se desvía) — deny-by-default, sin configuración nada
> cambia. Dentro del umbral, las propuestas se auto-ejecutan en la misma
> transacción que la aprobación humana (`reviewed_by=agent:<id>`) y quedan
> registradas como `AgentDecision` (efecto + desviación + auditoría
> `agent_decision.auto_executed`); el digest diario (`GET /agents/digest`)
> agrega por agente con pendientes humanas y el dueño revierte con un clic
> (`POST /agents/decisions/{id}/revert`; follow-up → `cancelled`, spam →
> `triaged`; doble revert → 409). Endpoints `GET/PUT /agents/autonomy` (PUT
> solo admin, auditado `agents.autonomy_updated`). Portal: paneles
> «Autonomía por excepción» y «Digest de decisiones de los agentes» en
> Agentes de IA. Integrado en la ronda de propuestas y en el CEO chat.
> Migración `0025`. 9 evals nuevos; corpus **606 passed / 12 skipped**;
> gates D-030 PASS (deuda 132 < 133); portal **85 vitest** + tsc + build.
> Validado en vivo contra el candidato: follow-up auto-ejecutado con
> `decision_id`, digest con `executed_by: agent:ceo_agent`, revert en vivo
> y 409 en doble revert; por UI el panel guarda el modo y el digest muestra
> la decisión revertida por admin.

> **CEO agent: mando en lenguaje natural para el dueño (2026-08-17):** fila
> **T-067**, VERIFIED — `POST /ceo/chat` (OPERATOR_ROLES) resuelve la
> intención de forma determinista (normalización Unicode + catálogo de
> palabras clave con pesos, sin LLM para el enrutado) sobre 11 intenciones:
> saludo, ventas, pipeline, leads, actividades, aprobaciones, inbox social,
> stock, follow-up de leads fríos, ayuda y unknown. Lecturas: datos reales
> verificados de la BD (agg de oportunidades/pedidos, etapas con aging,
> leads por estado y sin asignar, actividades vencidas, aprobaciones
> pendientes, inbox social urgente, stock bajo) sintetizados con el LLM
> configurado (ollama en vivo) o plantillas deterministas — nunca inventa.
> Acción: `follow_up_cold_leads` crea propuestas `ceo_follow_up` por lead
> sin asignar (batch 10, dedupe por unicidad) que el humano aprueba en el
> panel y aprobar genera la `Activity` (misma transacción que
> `_apply_follow_up`, `created_by=agent:ceo_agent`). Registrado en
> AGENT_REGISTRY (módulo `ceo`, 9 tools read-only) → aparece en el panel de
> supervisión. Memoria de conversación + auditoría `ceo_chat.message`.
> Portal: panel «Chat de dirección (CEO)» en Agentes de IA (burbujas,
> sugerencias, meta de intención/propuestas). 28 evals nuevos;
> corpus **597 passed / 12 skipped**; gates D-030 PASS (deuda 133 = baseline);
> portal **85 vitest** + tsc + build. Validado en vivo contra el candidato:
> E2E con LLM real (ventas 120/300, pipeline, follow-up con 10 propuestas
> pendientes, dedupe por lead, aprobación en vivo creando la actividad) y
> chat del dueño funcionando desde el portal.

> **Segmented controls iOS en la barra superior (2026-08-17):** fila
> **T-066**, VERIFIED — los icon-buttons de tema y densidad se sustituyen
> por dos segmented controls estilo iOS («Claro/Oscuro» y «Cómodo/Compacto»)
> con `role="group"`, nombres accesibles y `aria-pressed` en el segmento
> seleccionado. Track gris redondeado con hairline, thumb blanco con sombra
> y texto del acento de instalación; variantes oscura (thumb #1C1C1E) y
> compacta (28px); `flex-wrap` en ≤760px. Se eliminaron Moon/Sun/Rows3 del
> import. Portal **85 vitest** (1 nuevo del tema + densidad actualizado a la
> semántica segmented), tsc y build OK; backend intacto. Verificado en vivo
> en el preview: Oscuro+Compacto aplican `data-theme=dark`/`data-density=compact`
> con thumb #1C1C1E y texto de acento.

> **Identidad del rediseño en PDFs/facturas (2026-08-17):** fila **T-065**,
> VERIFIED — `generate_invoice_pdf(invoice, db=None)` compone la factura
> con la marca del portal y el acento de la instalación (T-061): barra de
> 60pt del color de acento, marca blanca «Agentes IA / Control
> empresarial», título FACTURA + número en Helvetica-Bold, metadatos
> (Cliente/Pedido/Estado/Moneda/Emitida) con etiqueta gris y valor oscuro,
> TOTAL a la derecha y pie determinista; etiqueta del cliente con
> nombre+email y normalización de dash (sin `?`). Determinista, de solo
> lectura y sin dependencias nuevas. 3 evals nuevos; corpus **569 passed /
> 12 skipped**; gates D-030 PASS (132 < 133). En vivo contra el candidato:
> HTTP 200 application/pdf con acento de instalación y cambio teal
> instantáneo (default→teal→restore). Fix de robustez: seed de supervisión
> con timestamps relativos a ahora.

> **Auditoría de contraste y proporciones del rediseño (2026-08-17):**
> fila **T-064**, VERIFIED — revisión WCAG de kanban, calendario y tareas.
> Corregido: «Agosto De 2026» (text-transform: capitalize sobre meses en
> minúscula) → «Agosto de 2026» con capitalización en JS; `.status.ok`
> (4.01:1) y `.status.warning` (4.17:1) pasan AA en claro (→ #0f7a4c
> 4.83:1 y #8a5a00 5.46:1); chips de score semántico ≥5:1; y el
> calendario en oscuro tenía números blancos sobre celdas blancas (1:1) —
> ahora overrides oscuras para celdas/out-month/weekday/hora/hover
> (día 17:1, fuera-de-mes 18.7:1, badges ≥9:1 en oscuro). Verificado en
> vivo con ratios computados (claro + oscuro); portal tsc + build +
> **84 vitest**; backend intacto (corpus y gates sin cambios).

> **Rediseño iOS / minimalista (2026-08-17):** fila **T-063**, VERIFIED —
> capa final de CSS que redefine el sistema de diseño completo: fondo
> system gray (#F2F2F7 claro / #000 oscuro), tarjetas blancas (/#1C1C1E)
> con radius 18-22 px y hairline borders, tipografía del sistema (SF
> Pro/Segoe UI), sidebar translúcida estilo iPad con pill de acento (sin
> navy ni glow), botones planos de un solo acento, tablas iOS sin cebra,
> alertas planas, kanban con tarjetas blancas y login sin franja de
> gradiente; sin animaciones decorativas (rise-in, brand-glow, pulse
> eliminados) — solo transiciones de 0,15 s. El acento de instalación
> (#007AFF/#0A84FF por defecto), el tema y la densidad siguen funcionando
> sobre el nuevo sistema. Portal tsc + build + **84 vitest** (sin cambios
> de comportamiento), corpus backend intacto (565/12), gates D-030 PASS;
> verificado en preview light + dark con computed styles (bodyBg
> rgb(242,242,247)/rgb(0,0,0), cardBg rgb(28,28,30), sidebar
> rgba(250,250,252,0.86)/rgba(22,22,24,0.86)) y screenshots.

> **Modo de densidad del portal (2026-08-17):** fila **T-062**, VERIFIED —
> preferencia por usuario (`comfortable`/`compact`) persistida en
> localStorage y aplicada con `data-density` sobre `documentElement` (mismo
> mecanismo que el tema). Toggle `Rows3` en la barra superior junto al de
> tema, con `aria-pressed` y tooltip. CSS compacto reduce padding/gaps de
> content, sidebar, paneles, métricas (126→92), tarjetas, tablas, kanban,
> calendario, supervisión y apariencia. Portal tsc + build + **84 vitest**
> (1 nuevo), corpus backend intacto (565/12), gates D-030 PASS; verificado
> en preview con computed styles reducidos (content 16/22/30, metric
> 11/12, panel 13/15) y screenshot del resumen compacto.

> **Color de acento por instalación (2026-08-17):** fila **T-061**,
> VERIFIED — modelo `InstallationAppearance` (una fila por instalación,
> get-or-create) con `accent_color` #RRGGBB validado por regex y
> `updated_by`; migración `0024`; `GET/PUT /appearance/settings` (PUT solo
> admin, auditado `appearance.settings_updated`). El portal carga el acento
> al entrar, lo aplica a `--accent`/`--accent-soft` (color-mix) con
> persistencia local (el login adopta el acento sin token) y el panel
> «Apariencia — Color de acento de la instalación» en Usuarios y permisos
> ofrece paleta de 8 presets + hex personalizado + «Restablecer azul»;
> marca, login, botón primario y franjas usan `color-mix` con el acento.
> Corpus **565 passed/12 skipped** (7 evals nuevos), gates D-030 PASS
> (deuda 132 < baseline 133), portal tsc + build + **83 vitest**; en vivo
> contra el candidato (rebuild + migración `0024`): default #246bfd → PUT
> #0d9488 → 422 en inválido → persistido con `updated_by: admin`; por UI:
> swatch violeta → guardar → `--accent: #7c5cf0` en el nav, botón y notice
> (screenshots).

> **Pulido visual del portal (2026-08-17):** fila **T-060**, VERIFIED —
> mejora estética solo en CSS (`src/styles.css`), sin cambiar
> comportamiento: accesibilidad (`:focus-visible`, `::selection`,
> `prefers-reduced-motion`), números tabulares y scrollbars finos; sidebar
> con resplandor, item activo con acento y marca con brillo; KPIs con tinte
> por tarjeta (azul/verde/violeta/ámbar/rosa, variantes dark) y hover con
> elevación; botones con gradiente, tablas con fila hover, alertas con
> franja de severidad, login con franja de gradiente y entrada en escena
> escalonada. Portal **82 vitest passed**, `vite build` OK; verificado en
> preview en modo claro y oscuro (screenshots).

> **Panel de supervisión de agentes por módulo (2026-08-17):** fila
> **T-059**, VERIFIED — `GET /agents/supervision` (READ_ROLES) agrega la
> auditoría `tool_call` de la instalación por agente (integrado o
> persistido): qué módulo gestiona, allowlist efectiva, estado por tool
> (kind, authorized, calls/✓/✗/!, `last_status` = la más reciente por
> timestamp), `summary` y `recent_actions` (últimas 5 auditadas); sin
> actividad el agente aparece ocioso. Portal: panel «Supervisión por
> módulo» (Control empresarial) bajo el registro — tarjeta por agente con
> badge de módulo, pills de llamadas/✓/✗/! y tablas desplegables de tools y
> actuaciones. Corpus **559 passed/12 skipped** (4 evals nuevos), gates
> D-030 PASS (deuda 131 < baseline 133), portal tsc + build + **82 vitest**;
> en vivo contra el candidato (rebuild con `libpq` 18.6-r0 en el
> Dockerfile + `--env-file .env.candidate-0815`): 3 invocaciones reales
> (crm `list_leads` success, social `get_social_stats` success, crm
> `confirm_quote` denied) → totals 3/2/1/0 y el panel muestra las tarjetas
> con la actividad real y la denegación auditada (screenshot).

> **Agentes de IA por módulo — Fase 2, propuestas con aprobación (2026-08-17):**
> fila **T-058**, VERIFIED — los agentes especializados de la T-057 ya no
> solo leen: **proponen** con aprobación humana. `services/agent_proposals.py`
> (determinista, sin LLM/red): `crm_agent` propone `agent_proposal:create_follow_up`
> (actividad con SLA 4 h para mensajes sociales urgentes — queja o lead con
> urgency ≥ 40 — sin seguimiento o vencido) y `social_agent` propone
> `agent_proposal:dismiss_message` (spam con score 0 aún en el inbox). Cada
> propuesta es un `ApprovalRequest` del flujo existente (`requested_by` = id
> del agente); unicidad por action+target, el rechazo re-propone si la señal
> sigue y el efecto viaja en la misma transacción del approve (actividad
> idempotente o `dismissed`) con auditoría. Endpoint `POST
> /approvals/agent-round` (RBAC operador+). Portal: botón «Ejecutar agentes»
> en el panel de aprobaciones + labels de propuesta. Corpus **555 passed/12
> skipped** (8 evals nuevos), gates D-030 PASS (deuda 131 < baseline 133),
> portal tsc + build + **81 vitest**; E2E en vivo contra el candidato:
> ronda real → propuestas de follow-up y spam → approve aplica el efecto.

> **Agentes de IA especializados por módulo — Fase 1 (2026-08-17):**
> directriz del cliente — «toda la app debe estar gestionada por agentes
> de IA especializados por módulo» (fila **T-057**, VERIFIED). Catálogo
> built-in en `AGENT_REGISTRY` (`catalog_agent`, `crm_agent`,
> `social_agent`, `marketing_agent`, `content_agent` + `sales_agent`/
> `rag_agent`) con `module`, `module_label`, `scope`, persona, tier y solo
> las herramientas de su dominio; 7 herramientas read-only deterministas
> por módulo en `DeterministicToolsService` declaradas en `TOOL_SPECS`
> (kind `read`); deny-by-default intacto (ninguna tool financiera
> autorizable; `AgentConfigSchema` con `extra=forbid`); auditoría
> `tool_call` en cada invocación. Arquitectura y roadmap (Fase 2 con
> aprobación, supervisor) en `docs/AGENTES_POR_MODULO.md`. Portal: badge
> de módulo + alcance en la sección Agentes. Corpus **547 passed/12
> skipped** (8 evals nuevos), gates D-030 PASS (ratchet 133=baseline),
> portal tsc + build + **80 vitest**.
>
> **Agente de escucha social — Fase 1 (2026-08-17):** undécimo módulo de la
> T-044 y cuarto del P2 (fila **T-056**, VERIFIED) — adaptadores puros por
> canal (genérico JSON+HMAC y WhatsApp Business Cloud API con challenge y
> `X-Hub-Signature-256`; fail-closed) en `services/social_adapters.py`;
> modelos `SocialChannel`/`SocialMessage`/`SocialTriage` (dedupe por
> `source_message_id`) con migración `0023`; triaje determinista sin
> red/LLM (intención, idioma, registro, sentimiento, urgencia, entidades,
> `score_social` explicado) en `services/social_triage.py`; webhook
> público firmado que persiste y encola la triaje en el outbox durable
> (`social.triage`): lead con `source=social` (dedupe email→teléfono→
> handle), actividad follow-up con SLA (WhatsApp 30 min, queja 15 min),
> timeline y evento saliente `social.message_triaged` en el catálogo de
> webhooks; CRUD de canales admin (secreto nunca expuesto; borrado con
> mensajes → desactivación), inbox/dismiss/stats operador+; el scoring
> fusiona la señal `social`. Portal: tab «Escucha social» en Clientes
> (`src/social.tsx`). En vivo contra el candidato (PostgreSQL real,
> `0023`): webhook WhatsApp simulado firmado → triaje queja/es/urgente
> 64/score 60 → lead «Carlos Ruiz» + actividad SLA 15 min + timeline +
> stats; 401 con firma inválida; reintento → duplicate; canal desactivado;
> preview del tab con el mensaje real (screenshot). Corpus **539
> passed/12 skipped** (14 evals nuevos), gates D-030 PASS (ratchet
> 133=baseline), portal tsc + build + **79 vitest**.
>
> **Retomar por aquí (handoff, sección 6):** los módulos P2 del plan
> (webhooks salientes, email integrado, calendario, campañas) están
> cerrados y la directriz de agentes por módulo está completa en sus dos
> fases (T-057 lectura + T-058 propuestas con aprobación); lo siguiente es
> la **Fase 2 del agente de escucha social** (Instagram/Facebook/LinkedIn/X
> según `docs/SOCIAL_LISTENING_AGENT.md`), conectar las propuestas de
> agente a más módulos (marketing/catálogo) o el bloque P3 (SSO/OIDC +
> MFA, tickets/SLA, equipos, multi-tenant RLS, billing, SCIM, BI) según
> `docs/PRODUCT_PLAN_CRM_B2B.md`. Línea base: corpus 559/12, gates D-030
> PASS, portal 82 vitest.

> **Email integrado (2026-08-16):** octavo módulo de la T-044 y segundo del
> P2 según el handoff (fila **T-052**, VERIFIED) — modelos `EmailTemplate`,
> `EmailSettings` y `EmailTrackingEvent` (migración `0020`), CRUD auditado
> con RBAC (`GET /email/templates` lectura + catálogo de variables,
> `POST/PATCH/DELETE` solo admin idempotente, `GET/PUT /email/settings`
> admin), `send_templated_email` que renderiza variables + firma (de
> plantilla o instalación) y envía por el pipeline existente; tracking de
> apertura/clics con `EMAIL_TRACKING_BASE_URL`: evento `sent` por token,
> pixel PNG 1x1 en el HTML y enlaces reescritos a `/email-tracking/{token}/
> open.png` y `/click` (endpoints públicos, idempotentes; 302 al destino);
> sin base URL no emite URLs rotas (audit `email.tracking_skipped`) y
> plantilla inexistente falla cerrado (`email.template_not_found`);
> `LocalEmailProvider`/`SmtpEmailProvider` aceptan `html` y
> `tracking_token` sin romper llamadas existentes. Portal: sección «Email
> integrado» (admin) con CRUD, «Enviar prueba», firma, toggle de tracking y
> tabla de eventos. En vivo contra el candidato: firma «Un saludo, Equipo
> BTOP Digital», `send-test` → spool con variables renderizadas + pixel +
> clics + firma, `open.png` 200 PNG 67 bytes, `/click` 302 a
> `https://example.com/presupuesto/QT-DEMO`, eventos `sent→open→click` en
> BD (sin duplicar). Corpus backend **531 passed/11 skipped**, gates PASS,
> portal **63 vitest**.
>
> **Retomar por aquí (handoff, sección 6):** el siguiente módulo del plan
> CRM es **calendario de comercial (P2)** — vistas diaria/semanal sobre las
> actividades ya existentes (`Activity.due_at`) — y después **campañas
> segmentadas (P2)** (sobre el spool/SMTP y la segmentación por campos
> personalizados y score). A continuación, datos maestros (cuenta vs
> contacto, merge, probabilidad por etapa, motivo de pérdida/ganancia) y el
> bloque P3 según `docs/PRODUCT_PLAN_CRM_B2B.md`. Línea base: corpus
> 531/11, gates D-030 PASS, portal 63 vitest.

> **Webhooks salientes de eventos CRM (2026-08-16):** séptimo módulo de la
> T-044 y primero del P2-f según el handoff (fila **T-051**, VERIFIED) —
> modelo `WebhookSubscription` (migración `0019`), CRUD auditado con RBAC
> (`GET` lectura con secreto oculto, `POST/PATCH/DELETE` solo admin, test
> ping `POST /{id}/test` por el outbox sin red), anti-SSRF en dos capas
> (CRUD sin DNS + dispatcher con resolución; rechazo → dead-letter
> permanente), transactional outbox (`OutboxService.enqueue(commit=False)`)
> con enganches en `lead.created`, `lead.assigned`,
> `pipeline.stage_changed` y `quote.confirmed`, dispatcher `crm.webhook`
> que firma con HMAC-SHA256 y el secreto de la suscripción. Portal:
> sección «Webhooks salientes» (admin) con CRUD y test. En vivo contra el
> candidato: firma verificada byte a byte en un listener local (cuerpo
> canónico 197 chars, `sent`) y DNS de `.test` → dead-letter auditada
> (`webhook_dns_resolution_failed`). Corpus backend **522 passed/11
> skipped**, gates PASS, portal **58 vitest**.

> **Import/export CSV de leads (2026-08-16):** sexto módulo de la T-044
> implementado (fila **T-050**, P2-e, VERIFIED) — `GET /leads/export.csv`
> exporta columnas fijas + campos personalizados activos (booleanos Sí/No,
> orden determinista, cabecera de descarga) y `POST /leads/import` importa
> lotes con `Idempotency-Key`: validación por fila sin abortar el lote,
> deduplicación por email (también intra-lote), creación con
> `source="import"` y modo `dry_run` sin efectos; auditoría
> `lead.import_completed`. Portal: botón «Exportar CSV» en Leads. El round
> anterior se cerró con P1-c campos personalizados (T-048) y P1-d lead
> scoring (T-049). Con este módulo el P2 de import/export queda cubierto;
> siguen abiertos del P2: email integrado, campañas, calendario, API pública
> + webhooks salientes y SSO/MFA. Corpus backend **510 passed/11 skipped**,
> gates PASS, portal **53 vitest**.

> **Campos personalizados + lead scoring (2026-08-16):** cuarto y quinto módulo
> de la T-044 implementados (filas **T-048** P1-c y **T-049** P1-d, VERIFIED).
> P1-c: modelos `CustomFieldDefinition`/`CustomFieldValue` (migración `0018`),
> definiciones tipadas por instalación con visibilidad por rol
> (`all`/`operators`/`admins`), endpoints auditados `GET/POST /custom-fields`,
> `PATCH /custom-fields/{id}`, `GET /custom-values` y `PUT /custom-values`
> (upsert idempotente con validación de tipo/opciones). P1-d:
> `GET /leads/{id}/score` determinista y explicado por señales (origen,
> antigüedad, oportunidades abiertas, valor, histórico won); la cola del
> kanban expone `score`/`score_signals` y se ordena por puntuación. Portal:
> pestaña «Campos personalizados» (admin), badge de puntuación en la cola y
> edición de valores en la ficha del lead. Además: `BLOCKERS.md` sincronizado
> con la evidencia (B-007 RESOLVED; B-003/B-005/B-006/B-010 MITIGADO) y fix de
> `--update-baseline` (recalcula el desglose `by_rule`; baseline ruff = 133).
> Corpus backend **505 passed/11 skipped**, gates PASS, portal **52 vitest**.

> **Actividades de comercial (2026-08-16):** tercer módulo de la T-044
> implementado (fila **T-047**, VERIFIED) — modelo `Activity` (migración
> 0017), CRUD auditado (`GET/POST /activities`, `PATCH /activities/{id}`,
> `POST /activities/{id}/remind`) y `DurableActivityReminderWorker` opt-in
> que al vencer `remind_at` envía el email por el pipeline existente
> (proveedor o spool local con degradación auditada, idempotente vía
> `reminded_at`). Portal: tab «Tareas» en Clientes con filtro, acciones
> Recordar ahora/Completar/Cancelar y formulario de nueva tarea. En la
> validación en vivo se encontró y corrigió un bug real (`None + str` al
> crear tarea sin lead). Worker y recordatorio validados en vivo contra el
> candidato (spool con asunto «Recordatorio: …», auditoría `activity.*`).
> Corpus 470/11, gates PASS, portal 47 vitest.

> **Timeline de interacción (2026-08-16):** segundo módulo de la T-044
> implementado (fila **T-046**, VERIFIED) — `GET /leads/{lead_id}/timeline`
> fusiona creación, asignación, oportunidades (creación/etapas/notas), ciclo
> de venta (presupuesto/pedido por external_reference) y emails
> (correlacionados por `recipient_sha256`, asunto hasheado por privacidad)
> en orden cronológico. Portal: ficha del lead en drawer desde las tarjetas
> del kanban y la cola (Esc cierra). Validado en vivo con un lead real del
> candidato (alta → oportunidad → nota → email en cola → 4 cambios de
> etapa). Corpus 465/11, gates PASS, portal 42 vitest.

> **Reporting de ventas P1-b (2026-08-16):** primer módulo de la T-044
> implementado (fila **T-045**, VERIFIED) — columna `stage_changed_at`
> (migración 0016, NOT NULL con backfill, batch para SQLite) y endpoint
> `GET /pipeline/report` con funnel por etapa (recuento, valor, aging
> medio/máx en la etapa actual), ticket medio y mediana, win-rate
> won/(won+lost) y pipeline abierto. Portal: tab «Reporting de ventas» en
> Clientes con 5 KPIs y funnel por barras; el aging sub-diario se muestra en
> horas (0,38 días → «9 horas»). Validado en vivo contra el candidato
> (funnel 26 en «Nuevo», ticket medio 43,25 €, aging 9 h máx 13 h, win-rate
> «—» con 0/0). Corpus 462/11, gates PASS, portal 36 vitest.

> **Tarea paraguas CRM completo (2026-08-16):** registrada **T-044** en
> `TASKS.md` con todo el hueco CRM detectado en el análisis: P1 núcleo
> vendible (actividades de comercial + timeline, reporting funnel/ticket
> medio/win-rate/aging, campos personalizados, lead scoring), P2 crecimiento
> (email integrado + campañas sobre el spool existente, calendario,
> import/export, API pública + webhooks, SSO/MFA) y P3 enterprise (tickets
> con SLA, equipos, multi-tenant RLS, billing, SCIM, BI), más datos maestros
> (cuenta/contacto, merge, probabilidad por etapa). Depende de T-042 (plan)
> y T-043 (kanban P1-a, VERIFIED). El reporting (P1-b) es el siguiente paso.

> **Kanban de pipeline P1-a (2026-08-16):** implementado el módulo P1-a del
> plan CRM — etapas configurables sobre `opportunities` con drag&drop nativo
> (sin librerías), cambio de etapa auditado y cola de leads sin asignar con
> asignación a comercial auditada. Backend: `PipelineStage` +
> `leads.assigned_to` (migración `0015`, idempotente, downgrade no
> destructivo) y 5 endpoints (`GET/PUT /pipeline/stages`, `GET /pipeline/board`,
> `PATCH /opportunities/{id}`, `PATCH /leads/{id}/assign`), todos auditados y
> con RBAC (solo admin reconfigura etapas). Portal: sección Clientes con
> toggle «Leads / Pipeline (kanban)» (`src/kanban.tsx`). Verificado en vivo
> contra el stack candidato: board con 6 etapas y 26 oportunidades, asignación
> del lead E2E (`lead.assigned` en `audit_logs`) y cambio de etapa
> `new→won→new` (`pipeline.stage_changed`). Corpus 459 passed/11 skipped,
> gates PASS, portal 32 vitest. Fila T-043.

> **Plan de producto CRM B2B (2026-08-16):** nuevo documento
> `docs/PRODUCT_PLAN_CRM_B2B.md` reposiciona Bridge como **CRM B2B de ventas +
> back-office comercial por instancia gestionada** — la tesis: el pipeline se
> alimenta del ciclo de venta real (cada presupuesto del chat es una
> oportunidad), no de tecleo manual. Define módulos a añadir en tres bloques
> (P1 núcleo comercial: kanban/actividades/reporting/asignación/scoring;
> P2 crecimiento: SSO+MFA/campañas/API/calendario/import-export;
> P3 enterprise: multi-tenant RLS/billing/SCIM/ERP-fiscal/BI), precios por
> segmento sobre los rangos del pitch (Starter €149 / Pro €499 / Enterprise
> €1.900) y hoja de ruta M0→M3 con criterios de salida (M1 = v1.0 vendible
> como Pro). Fila T-042.

> **Gate de regresión LLM-as-judge (2026-08-16):** quality gates incorpora
> `--with-judge`, el gate `llm-judge` que ejecuta el evaluador de
> naturalidad cuando cambian los archivos de prompt/chat y **falla el
> pipeline si la media global baja de 4.0** (`--judge-threshold`) sobre la
> evidencia en vivo más reciente. Sin cambios, sin evidencia o sin juez
> alcanzable → SKIP fail-open auditado. Juez de referencia: qwen3-14b en
> LM Studio local (T-039); `--judge-spec`/`QUALITY_GATE_JUDGE_SPEC` lo
> cambian. Ejecución real: **llm-judge PASS, media global 4.3 ≥ 4.0** (11
> respuestas), artefacto `logs/rehearsal/quality_gate_judge_20260816T110137Z.json`.
> Corpus **450 passed / 11 skipped / 0 errores**; gates PASS; fila T-041.

> **Repetición de saludo corregida y revalidada (2026-08-16):** el hallazgo
> principal de la evaluación (deepseek-r1:8b repetía la plantilla de saludo
> en follow-ups) se corrige de forma **determinista** con
> `_strip_greeting_repeat` (con historial y turno no-saludo elimina el
> prefijo de saludo/presentación; si la respuesta era solo el saludo cae al
> extractivo) y su espejo `_ensure_greeting_persona` (primer saludo con el
> nombre garantizado); el historial previo ahora excluye el mensaje actual
> (el webhook lo persiste antes de responder) y la directiva de
> idioma/registro se anexa también al final del prompt de usuario. Driver
> en vivo PASS **11/11** (follow-ups sin saludo, saludo con persona).
> Revalidación LLM-as-judge: **deepseek-r1:8b 3.17 → 3.30** y **qwen3-14b
> (LM Studio) 4.12 → 4.28** — ambos confirman la corrección: el follow-up
> que rompía coherencia pasa de coherencia **1 → 4 (8b) / 1 → 5 (qwen)**.
> El veredicto global sigue FAIL por residuales distintos: honestidad de
> disponibilidad (memoria t1 afirma «están en venta» con stock 0) y ruido
> del juez en el saludo puro de persona. Corpus **444 passed / 11 skipped /
> 0 errores**; gates PASS; fila T-040.

> **Juez provider-agnóstico + comparación (2026-08-16):** el evaluador
> `scripts/llm_judge_naturalness.py` admite ollama/openai_compatible/anthropic
> con la misma rúbrica y la misma configuración del producto
> (`OPENAI_BASE_URL`/`API_KEY`, `ANTHROPIC_*`), y `--compare A B` compara
> dos jueces sobre la misma evidencia. Ejecución real: **deepseek-r1:8b
> media 3.38 FAIL vs qwen3-14b (LM Studio) media 4.12 FAIL** — ambos
> confirman la repetición de saludo en follow-ups (coherencia 1 con qwen);
> el 8b como juez es severo de más en persona (Δ1.55); acuerdo global 3/11.
> Corpus **430 passed / 11 skipped / 0 errores**; gates PASS; fila T-039.
>
> **Evaluación LLM-as-judge de naturalidad (2026-08-16):** el script
> `scripts/llm_judge_naturalness.py` puntúa automáticamente las respuestas
> reales del chat guardadas en `logs/rehearsal/` con un juez Ollama
> (deepseek-r1:8b, temp 0, self-consistency 3 pasadas) en cuatro dimensiones
> (fluidez, coherencia, persona, honestidad), con fact-check determinista
> contra el catálogo real (un SKU inexistente fuerza honestidad=1) y
> veredicto reproducible. Ejecución real sobre 11 respuestas: media **3.17**
> → **FAIL honesto**: deepseek-r1:8b repite el saludo en follow-ups
> (coherencia 1, hallazgo consistente) y afirma disponibilidad con stock 0;
> **ningún SKU citado es inventado** (todos existen en la BD real).
> Corpus **428 passed / 11 skipped / 0 errores**; gates PASS; fila T-038.
>
> **Cierre de venta real + adaptación idioma/registro (2026-08-15):** el
> chat ya cierra la venta completa en vivo contra el stack candidato
> (`agent-candidate-0815`): al responder `CONFIRMAR <token>` se crea el
> pedido (verificado en PostgreSQL) y se envía la factura por email con PDF
> adjunto (spool local del contenedor, asunto "Tu factura <nº> de BTOP
> Digital"; `scripts/validate_sale_live.py` **PASS 15/15**). El asistente
> adapta idioma y registro al cliente: `_detect_language_register` anexa
> una directiva determinista al prompt (inglés/formal/tuteo) y el driver
> valida las escenas `formal`/`ingles`/`tuteo` en vivo (**PASS 11/11**,
> "¿usted busca…?" / "Hello! We have…" / "¿Qué tal? … de tu interés") con
> la verificación `skus_existentes` (todo SKU citado existe en el catálogo
> real). Corpus **417 passed / 11 skipped / 0 errores**; quality gates
> D-030 PASS; filas T-036/T-037 en `TASKS.md`.
>
> **Persona por cliente + validación en vivo del chat con Ollama (2026-08-15):**
> el stack candidato (`agent-candidate-0815`) corre el chat comercial con
> Ollama (deepseek-r1:8b) sobre el catálogo real de 41.652 SKUs y la persona
> por cliente configurada (`COMMERCE_ASSISTANT_NAME=Carmen`,
> `COMMERCE_STORE_NAME=BTOP Digital` en `.env.candidate-0815`; ambas se
> pasan al contenedor vía `docker-compose.yml`). El driver
> `scripts/validate_chat_live.py` recorre el webhook real de Chatwoot (HMAC
> firmado) y valida saludos, búsquedas, comparaciones, categorías ausentes,
> memoria (2 turnos) y persona: los saludos se presentan ("¡Hola! Soy Carmen
> de BTOP Digital…") y los cierres de compra mencionan la tienda
> ("Presupuesto <id> de BTOP Digital: …"). Veredicto **PASS 8/8 turnos** con
> persistencia de memoria verificada en PostgreSQL; evidencia en
> `logs/rehearsal/chat_live_validation_*.json`. La validación además detectó
> una alucinación real (producto inventado fuera del bloque) corregida con
> `_enforce_verified_product_output`. Corpus **408 passed / 11 skipped / 0
> errores**; quality gates D-030 PASS. Detalle en `docs/TEST_EVIDENCE.md` y
> filas T-034/T-035.
>
> **Catálogo real + paginación en vivo en el stack candidato (2026-08-15):**
> el stack `agent-candidate-0815` recibe las credenciales PrestaShop reales
> (btopdigital.es) en `.env.candidate-0815` (gitignored) y se ejecuta el sync
> incremental (`POST /integrations/prestashop/sync?since=1970-01-01`):
> **41.652 productos creados en 326,5 s**, historial `success`
> (`prestashop_sync_history`), BD con `prestashop=41.652 + local=1 = 41.653`.
> `GET /catalog/products` validado en vivo a través del proxy: envelope
> `{items,total,limit,offset}` con `total=41653`, páginas disjuntas y estables,
> orden por precio/nombre, última página sin huecos, recorrido completo
> **209 páginas → 41.653 IDs únicos (coverage 100 %)**, búsqueda `rubik` → 69
> resultados, filtro `source=local` → 1 y `sort` inválido → 422. Índice
> semántico `skipped` en el candidato (sin proveedor de embeddings remoto);
> la búsqueda léxica opera. Detalle en `docs/TEST_EVIDENCE.md`.
>
> **Memoria de conversación (working tree 2026-08-15):** el chat comercial
> recuerda el contexto previo: modelo `ConversationMessage` (migración 0014),
> registro del mensaje del cliente y de cada respuesta del asistente en el
> webhook de Chatwoot, historial acotado a `COMMERCE_CHAT_MEMORY_MESSAGES`
> (12 por defecto, poda al insertar) y bloque "Conversación reciente" en el
> prompt marcado como contexto de continuidad (nunca fuente de datos).
> 4 evals nuevos; corpus **399 passed / 11 skipped / 0 errores**;
> quality gates D-030 PASS.
>
> **Calidad del chat comercial (working tree 2026-08-15):** persona por
> cliente (`COMMERCE_ASSISTANT_NAME`), prompt de sistema reescrito (más
> natural, sin duplicados, cierre variado), fallback extractivo arreglado
> (el saludo ya no responde "no encuentro productos"; categoría ausente
> honesta; resultados agrupados por categoría y acotados a 12 con nota) y
> `_polish_answer` (recorte + colapso de líneas) en respuestas LLM y
> extractivas. 5 evals nuevos; corpus **418 passed / 11 skipped / 0 errores**;
> quality gates D-030 PASS.
>
> **Pitch comercial (2026-08-15):** `docs/PITCH_COMERCIAL.md` — ficha por
> segmento (distribuidor B2B, fabricante, marketplace), diferenciadores con
> evidencia verificable (RPO/RTO SS-05, RBAC SS-04, catálogo 41.652 SKUs,
> ciclo comercial real, 413 tests) y la sección explícita de claims que NO se
> pueden afirmar aún (SBOM SS-02, TLS/DNS SS-03, soak SS-06, alertas SS-07)
> con cierre por fases; plantilla de propuesta por instancia gestionada
> rellenable y guion de llamada.
>
> **Propuesta SaaS multi-tenant (2026-08-15):** `docs/ARCHITECTURE_SAAS_MULTI_TENANT.md`
> documenta la evolución a PostgreSQL compartido con RLS: la columna
> `installation_id` ya existe en las 24 tablas owned, así que el cambio clave
> es resolver el tenant por petición (JWT `tenant_id`/subdominio) y añadir
> `FORCE ROW LEVEL SECURITY` con `set_config('app.tenant_id', ..., true)`
> por transacción. Incluye `tenants`/`tenant_subscriptions`, matriz de tiers
> Starter/Pro/Enterprise y plan por fases F0–F4. Es una propuesta de diseño
> (no implementada); pendiente de decisión de negocio.
>
> **Catálogo de triggers (working tree 2026-08-15):** se amplía el catálogo
> de automatizaciones con tareas programadas y webhooks: `prestashop_sync`
> diario (lock Redis + `since` de la última ejecución), `low_stock_alert`
> (resumen por email bajo umbral, solo catálogo de confianza, idempotente
> por ventana) y `cart_abandonment` (follow-up de presupuestos en borrador
> abandonados). Todos con aprobación (flujo request-activation + approval de
> `/scheduled-tasks`) y auditoría. Webhook `POST
> /automations/triggers/{tipo}` con gate de aprobación (409 sin tarea activa
> aprobada), HMAC (`AUTOMATION_WEBHOOK_SECRET`) o bearer admin, y payload
> fusionado. 11 evals nuevos; corpus **413 passed / 11 skipped / 0 errores**;
> dialecto PostgreSQL validado contra el catálogo real (18.734 bajo umbral 5);
> quality gates D-030 PASS.
>
> **Email real SMTP para automatizaciones (working tree 2026-08-15):** se
> implementa el envío real de recordatorios de presupuesto, dunning y
> facturas vía ``SmtpEmailProvider`` (``EMAIL_PROVIDER=smtp``, STARTTLS/SSL,
> login opcional, timeout) con registro perezoso en ``send_email`` y
> **degradación controlada auditada** al spool local si el proveedor falla
> (``EMAIL_FALLBACK_TO_LOCAL_SPOOL``, evento
> ``automation.email_degraded_to_local``); con fallback desactivado,
> fail-closed. 6 evals nuevos sin red (dobles de ``smtplib``); corpus
> **402 passed / 11 skipped / 0 errores**; quality gates D-030 PASS.
>
> **Matriz E2E SS-04 (2026-08-15):** se cierra el stop-ship SS-04 (E2E final)
> con `scripts/e2e_role_matrix.py` sobre el stack candidato: **63/63 checks
> (7 roles × 9 endpoints de módulo)** en 5.27 s con acceso 200/403 exacto a
> la matriz RBAC del backend (`READ/OPERATOR/ADMIN_ROLES`), contratos de
> respuesta verificados (envelope de catálogo, dashboard role-aware con
> `permissions.approve/manage_users`), usuarios de prueba creados,
> desactivados vía `PATCH /users/{id}` y eliminados por SQL → baseline
> `users=2`, stack 5/5 healthy. Artefacto
> `logs/rehearsal/e2e_role_matrix_20260815T145447Z.json`; evidencia en
> `docs/PRODUCTION_READINESS.md` §Evidencia SS-04.
>
> **Ensayo integral SS-05 (2026-08-15):** se cierra el stop-ship SS-05
> (restore/rollback integral) con un ensayo completo contra el PostgreSQL real
> del stack candidato `agent-candidate-0815` (Alembic `0013`): backup cifrado
> +HMAC en 10.9 s, restore verificado a destino vacío aislado, **RTO restore
> 25.2 s / rollback 25.1 s**, checks funcionales (login, catálogo, wiki
> pública) y rollback del safety backup que devuelve el estado exacto previo
> al restore. RPO validado por punto-en-el-tiempo (marcador post-backup se
> pierde en el restore y reaparece en el rollback). Evidencia completa en
> `docs/PRODUCTION_READINESS.md` §Evidencia SS-05.
>
> **Generadores SEO deterministas (T-018, working tree 2026-08-15):** se cierra el último pendiente accionable de la Ruta A: `sitemap.xml`, `blog-rss.xml`, `llms.txt`, `llms-full.txt` y `knowledge-index.json` portados de FlowWink (MIT, D-012) al motor del Bridge como `SeoGeneratorService` sobre catálogo + wiki (páginas `published`, landings `approved`, productos de orígenes de confianza sin demo y disponibles). Determinismo byte-a-byte (sin reloj de pared, orden estable, `base_url` nunca hardcodeada: query param validado o origin de la petición); salidas válidas (XML/RSS parseables, JSON con esquema 1); sin publicación externa (`X-External-Publication: not-performed`). El corpus hermético del backend pasa **373 / 373** (11 skipped opt-in) incluyendo 7 evals nuevos (`tests/regression/test_seo_generators.py`); quality gates D-030 PASS. La fila T-018 de `TASKS.md` pasa a VERIFIED.
>
> **Actualización de auditoría 2026-08-10 (HEAD `c5c0b52`):** la decisión continúa en **NOT PRODUCTION READY — CRITICAL RISK** y la evidencia verde histórica no es representativa del árbol actual. Se reprodujeron 2 fallos de integración, 8 fallos de migración causados por la revisión no versionada `0006_product_embeddings.py`, quality gates rojos y un helper de restore con `drop_all()` sin guard de destino vacío. Docker estaba detenido y el runtime no se revalidó. Informe: `docs/PROJECT_STATUS_AUDIT_2026-08-10.md`.
>
> **Remediación posterior a la auditoría 2026-08-10:** se cierran **1 P0 + 7 P1** identificados en el informe (RA-01 a RA-08 en `TASKS.md`). El corpus de tests hermético del backend pasa **241 / 241** pruebas relevantes (12 fallos preexistentes no relacionados con esta remediación; ver matriz de pendientes al final). El restore destructivo potencial queda cerrado con marker explícito; la migración `0006` se hace dialect-aware; el handler del webhook transiciona a `state="completed"` en cada rama; el chat funciona con `_default_catalog_source()`; el NameError `_LOG` se sustituye por `log_event`; el SSRF Chatwoot queda en `false` por defecto; email y webhook saliente ya no fingen éxito en errores de I/O ni en URLs privadas. Detalle completo en `CHANGELOG.md` ("Remediación de auditoría 2026-08-10").
>
> **Trabajo del 2026-08-15 (working tree, T-027):** se cierra el pendiente del catálogo del portal. Nuevo `GET /catalog/products` paginado (query/limit/offset/sort/order/source whitelisted, `updated_at`/`created_at` en cada fila) y tabla del portal con búsqueda, filtro por origen, orden ascendente/descendente, paginación y columna de frescura. El corpus hermético del backend pasa **388 / 388** (11 skipped opt-in) incluyendo 7 evals nuevos (`tests/regression/test_catalog_portal_pagination.py`); el portal pasa **27 / 27** (3 evals nuevos), typecheck, formato y build verdes; quality gates D-030 PASS (hard 0, clean 0, ratchet 129 ≤ baseline 243). Se actualizan las filas T-016 (absorbida por T-015), T-019/T-020 (RA-01/RA-02), P1-001/002/003/005/010/011/012 y T-025 (evidencia en working tree/`production-gates.yml`) a VERIFIED; la deuda documental de la sección "Pendiente" de `TASKS.md` queda al día. La decisión sigue siendo la de `docs/PRODUCTION_READINESS.md` (2026-08-15): **NOT PRODUCTION READY — REMEDIATION INCOMPLETE**, bloqueada por los stop-ships SS-01…SS-07 (release/checkout inmutable, imágenes finales, TLS/DNS, E2E final, restore/rollback integral, soak y alertas).

**Fecha:** 2026-08-06
**Rama:** `production-remediation`
**Recovery commit:** `ed77056`
**Commit P0:** `de236e9`
**Commit P1 de invariantes:** `48051e8`
**Commit harness hermético (D-032):** `4afd0c7`
**Commit tool policy (D-012):** `4d97449`
**Commit resiliencia (D-021):** `3733bad`
**Commit crash recovery (D-035):** `5a3edf8`
**Commit reconciliación GHL (D-010):** `ce2723c`
**Commit clasificación/DLP RAG (D-020):** `0541650`
**Commit dependencias (D-017):** `7fb4f45`
**Commit observabilidad (D-028):** `af53b8b`
**Commit lifecycle (D-029):** `ff0eed8`
**Commit portal/docs (D-026/D-027):** `33d77c1`
**Commit quality gates (D-030):** `ca73a6c`
**Commit automatizaciones FlowWink lote 1 (D-012):** `bf647cf`
**Commit Agentes/IA FlowWink lote 2 (D-012):** `59558a1`
**Commit backup/restore/rollback (D-015/D-016):** `6b34200`
**Commit infra runtime (D-008/D-025):** `f6137e0`
**Commit chat sin Chatwoot + E2E (Ruta A):** `c2f4b84`
**Commit preflight puertos (D-009):** `19e7f71`
**Commit validación stricta (D-022):** `6c689da`
**Commit licencias (D-023):** `8a098f3`
**Fase activa:** Fase 3 — extracción de automatizaciones FlowWink sin Supabase (Wave 1 de P1/P2 agotada)
**Ruta aprobada:** Ruta A — candidata core con limitaciones documentadas (`DECISIONS.md` D-007)
**Decisión:** **NOT PRODUCTION READY — REMEDIATION INCOMPLETE** (autoritativa: `docs/PRODUCTION_READINESS.md` 2026-08-15)

## Estado verificable

- Auditoría 2026-08-10: backend unitario 23 passed; integración 2 failed/30 passed/3 skipped; regresión parcial 8 failed/187 passed/6 skipped; suite completa sin resultado por timeout; quality gates FAIL; portal typecheck/test/build PASS, format/ESLint FAIL; audit npm completo con 1 HIGH; Docker/runtime BLOCKED.
- Stop-ship reabiertos: restore destructivo potencial (`backup.py:165-171`), migración `0006` sin seguimiento e incompleta, idempotencia del webhook en `processing`, core local excluido del chat por filtro rígido PrestaShop, SSRF Chatwoot habilitado y configuración TLS/production incompleta.

- El workspace fue entregado sin `.git`; se inicializó un repositorio local y se creó un punto de recuperación antes de la remediación.
- Compose declara 14 servicios, 3 redes y 9 volúmenes; la configuración sintáctica se valida.
- Todos los contenedores del proyecto están detenidos. Los volúmenes permanecen intactos.
- El host tiene 31,46 GiB de RAM y estaba al 87,7 % de uso en la captura de baseline; no se iniciará build/full stack hasta disponer de margen seguro.
- Los seis P0 reproducidos están corregidos y verificados en `de236e9`: demo, confirmación, pricing/fiscalidad, stock, migraciones y aislamiento por instalación.
- El corpus backend pasa 159 pruebas y las migraciones herméticas 23; las reproducciones rojas de Fase 1 se conservan como evidencia histórica previa a cada fix.
- PostgreSQL 15 efímero verificó la revisión `0003`, 12 FKs compuestas `DEFERRABLE INITIALLY DEFERRED`, confirmación, aprobación CAS, presupuesto LLM, oversell, carreras de reservas, `python -O`, downgrade/reupgrade y adopción histórica; cada ensayo terminó sin filas ni contenedores residuales.
- `48051e8` cerró seis P1 y un P2: aprobación CAS, Activepieces estricto, coste/presupuesto IA, paginación/visibilidad PrestaShop, importación atómica idempotente y health separado. Sumado al verificador PostgreSQL cerrado en `de236e9`, hay siete P1 verificados; Webhooks/GHL, RAG, resiliencia, perfil seguro y handoff conservan alcance parcial o live pendiente.
- El 2026-08-03 se re-verificó el corpus en vivo: la corrida combinada reproducía 2 fallos por contaminación de entorno (D-032); tras `4afd0c7` el corpus combinado pasa 159/159 en ambos órdenes de colección con entorno limpio. D-032 queda VERIFIED (P2).
- El 2026-08-03 se cerró D-012 con `4d97449`: `ToolExecutor` deny-by-default (`/agents/tools/invoke`), allowlist estricta por agente, argumentos validados, herramientas financieras prohibidas y auditoría; 10 evals nuevos y corpus combinado 169/169.
- El 2026-08-03 se cerró D-021 con `3733bad`: circuit breakers por proveedor en los cuatro adapters HTTP, outbox durable con claim CAS, backoff determinista y DLQ (`OutboxService`, migración `0004`), captura GHL reencolada con checkpoints durables, endpoints `/outbox*` con roles y métricas; 18 evals nuevos y corpus combinado 187/187 en ambos órdenes de colección.
- El 2026-08-03 se cerró D-035 con `5a3edf8`: el webhook checkpointa el resultado tras cada efecto externo visible y el takeover con checkpoint de éxito completa sin repetir efectos (`_resume_webhook_from_checkpoint`); 3 evals de crash/recovery y corpus combinado 190/190 en ambos órdenes de colección. La microventana efecto→checkpoint persiste hasta disponer de claves de idempotencia del proveedor (D-010).
- El 2026-08-03 se cerró D-010 con `ce2723c`: como GHL no acepta claves de idempotencia, la microventana efecto→checkpoint (residual de D-035) se cierra con reconciliación previa al efecto (`find_opportunity_by_reference` por custom field `external_reference` y `find_note_by_body`) en el dispatcher del outbox y en `/integrations/ghl/leads`; una búsqueda fallida falla cerrada, un lead sin referencia va directo a DLQ y cada reconciliación queda auditada (`ghl_lead_reconciled`); 6 evals nuevos y corpus combinado 196/196 en ambos órdenes de colección. Residual: contrato live del endpoint de búsqueda pendiente de sandbox GHL (B-004).
- El 2026-08-03 se cerró D-020 con `0541650`: clasificación public/internal/confidential/restricted con ACL deny-by-default (legado sin clasificación conserva ACL estricta), DLP determinista en ingesta (DNI/NIE con letra, tarjeta con Luhn, IBAN ES mod-97, JWT, AWS, claves sk_live, claves privadas) que eleva la clasificación a confidential sin persistir valores y redacta respuesta y citas, bloqueo de consultas con patrones de inyección y marcado `trusted=false` del contenido recuperado; 10 evals nuevos y corpus combinado 206/206 en ambos órdenes de colección.
- El 2026-08-03 se cerró D-017 con `7fb4f45`: Pillow fijado en 12.x (cierra 49 CVEs en 10.x/11.x), pypdf en 6.x (cierra CVE de 5.9.0), Vite subido a ^7 (esbuild path traversal cerrado); script `scripts/audit_dependencies.py` ejecuta pip-audit + npm audit y falla si high/critical >0; 6 evals nuevos y corpus combinado 212/212 en ambos órdenes de colección.
- El 2026-08-03 se cerró D-028 con `af53b8b`: middleware FastAPI con logs JSON correlacionados (correlation_id/request_id/tenant_id/user_id/route/method/status/latency_ms), contextvars por proceso con restauración robusta, helpers `log_event` y `record_metric` con redacción determinista (password/secret/token/bearer/private_key/JWT/sk_live/tarjeta/clave privada), métricas Prometheus para HTTP/outbox/breaker/RAG/alerts y reglas in-memory (`circuit_breaker_open`, `outbox_dead_letter_growth`, `rag_abstention_rate`, `dlp_findings`) integradas en `/metrics` con `recent` y `evaluated`; 10 evals nuevos y corpus combinado 222/222 en ambos órdenes de colección.
- El 2026-08-03 se cerró D-029 con `ff0eed8`: `LifecycleService` con export JSON portable de datos operativos (sin users ni AuditLog), erase con retención configurable e inmediata, proceso de borrados vencidos y legal hold que bloquea cualquier erase mientras está activo; borrado en orden FK con eliminación de archivos RAG dentro del directorio de subidas; modelo `InstallationLifecycle` + migración aditiva `0005`; endpoints `/lifecycle/*` con `ADMIN_ROLES` y auditoría completa; 6 evals nuevos y corpus combinado 228/228 en ambos órdenes de colección. Residual: revisión legal de la política de retención (B-008).
- El 2026-08-03 se cerraron D-026/D-027 con `33d77c1`: README reescrito contra la fuente autoritativa y banners SUPERSEDED en `REMEDIATION_REPORT`, `MASTER_PLATFORM_REPORT`, `FINAL_REPORT` y `COMMERCIAL_READINESS_REPORT`; la navegación del portal deja de prometer módulos fantasma (cinco anchors rotos) con secciones reales respaldadas por `GET /tools/products`, nuevo `GET /rag/documents`, `GET /agents` y `GET /users`; runner frontend vitest + testing-library + vitest-axe con 5 evals verdes; 1 eval backend nuevo y corpus combinado 229/229. Residual: E2E visual en viewports acordados (Fase 19).
- El 2026-08-03 se cerró D-030 con `ca73a6c`: `scripts/quality_gates.py` con tres puertas (`ruff-hard` E9,F a 0, `ruff-clean-zone` a 0 y `ruff-ratchet` con baseline visible de 213 en `scripts/quality_baseline.json`), B008 excluido globalmente por el patrón `Depends()` de FastAPI, deuda de estilo en tests legacy corregida; 6 evals nuevos y corpus combinado 235/235 en ambos órdenes de colección. Con este cierre la Wave 1 (defectos corregibles sin runtime) queda agotada; los P1 restantes requieren runtime/Docker o decisión del propietario.
- El 2026-08-04, tras la decisión D-012 (propietario rechaza Supabase y selecciona extraer 6 dominios de FlowWink al Bridge), se entregó el lote 1 de automatizaciones con `bf647cf`: `app/services/automations.py` con router de email de proveedor local (sin red), `quote-expiry-reminders` idempotente por ventana, `dunning-processor` que solo notifica y marca `overdue` sin mutar importes, `generate-invoice-pdf` determinista de solo lectura, `send-webhook` firmado HMAC sobre circuit breaker y sweep agregado pull; endpoints `/automations/sweep` y `/automations/invoices/{id}/pdf` con roles. 7 evals nuevos; corpus 242/242; `automations.py` entra en la zona limpia del gate D-030. Esto es funcionalidad nueva (T-015), no cierra defectos: los conteos P0/P1/P2 no cambian.
- El 2026-08-04 se verificaron D-015 y D-016 con `6b34200`: `app/services/backup.py` con `create_backup` (manifiesto con conteos+sha256 por tabla), `restore_backup` a motor vacío y `verify_backup`; **restauración REAL** verificada en SQLite (hermético) y en PostgreSQL efímero (opt-in, contenedor pgvector, dos BDs, extension vector); `rollback_installation` restaura los datos de una instalación a un punto conocido tras una mala release, independiente del resto. 4 evals; corpus 248. Cierra dos P1: quedan 9 abiertos, todos de runtime/bloqueados.
- El 2026-08-04 se entregó el lote 2 de Agentes/IA con `59558a1`: `app/services/agent_ai.py::docs_chat` (port de `docs-chat` de FlowWink) con búsqueda RAG y ACL por rol, abstención sin evidencia, citas verificables y respuesta extractiva honesta cuando no hay proveedor LLM real (B-006); endpoint `/agents/docs-chat` con roles. 3 evals nuevos; corpus 245/245; `agent_ai.py` en zona limpia del gate D-030. Funcionalidad nueva (T-017), no cambia conteos de defectos.
- El 2026-08-03, con autorización del propietario, se detuvieron los tres compose projects del workspace antiguo (`agent-platform`, `agent-piloto-rc1`, `agent-cliente-demo-es-staging`); volúmenes intactos y puerto 9000 liberado. La memoria de la VM Docker queda pendiente de liberación/medición (B-001 mitigado).
- Permanecen 6 P1 y 0 P2 no verificados; no existe candidata de release ni evidencia E2E/live suficiente.
- El 2026-08-04 se produjo la matriz de licencias (D-023, `8a098f3`): `LICENSE` raíz, `THIRD_PARTY_NOTICES.md` actualizado y `docs/LICENSE_MATRIX.md` con licencias Python verificadas vía `importlib.metadata`; vendor/EE marcados "requiere revisión legal" (B-008). D-023 pasa a FIXED (aprobación legal pendiente antes de release).
- El 2026-08-04 se cerró D-022 con `6c689da`: `validate_runtime_security` (llamada al arrancar) rechaza en producción SQLite, CORS/host abiertos y DEBUG, además de secretos débiles, mocks/stubs, demo y presupuestos de retry/breaker/outbox; 12 evals. D-009 quedó FIXED con preflight atómico de puertos (`19e7f71`, verificación live pendiente de Docker).
- El 2026-08-04, con Docker operativo, se levantó el perfil **core** y se verificó en runtime: proxy healthy con `cap_add SETUID` (26 workers sin `setuid EPERM`, D-008), upstreams opcionales (chatwoot/activepieces) con resolución perezosa que dejan arrancar el core sin ellos (502 graceful), límites `deploy.resources` aplicados por contenedor (D-025) y smoke 200 por el puerto 9000 (portal/api/flowwink). El host queda ~3,9 GB libres con el core arriba.
- El 2026-08-04 se desacopló el canal de respuesta de Chatwoot (`c2f4b84`): cuando `CHATWOOT_API_TOKEN` no está configurado, el webhook degrada el reply/efectos a un canal interno auditado y el core completa **chat → lead → presupuesto sin dependencias externas**. **E2E en vivo verificado**: webhook firmado HMAC → `quote_created` con total determinista 136,00 (2×50 +21 IVA +15 envío) y token `CONFIRMAR <TOKEN>`; reproducible con `scripts/e2e_core_chat_to_quote.py`.
- El 2026-08-06 se cerró la mejora **catálogo verificado en preguntas libres de chat (catalog_overview)**: cuando el cliente pregunta algo genérico tipo "¿qué tenéis?", "¿qué me recomiendas?" o nombra un dominio sin match específico, el flujo `/webhooks/chatwoot` cae a un resumen del catálogo sincronizado desde PrestaShop (límite 8, sin LLM) en lugar de transferir al equipo comercial o de abstenerse; helper `_looks_like_product_inquiry` detecta intención de catálogo (tokens de producto/catálogo/existencias/recomendación + hints de dominio) y respeta la rama previa `verified_product_recommendations` cuando hay coincidencia específica; 3 evals nuevos. En el mismo cambio se añade `SAFE_FETCH_ALLOW_PRIVATE_NETWORK: "true"` al bloque `&chatwoot-environment` del compose para que el webhook pueda entregar al hostname interno `bridge-api` en desarrollo sin ser filtrado por `vendor/chatwoot/lib/safe_fetch.rb`; en producción el webhook debe ir a un dominio público y la variable debe quedar apagada. Wave 1 cerrada por completo: los seis P1 restantes son runtime/bloqueados (egress live D-006, preflight de puertos live D-009, handoff Chatwoot live D-019, release/imágenes por digest D-016-residual, alcance FlowWink D-018 y licencias D-023).
- El build del portal fue reproducido anteriormente; la UX dinámica permanece sin validar.

## Stop-ship abiertos tras el cierre P0

1. Webhooks/GHL ya tienen inbox durable, lease, checkpoints, recuperación de crash ambiguo tras efecto y reconciliación previa al efecto (D-010 cerrado); queda el fault injection live contra el proveedor real (bloqueado por B-004).
2. RAG ya tiene clasificación, DLP y corpus anti prompt injection verificados en `0541650`; queda el dataset de exfiltración a escala real y el E2E del proveedor RAG real (B-006 bloquea el sandbox).
3. Egress, proxy y Chatwoot no están verificados en runtime; la asignación de handoff solo está demostrada con contratos locales.
4. Restore, release/rollback, recursos y licencias siguen sin gate aprobado; dependencias (`7fb4f45`) y observabilidad (`af53b8b`) verificadas.
5. No existe release candidata, build limpio ni E2E crítico completo contra proveedores locales/sandbox autorizados.

## Fases

| Fase | Estado | Evidencia o bloqueo |
|---|---|---|
| 0 — Baseline | VERIFIED | Cuatro documentos completos; topología, estados, enlaces y Compose contrastados sin arrancar servicios |
| 1 — Reproducción | VERIFIED | 19 tests rojos; registros de defectos/riesgos/evidencia; 32 defectos contrastados |
| 2 — P0/P1 | IN PROGRESS | Seis P0, veinte P1 y cinco P2 `VERIFIED`; quedan 6 P1 no verificados (egress live, preflight puertos [FIXED], handoff Chatwoot live, release/imágenes por digest, alcance FlowWink, licencias) |
| 3 — Runtime/core | IN PROGRESS | Perfil core levantado y verificado en runtime (proxy SETUID healthy, límites de recursos, smoke por proxy); pendiente perfil full y E2E |
| 3–29 | BLOCKED | Orden obligatorio; dependen de P0/P1 y core estable |
| Release | BLOCKED | No se cumplen gates de producción |

## Fuente de verdad

- Readiness: `docs/PRODUCTION_READINESS.md`.
- Trabajo: `TASKS.md`.
- Bloqueos: `BLOCKERS.md`.
- Evidencia: `docs/TEST_EVIDENCE.md`, `docs/baseline/` y `docs/remediation/`.
- Auditoría de origen: `docs/PROJECT_TECHNICAL_AUDIT.md`.
- Informe de sesión 2026-08-16 (P1-c/P1-d/P2-e): `docs/SESSION_LOG_CRM_2026-08-16.md`.
- Handoff para el siguiente agente: `docs/HANDOFF_CONTINUACION_CRM.md`.
