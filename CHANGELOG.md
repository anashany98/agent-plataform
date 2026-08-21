# Changelog

Todos los cambios relevantes de la remediación se documentan aquí. El proyecto adopta SemVer cuando exista una primera candidata reproducible.

## [Órdenes de acción por módulo en el chat — 2026-08-18]

- **T-075 (Chat/CRM, VERIFIED):** el CEO agent pasa de informar a **actuar**
  con 4 intents de acción por módulo (`ceo_agent.py` + `agent_proposals.py`):
  - **`lead_create`** «crea un lead ana@… de Empresa SL» → propuesta
    `agent_proposal:ceo_create_lead` (dedupe por email) → al aprobar crea
    el lead real (`source=local`, `status=new`).
  - **`opportunity_move`** «mueve la oportunidad X a negociación» →
    propuesta `agent_proposal:ceo_move_opportunity` (match por id, nombre o
    referencia; etapa por key o nombre de `PipelineStage`) → al aprobar
    cambia `stage` + `stage_changed_at` y encola el webhook saliente
    `pipeline.stage_changed`.
  - **`task_create`** «crea una tarea para llamar a Carlos» → propuesta
    `agent_proposal:ceo_create_task` → al aprobar crea la `Activity`
    pendiente con `kind` según el verbo (llamada/reunión/follow-up/email).
  - **`campaign_launch`** «lanza una campaña «Oferta X»» → propuesta
    `agent_proposal:ceo_launch_campaign` (dedupe por nombre) → al aprobar
    crea la campaña como borrador (plantilla activa si existe; fail-closed:
    nunca envía sin plantilla/segmento) o activa la existente.
  Todas siguen deny-by-default (propuestas `pending` en Aprobaciones; solo
  se auto-ejecutan dentro de la autonomía autorizada del CEO agent, T-068)
  y la aprobación aplica la mutación en la misma transacción con auditoría
  `agent_proposal.executed`. 7 evals nuevos (45/45 en `test_p1_ceo_agent`);
  corpus **644 passed / 12 skipped**; gates D-030 PASS. Validado en vivo
  contra el PostgreSQL real: lead creado, oportunidad `new → negotiation`
  con webhook, actividad `call` creada y campaña borrador creada; datos de
  prueba limpiados.

## [Voz en el chat y digest diario — 2026-08-18]

- **T-073 (Portal, VERIFIED):** entrada por voz en el chat universal con
  Web Speech API (`ceoChat.tsx`): botón micrófono con estado pulsante,
  el dictado (es-ES) rellena el input para que el usuario pueda corregir
  antes de enviar y el envío usa **exactamente el mismo pipeline de
  intenciones** que el tecleado (`/ceo/chat`). Errores amigables
  (permisos, sin voz, sin conexión) y degradación fail-closed en
  navegadores sin soporte (el botón no aparece). 5 evals nuevos
  (`ceoChat.test.tsx`); portal **98 vitest + tsc + build**.

- **T-074 (Agentes/Email, VERIFIED):** **digest diario por email**
  (`services/daily_digest.py` + `POST /digest/send` + tarea programada
  `daily_digest` activa): cada día el dueño recibe (1) las **decisiones de
  los agentes** de las últimas 24 h (agente, acción, desviación, estado)
  con la instrucción **«REVERTIR <id>»** por decisión en vigor; (2) las
  **propuestas pendientes** de aprobación (primeras 8 + total); (3) las
  **métricas clave** (oportunidades, ticket medio, pipeline, pedidos,
  aprobaciones, stock bajo, agentes activos). Responder al correo con
  «REVERTIR <id>» anula la decisión con la misma trazabilidad del portal
  (`autonomy.revert_decision`, la evidencia nunca se borra) y responde la
  confirmación por el spool/SMTP. Sin `OWNER_COMMAND_EMAIL` → omitido
  auditado. 7 evals nuevos (`test_p1_daily_digest.py`); corpus **637
  passed / 12 skipped**; gates D-030 PASS. Validado en vivo contra el
  PostgreSQL real: dry-run con datos reales (1 decisión, 21 propuestas),
  envío real al spool (`queued_for_manual_delivery:…`), decisión sembrada
  revertida por email (actividad `cancelled`, `reverted_by` del dueño,
  confirmación en el spool) y tarea diaria creada y activa.

## [Onboarding guiado — 2026-08-18]

- **T-072 (Portal, VERIFIED):** al **primer acceso** se abre un asistente
  paso a paso para personas sin experiencia técnica: (1) explica que la
  landing es «tu empresa en una conversación» (una sola persona gestiona
  casi todo con agentes de IA); (2) invita a probar **3 preguntas de
  ejemplo** («¿cómo van las ventas?», «¿qué hay que aprobar?», «¿hay stock
  bajo?») que se envían al chat universal real y muestran la respuesta con
  datos de la empresa; (3) activa el **modo guiado**: mientras no se
  complete, la barra lateral solo muestra Asistente y Resumen, con un botón
  «Mostrar todos los módulos» (en el overlay y en la barra lateral) para
  revelarlos cuando el usuario se sienta cómodo. La preferencia persiste en
  localStorage (`guided-onboarding`), así que no vuelve a aparecer.
  Implementación: `portal/src/onboarding.tsx` (nuevo), `CeoChat` con
  handle imperativo `send()` (forwardRef, compatible con su uso compacto),
  `App.tsx` (estado guidedMode, filtro de nav, overlay) y `styles.css`.
  8 evals nuevos (`onboarding.test.tsx`: primer acceso, preguntas enviadas
  al chat real, revelar módulos, seguir en guiado, persistencia, omitir y
  axe); portal **93 vitest + tsc + build**. Validado en vivo contra el
  candidato (preview + contenedor reconstruido): flujo completo paso a paso
  con respuesta real del chat (ticket medio 43.25 EUR) y navegación
  revelada al terminar.

## [App simple con chat universal — 2026-08-18]

- **T-071 (Portal/Agentes, VERIFIED):** la app pasa a ser manejable por
  **una sola persona**: nueva sección **«Asistente» como landing** con el
  chat universal como centro de mando (componente `CeoChat` reutilizable,
  variante grande en el landing y compacta en la sección de agentes).
  El chat ahora **gestiona agentes y automatizaciones** en lenguaje natural:
  `automations_status` (qué automatizaciones hay, próxima ejecución),
  `agents_status` (qué agentes gestionan cada módulo) y `automation_toggle`
  (pausar/activar una automatización → propuesta `agent_proposal:automation_toggle`
  que se aplica al aprobar en el panel; match por nombre, parte del nombre o
  tipo de tarea). **Moneda EUR explícita** en el texto del landing y en las
  respuestas (ya era el default de backend/portal).
  Bug encontrado en vivo y corregido: el toggle exigía el nombre completo
  de la tarea en el mensaje; ahora «pausa el barrido E2E» encuentra
  «Barrido E2E e2ef…». 2 evals nuevos (38/38 en `test_p1_ceo_agent.py`);
  corpus **629 passed / 12 skipped**; gates D-030 PASS (deuda 132 < 133);
  portal 85 vitest + tsc. Validado en vivo contra el candidato: intents
  `automations_status`/`agents_status`/`automation_toggle` sobre el
  PostgreSQL real, ciclo propuesta → aprobación → pausa aplicada, y el
  chat desde el portal contra el candidato con la moneda EUR visible.

## [Cierre mensual en piloto automático — 2026-08-17]

- **T-070 (P2 Backend, VERIFIED):** primer proceso completo con agente
  coordinador (`finance_agent`). `POST /finance/monthly-close` ejecuta en un
  solo disparo: (1) **reconciliar** pedidos confirmados del periodo contra
  facturas (solo lectura), (2) **emitir facturas** — cada pedido sin factura
  crea `InvoiceDraft` + `ApprovalRequest` `issue_invoice` con `value_eur`;
  con la autonomía del agente (T-068) activa y bajo el umbral se emite y
  envía al instante con el PDF adjunto, `AgentDecision` y auditoría
  `agent_decision.auto_executed`; si no, queda pendiente de aprobación
  humana (política financiera deny-by-default) —, (3) **disparar dunning** de
  facturas vencidas (solo en modo autónomo; manual → diferido informado) y
  (4) **generar el reporte** mensual y enviarlo al dueño
  (`OWNER_COMMAND_EMAIL`) por el router de email con degradación al spool.
  `dry_run=True` proyecta sin mutar nada. `finance_agent` registrado en
  `AGENT_REGISTRY` (módulo `finance`, tools read-only). 7 evals herméticos
  nuevos; corpus **620 passed / 12 skipped**; gates D-030 PASS. Validado en
  vivo contra el PostgreSQL real: dry-run sobre los pedidos reales del mes;
  pedido sembrado → modo manual = propuesta pendiente; autonomía con umbral
  1000 € → factura auto-emitida (`approved`) con decisión, auditoría y email
  con PDF en el spool; datos de prueba limpiados y autonomía restaurada.

## [Superficie de mando del dueño (email/WhatsApp) — 2026-08-17]

- **T-069 (P2 Backend, VERIFIED):** el propietario consulta y da órdenes a
  los agentes desde el canal que ya usa, sin abrir el portal. **Email**: el
  webhook `POST /commands/email/webhook` (HMAC con
  `OWNER_COMMAND_EMAIL_WEBHOOK_SECRET`) entrega el correo del dueño, la
  intención se resuelve con el CEO agent (misma memoria por conversación) y
  la respuesta sale por `send_email` → SMTP real o spool local con
  degradación auditada. **WhatsApp**: en el webhook de escucha social, el
  número del dueño (`OWNER_COMMAND_PHONE`) se intercepta ANTES del triaje
  comercial, se resuelve con el CEO agent y la respuesta se registra como
  mensaje saliente (`direction="out"`) en el mismo canal. Fail-closed:
  identidad vacía = desactivada; remitente/número desconocido → ignorado de
  forma auditada sin respuesta (202/200 `ignored`); sin secreto o firma
  inválida → 401. Auditoría `ceo_command.email` / `ceo_command.whatsapp`
  (+ `.ignored`/`.rejected`) con intención, proveedor y referencia de la
  respuesta. 7 evals nuevos; corpus **613 passed / 12 skipped**; gates D-030
  PASS (deuda 132 < 133); validado en vivo contra el candidato: correo del
  dueño → `sales_summary` con reply `queued_for_manual_delivery` en el
  spool real, WhatsApp del dueño → `owner_command` con `pipeline_status` y
  reply outbound, desconocidos ignorados, y auditoría completa en
  PostgreSQL.

## [Autonomía por excepción — 2026-08-17]

- **T-068 (P2 Backend + Portal, VERIFIED):** la aprobación por caso se
  convierte en **supervisión por excepción**. Cada agente tiene una
  configuración por instalación (`AgentAutonomy`: modo `manual`/`autonomous`,
  umbral en EUR, flags de follow-ups y descarte de spam, avisar solo si se
  desvía) — deny-by-default: sin configuración nada cambia. Dentro del
  umbral, las propuestas se auto-ejecutan en la misma transacción que la
  aprobación humana (`reviewed_by=agent:<id>`), se registran en
  `AgentDecision` (con efecto, desviación y auditoría
  `agent_decision.auto_executed`) y aparecen en el **digest diario**
  (`GET /agents/digest`) con totales por agente y pendientes humanas. El
  dueño revierte con un clic (`POST /agents/decisions/{id}/revert`,
  auditado, doble revert → 409): follow-up → `cancelled`, spam → `triaged`.
  Endpoints `GET/PUT /agents/autonomy` (PUT solo admin, auditado
  `agents.autonomy_updated`). Portal: paneles «Autonomía por excepción» y
  «Digest de decisiones de los agentes» en Agentes de IA. Integrado en la
  ronda de propuestas (CRM/social) y en el CEO chat (follow-up de leads
  fríos se ejecuta al instante dentro de la autonomía y la respuesta lo
  dice). Migración `0025`. 9 evals nuevos; corpus **606 passed / 12
  skipped**; gates D-030 PASS (deuda 132 < 133); portal **85 vitest** +
  tsc + build; validado en vivo contra el candidato (migración 0025 en
  PostgreSQL real): CEO autónomo → follow-up auto-ejecutado con
  `decision_id`, digest con `executed_by: agent:ceo_agent`, revert en vivo
  y doble revert 409; por UI el panel guarda el modo y el digest muestra la
  decisión revertida por admin.

## [CEO agent: mando en lenguaje natural para el dueño — 2026-08-17]

- **T-067 (P2 Backend + Portal, VERIFIED):** nueva capa de dirección —
  `POST /ceo/chat` resuelve la intención del dueño de forma **determinista**
  (normalización + catálogo de palabras clave con puntuación, sin LLM para
  el enrutado) y delega en los datos reales de los módulos: ventas,
  pipeline, leads, actividades, aprobaciones, bandeja social y stock. Las
  lecturas se sintetizan con el LLM configurado (Ollama en el candidato) o
  con plantillas deterministas honestas (nunca inventa cifras). Las
  **acciones** (follow-up de leads fríos) NO se ejecutan: crean propuestas
  `agent_proposal:ceo_follow_up` pendientes de aprobación, y aprobarlas
  crea la actividad en la misma transacción (auditado). El `ceo_agent`
  queda registrado (módulo `Dirección (CEO)`, 9 tools read-only) y aparece
  en el panel de supervisión. Cada mensaje usa la memoria de conversación
  y se audita como `ceo_chat.message`. Portal: panel «Chat de dirección
  (CEO)» en Agentes de IA con burbujas, sugerencias y meta de intención.
  Corpus **597 passed / 12 skipped**; gates D-030 PASS (deuda 133 =
  baseline); portal **85 vitest** + tsc + build. En vivo contra el
  candidato: ventas/pipeline respondidos por Ollama con números reales,
  20 propuestas CEO creadas (2 rondas de 10, dedupe por lead), aprobación
  con actividad creada, supervisión con ceo_agent y chat funcional en el
  preview.

## [Segmented controls iOS en la barra superior — 2026-08-17]

- **T-066 (P2 Portal, VERIFIED):** los icon-buttons de tema y densidad se
  sustituyen por dos segmented controls estilo iOS («Claro/Oscuro» y
  «Cómodo/Compacto») con `role="group"`, etiquetas accesibles y
  `aria-pressed` en el segmento seleccionado. CSS iOS: track gris
  redondeado con hairline, thumb blanco con sombra y texto del acento de
  instalación, variante oscura (thumb #1C1C1E) y compacta (28px); se
  eliminaron los iconos Moon/Sun/Rows3 (solo se usaban ahí). Portal **85
  vitest** (1 nuevo del segmented de tema + el de densidad actualizado a
  la semántica segmented), tsc y build OK; backend intacto.

## [Identidad del rediseño en PDFs/facturas — 2026-08-17]

- **T-065 (P2 Backend, VERIFIED):** la factura en PDF (`generate_invoice_pdf`,
  determinista y de solo lectura) adopta la identidad del rediseño iOS:
  barra de marca de 60pt con el **acento de la instalación** (T-061,
  resuelto de `InstallationAppearance` sin efectos secundarios; default
  #246bfd sin `db`), marca «Agentes IA / Control empresarial» en blanco,
  título FACTURA + número en Helvetica-Bold, filas de metadatos
  (Cliente/Pedido/Estado/Moneda/Emitida) con etiqueta gris y valor oscuro,
  bloque TOTAL alineado a la derecha y pie de solo lectura. La etiqueta
  del cliente ahora resuelve nombre + email desde la BD en vez del id
  crudo, y la puntuación no-latin-1 (em/en-dash) se normaliza para que
  nunca salga `?`. Helvetica/Helvetica-Bold (el equivalente PDF de
  SF Pro/Segoe UI) sin dependencias nuevas. 3 evals nuevos; corpus
  **569 passed / 12 skipped**; gates D-030 PASS (deuda 132 < 133). En vivo
  contra el candidato: el endpoint HTTP sirve el PDF con el acento de la
  instalación y el acento teal cambia la barra al instante (E2E
  default→teal→restore). También se endureció el seed del test de
  supervisión (timestamps relativos a ahora) para eliminar un flake del
  corpus.

## [Auditoría de contraste y proporciones del rediseño — 2026-08-17]

- **T-064 (P2 Portal, VERIFIED):** revisión de contraste WCAG del
  rediseño iOS en las secciones del CRM (kanban, calendario, tareas).
  Corregido: título del calendario pasaba de «agosto de 2026» a
  «Agosto De 2026» por un `text-transform: capitalize` (ahora la
  capitalización se hace en JS y se quitó el transform); los estados
  `.status.ok` (#16885a, 4.01:1) y `.status.warning` (#a26b00, 4.17:1)
  no alcanzaban AA 4.5:1 en claro (→ #0f7a4c 4.83:1 y #8a5a00 5.46:1,
  manteniendo el tono); los chips de score de la búsqueda semántica
  tenían margen justo (#1a7f37/#9a6700/#8250df → #166534/#8a5c00/#7a45d6,
  ahora ≥5:1); y el calendario en modo oscuro tenía los números de día
  blancos sobre celdas blancas (#fff hardcodeado, ratio 1:1) y los
  días fuera de mes blanco sobre gris claro (1.06:1) — ahora celdas
  #1C1C1E con overrides para out-month, weekday, hora del item, hover
  y bordes (17:1 y 18.7:1). Verificado en vivo claro+oscuro con ratios
  computados; portal 84 vitest + tsc + build OK; backend intacto.

## [Rediseño iOS / minimalista del portal — 2026-08-17]

- **T-063 (P2 Portal, VERIFIED):** capa final de CSS que redefine el
  sistema de diseño completo: fondos system gray (#F2F2F7 claro / #000
  oscuro), tarjetas blancas (/#1C1C1E) con esquinas 18-22 px y hairline
  borders, tipografía del sistema (SF Pro/Segoe UI), sidebar translúcida
  estilo iPad (backdrop-blur, pill de acento, sin navy ni glow), botones
  planos de un solo acento (#007AFF / #0A84FF, que sigue siendo
  `var(--accent)` para el selector por instalación), tablas iOS sin cebra,
  alertas planas tintadas, kanban con tarjetas blancas y login sin franja
  de gradiente. Se eliminan las animaciones decorativas (rise-in,
  brand-glow, pulse de carga) y los gradientes/sombras pesadas — el look
  «hecho con IA» desaparece. Sin cambios de comportamiento: portal **84
  vitest**, tsc + build OK; corpus backend intacto (565/12), gates D-030
  PASS; verificado en preview light + dark (screenshots).

## [Modo de densidad del portal — 2026-08-17]

- **T-062 (P2 Portal, VERIFIED):** preferencia de densidad por usuario
  (`comfortable`/`compact`) persistida en localStorage y aplicada con
  `data-density` sobre `documentElement` (mismo mecanismo que el tema).
  Toggle `Rows3` en la barra superior junto al del tema, con
  `aria-pressed` y tooltip. CSS `:root[data-density="compact"]`: reduce
  paddings/gaps de content, sidebar, paneles, métricas (min-height
  126→92), tarjetas de recurso, formularios, tablas, badges/status/counter,
  grids, kanban, calendario, supervisión y panel de apariencia; h1/h2 más
  pequeños. Se combina con tema claro/oscuro y acento de instalación. 1
  vitest nuevo; portal tsc + build + **84 vitest**, corpus backend intacto
  (565/12), gates D-030 PASS; verificado en preview con computed styles
  reducidos y screenshot del resumen compacto.

## [Color de acento configurable por instalación — 2026-08-17]

- **T-061 (P2 Portal, VERIFIED):** modelo `InstallationAppearance` (una
  fila por instalación, patrón get-or-create) con `accent_color` #RRGGBB
  validado por regex (fail-closed, sin inyección CSS) y `updated_by`;
  migración `0024` idempotente con paridad de esquema. Endpoints
  `GET /appearance/settings` (READ_ROLES, default #246bfd) y
  `PUT /appearance/settings` (solo admin, auditado
  `appearance.settings_updated`; hex inválido o `extra` → 422; re-PUT sin
  cambio no re-audita). El portal carga el acento al entrar y lo aplica a
  `--accent`/`--accent-soft` (color-mix) con persistencia en localStorage
  (el login adopta el acento de la instalación sin token). Panel
  «Apariencia — Color de acento de la instalación» en Usuarios y permisos:
  paleta de 8 presets + hex personalizado + vista previa, «Guardar acento»
  y «Restablecer azul». Marca, login, botón primario y franjas ahora usan
  `color-mix` sobre el acento activo. 7 evals backend + 1 vitest; corpus
  **565/12**, gates D-030 PASS (deuda 132 < baseline 133), portal 83
  vitest. En vivo contra el candidato (migración `0024`): default → PUT
  #0d9488 → 422 en inválido → persistido con `updated_by: admin`; por UI
  el swatch violeta retiñe todo el portal (screenshots).

## [Pulido visual del portal — 2026-08-17]

- **T-060 (P2 Portal, VERIFIED):** mejora estética integral solo en CSS
  (`src/styles.css`), sin cambios de comportamiento. Accesibilidad:
  `:focus-visible` con anillo de acento, `::selection` con acento y
  `prefers-reduced-motion` que desactiva animaciones. Números tabulares en
  métricas/contadores/tablas y scrollbars finos. Sidebar: resplandor
  radial, item activo con gradiente de acento + barra lateral e icono
  iluminado, hover con desplazamiento y marca con brillo pulsante. KPIs:
  tinte por tarjeta (azul/verde/violeta/ámbar/rosa con variantes dark),
  chips de icono teñidos, línea de gradiente y elevación al hover.
  Paneles, botones (primario con gradiente), tablas (fila hover),
  alertas (franja lateral de severidad), tarjetas de recurso y login
  (franja de gradiente) con micro-interacciones; estado de carga con pulso
  suave y entrada en escena escalonada. Portal **82 vitest passed** y
  `vite build` OK; verificado en preview en modo claro y oscuro
  (screenshots).

## [Panel de supervisión de agentes por módulo — 2026-08-17]

- **T-059 (P2 Agentes IA, VERIFIED):** endpoint `GET /agents/supervision`
  (READ_ROLES, alias `/api/bridge/agents/supervision`) que agrega la
  auditoría `tool_call` de la instalación por agente (integrado o
  persistido): módulo, allowlist efectiva, estado por tool (kind,
  authorized, calls/✓/✗/!, `last_status` = llamada más reciente por
  timestamp), `summary` y `recent_actions` (últimas 5); un agente sin
  actividad aparece ocioso (calls=0). Portal: panel «Supervisión por
  módulo» (eyebrow Control empresarial) en la sección Agentes de IA —
  tarjeta por agente con badge de módulo, tier, última actividad, pills y
  tablas desplegables «Estado de las tools» y «Últimas actuaciones
  auditadas» (chips success/denied/error). 4 evals backend + 1 vitest;
  corpus **559/12**, gates D-030 PASS (deuda 131 < baseline 133), portal
  82 vitest. En vivo contra el candidato: rebuild del bridge-api — pin
  `libpq` del Dockerfile actualizado a `18.6-r0` (la versión 18.4 dejó de
  existir en el repo Alpine 3.24) y build con `--env-file
  .env.candidate-0815` — y 3 invocaciones reales por
  `POST /agents/tools/invoke` (crm `list_leads` success, social
  `get_social_stats` success, crm `confirm_quote` denied) → totals
  3/2/1/0; el panel del preview muestra la actividad real y la denegación
  auditada (screenshot).

## [Agentes de IA por módulo — Fase 2: propuestas con aprobación — 2026-08-17]

- **T-058 (P2 Agentes IA, VERIFIED):** los agentes especializados de la
  T-057 pasan de solo leer a **proponer** acciones con aprobación humana.
  `services/agent_proposals.py` (determinista, sin LLM/red): `crm_agent`
  propone `agent_proposal:create_follow_up` (actividad con SLA 4 h para
  mensajes sociales urgentes — queja o lead con urgency ≥ 40 — cuyo
  seguimiento falta o está vencido) y `social_agent` propone
  `agent_proposal:dismiss_message` (spam con score 0 aún en el inbox).
  Cada propuesta es un `ApprovalRequest` del flujo existente con
  `action_type agent_proposal:*` y `requested_by` = id del agente;
  unicidad por action+target, el rechazo re-propone si la señal sigue y el
  efecto viaja en la misma transacción del approve (actividad idempotente
  por `created_by=agent:<id>`+título, o `dismissed`) con auditoría.
  Endpoint `POST /approvals/agent-round` (RBAC operador+, `agent_proposals.run`
  auditado). Portal: botón «Ejecutar agentes» en el panel de aprobaciones
  (solo admin) y labels de propuesta de agente en el feed. 8 evals backend
  + 1 vitest; corpus **555/12**, gates D-030 PASS (deuda 131 < baseline
  133), portal 81 vitest; E2E en vivo contra el candidato con propuestas
  reales y approve aplicando el efecto.

## [Agentes de IA especializados por módulo — Fase 1 — 2026-08-17]

- **T-057 (P2 Agentes IA, VERIFIED):** directriz del cliente — «toda la app
  debe estar gestionada por agentes de IA especializados por módulo».
  Arquitectura en `docs/AGENTES_POR_MODULO.md` (mapa módulo→agente, tiers
  de autonomía L0-L3, Fase 2 con aprobación humana, supervisor). Catálogo
  built-in en `AGENT_REGISTRY`: `catalog_agent` (Catálogo), `crm_agent`
  (Clientes/CRM), `social_agent` (Escucha social), `marketing_agent` (Email
  y campañas), `content_agent` (Contenido/SEO) + `sales_agent`/`rag_agent`
  existentes; cada uno con `module`, `module_label`, `scope`, persona, tier
  y solo las herramientas de su dominio. 7 herramientas read-only
  deterministas sin mutación en `DeterministicToolsService` y declaradas en
  `TOOL_SPECS` (kind `read`): `list_leads`, `list_activities`,
  `get_pipeline_report`, `list_social_inbox`, `get_social_stats`,
  `list_campaigns`, `get_campaign_stats`. Deny-by-default intacto: ninguna
  allowlist autoriza herramientas financieras/contables; el
  `AgentConfigSchema` sigue con `extra=forbid`; cada invocación se audita
  (`tool_call` success/denied/error). Portal: badge de módulo + alcance en
  la tarjeta del agente. 8 evals backend + 1 vitest; corpus **547/12**, gates
  D-030 PASS, portal 80 vitest.

## [Agente de escucha social — Fase 1 — 2026-08-17]

- **T-056 (P2 CRM, VERIFIED):** adaptadores puros por canal en
  `services/social_adapters.py` (genérico JSON+HMAC y WhatsApp Business
  Cloud API con challenge por GET y firma `X-Hub-Signature-256`; canal
  desconocido fail-closed); modelos `SocialChannel`/`SocialMessage`/
  `SocialTriage` con migración `0023` idempotente (dedupe por
  `source_message_id`); triaje determinista sin red/LLM en
  `services/social_triage.py` (intención, idioma, registro, sentimiento,
  urgencia, entidades y `score_social` explicado); webhook público
  `POST /social/webhook/{id}` que verifica HMAC (401 fail-closed), deduplica
  reintentos (200 duplicate) y encola la triaje en el outbox durable
  (`social.triage` → dispatcher que crea/actualiza el lead con
  `source=social` por email→teléfono→handle, actividad follow-up con SLA
  por canal — WhatsApp 30 min, queja 15 min —, timeline y evento saliente
  `social.message_triaged` en el catálogo de webhooks); CRUD de canales
  solo admin (idempotente, secreto nunca expuesto; borrado con mensajes →
  desactivación), inbox/dismiss/stats operador+; `_lead_score` fusiona la
  señal `social` (hasta 20 pts). Portal: tab «Escucha social» en Clientes
  (`src/social.tsx`). 14 evals backend + 4 vitest; corpus **539/12**, gates
  D-030 PASS, portal 79 vitest; validación en vivo contra el candidato
  (migración `0023`): webhook WhatsApp simulado firmado → triaje
  queja/es/urgente 64/score 60 → lead «Carlos Ruiz» + actividad SLA 15 min
  + timeline + stats; 401 con firma inválida; reintento → duplicate; canal
  desactivado; preview del tab (screenshot).

## [Propuesta de arquitectura — Agente de escucha social — 2026-08-17]

- Nuevo documento de diseño: `docs/SOCIAL_LISTENING_AGENT.md` (propuesta, sin
  implementar) para el módulo de escucha social (Instagram, WhatsApp, Facebook,
  LinkedIn, X) recogido en sesión: conectores por canal con hechos reales de
  2026 (WhatsApp Cloud API con inbound gratis, Meta con revisión de app, X sin
  free tier — pago por uso —, LinkedIn con DMs de página restringidos),
  arquitectura webhook → outbox durable → triaje (determinista primero, LLM
  opcional con guardrails) → upsert de lead + actividad + timeline + cola
  priorizada del kanban, modelo de datos propuesto (migración `0023_social`),
  seguridad/gobierno (HMAC, DLP, RBAC, RGPD), definición de «hecho» con plan
  de tests herméticos, hoja de ruta en 3 fases y gancho de venta por segmento.
  Reutiliza los patrones existentes (verify_hmac_signature, outbox,
  idempotencia, `_lead_score`, actividades, spool, webhooks salientes).

## [Manual de recorrido en PDF — 2026-08-17]

- Nuevo artefacto de producto: `docs/MANUAL_RECORRIDO_APP.pdf` (9 páginas,
  portada + índice con números de página) generado por
  `scripts/generate_manual_pdf.py` (reportlab). Contiene: resumen ejecutivo
  con métricas actuales (corpus 548/12, catálogo 41.652 SKUs, RBAC 63/63,
  RPO/RTO), acceso y roles, recorrido módulo a módulo de todo lo que la app
  hace hoy, tabla de **porcentaje de finalización** (M0+M1 100 %, P2 86 %,
  P3 0 %, plan global 82 %), módulos actuales vs módulos futuros (incluye la
  idea de agente de escucha social para Instagram/WhatsApp/Facebook/LinkedIn/X),
  recorrido de negocio del ciclo de venta completo y pitch comercial
  (segmentos, precios Starter/Pro/Enterprise, diferenciadores con evidencia y
  regla de venta honesta). Se verificó el render real página a página
  (acentos correctos, tablas y TOC bien formados).

## [Datos maestros CRM (T-054, P2) — 2026-08-17]

- **Modelos**: `Account` (razón social, NIF, sector, web, nota, score) y
  `Contact` (nombre, cargo, email, teléfono, cuenta FK, principal, merge) con
  migración `0021` idempotente y downgrade no destructivo; `Lead` gana
  `account_id`/`contact_id`/`merged_into` (los leads merged se excluyen de la
  lista y del board); `Opportunity` gana `probability` (heredada de la etapa),
  `lost_reason` y `won_at`/`lost_at`; `PipelineStage` gana `probability`
  editable por admin.
- **Endpoints auditados con RBAC**: CRUD de cuentas (`GET/POST/PATCH
  /accounts`), `GET/POST /contacts`, `POST /contacts/{id}/merge`, `POST
  /leads/{id}/merge` (mueve oportunidades, actividades y custom values del
  absorbido al principal, audita el merge), `PATCH /pipeline/stages/{id}`
  (probabilidad), `POST /opportunities/{id}/close` (won/lost con motivo
  obligatorio en lost; timestamps; cierra las actividades pendientes del lead;
  dispara el webhook `opportunity.closed`).
- **Reporte de ventas extendido** (`/pipeline/report`): `lost_reasons`
  (contador por motivo), `weighted_pipeline_value` (Σ valor × probabilidad de
  abiertas) y `probability` por etapa — el forecast ahora pondera de verdad.
- **Portal**: tab «Cuentas» en Clientes (`src/accounts.tsx`) con listado y
  ficha (contactos de la cuenta), modal de cierre de oportunidad (won/lost con
  motivo) y badge de probabilidad en las tarjetas del kanban.
- **Validación en vivo contra el candidato** (PostgreSQL real, migración
  `0021` aplicada): cuenta + contacto principal, cierre lost con motivo
  (webhook encolado), merge de leads con exclusión del perdedor, reporte con
  `lost_reasons`/`weighted_pipeline_value`/`probability`, preview del tab
  Cuentas (screenshot). Corpus **541 passed/12 skipped**, gates D-030 PASS,
  portal tsc + build + **72 vitest**.

## [Calendario de comercial (T-053, P2) — 2026-08-16]

- **Backend**: endpoint `GET /calendar/agenda` (RBAC operador+) que devuelve
  la agenda de actividades en un rango de días locales inclusivos
  (`start`/`end` `YYYY-MM-DD`, `tz_offset` en minutos, máximo 92 días):
  **todos** los días del rango con counts (total, pending, completed,
  cancelled, overdue) y sus actividades, más `totals`. El agrupado usa el
  offset del cliente para que el día local coincida con su calendario;
  `overdue` cuenta las pendientes con `due_at` local ya pasado; las
  actividades sin `due_at` quedan fuera. Filtros `assigned_to`/`kind`/
  `status`. Validaciones: 422 para fecha mal formada, rango invertido y
  rango >92 días.
- **Portal**: nuevo tab «Calendario» en Clientes (`src/calendar.tsx`) con
  vistas **Mes** (rejilla L–D con badges ⚠ vencidas / pendientes / ✓ hechas
  por día y click que abre el día), **Semana** (7 columnas con la lista
  compacta) y **Día** (lista completa con tipo, hora, lead y estado),
  navegación ◀/Hoy/▶, pills de totales y `tz_offset` del navegador.
  `KIND_LABELS`/`STATUS_LABELS` exportados desde `activities.tsx`.
- **Calidad**: 5 evals backend herméticos nuevos (agrupación + counts, días
  vacíos, overdue + filtros, `tz_offset` desplaza el día local, exclusión de
  sin fecha/fuera de rango, RBAC + validaciones) y 5 vitest nuevos. De paso
  se corrigieron dos hallazgos de ruff (B904 `raise … from None` y DTZ011
  fecha UTC en tests) para mantener el ratchet en baseline.

## [Email integrado (T-052, P2) — 2026-08-16]

- **Backend**: modelos `EmailTemplate`, `EmailSettings` y `EmailTrackingEvent`
  (migración `0020` idempotente, downgrade no destructivo). CRUD auditado con
  RBAC: `GET /email/templates` (lectura + catálogo de variables), `POST /
  email/templates` (solo admin, idempotente con `Idempotency-Key`, nombre
  único), `PATCH/DELETE /email/templates/{id}` (solo admin) y
  `GET/PUT /email/settings` (firma por instalación y tracking; solo admin
  para mutar).
- **Plantillas y firma**: `send_templated_email` renderiza asunto/cuerpo con
  variables del catálogo (`{{store_name}}`, `{{lead.first_name}}`,
  `{{quote.id}}`…), añade la firma (de plantilla o de instalación) y envía
  por el pipeline existente (`automations.send_email` → SMTP o spool local
  con degradación auditada). `POST /email/templates/{id}/send-test` envía
  una prueba con variables de ejemplo.
- **Tracking de apertura y clics**: con `EMAIL_TRACKING_BASE_URL`
  configurado, el envío registra el evento `sent` (token aleatorio →
  destinatario/plantilla), inserta el pixel PNG 1x1 y reescribe los enlaces
  http/https a `{base}/email-tracking/{token}/click?u=…`. Los endpoints
  públicos `GET /email-tracking/{token}/open.png` (PNG 1x1 válido) y
  `/click` (302 al destino) registran `open`/`click` de forma idempotente
  (una apertura por token; las recargas no duplican). Sin base URL no se
  emiten URLs rotas: se omite y se audita `email.tracking_skipped`.
  Plantilla inexistente → fallo cerrado `email.template_not_found`.
- **Proveedores**: `LocalEmailProvider`/`SmtpEmailProvider` aceptan `html`
  (SMTP lo envía como alternativa multipart) y `tracking_token` (persistido
  en el spool), sin romper llamadas existentes.
- **Portal**: sección «Email integrado» (solo admin) con CRUD de plantillas,
  «Enviar prueba», firma de instalación, toggle de tracking y tabla de
  eventos de tracking (sent/open/click con badges).
- **Pruebas**: 9 evals backend herméticos nuevos
  (`tests/regression/test_p1_email_templates.py`) — CRUD+RBAC+validación,
  settings, envío con spool y tracking (pixel + clics + firma), sin base URL
  omite tracking, plantilla inexistente honesta, open idempotente con PNG
  válido, click 302 + idempotente, endpoints públicos y RBAC de eventos — y
  5 evals vitest (`src/email.test.tsx`). Corpus backend **531 passed/11
  skipped**; portal **63 vitest**; quality gates D-030 PASS.
- **Validación en vivo contra el candidato** (PostgreSQL real, migración
  `0020` aplicada): settings con firma «Un saludo, Equipo BTOP Digital»;
  plantilla creada; `send-test` → spool con asunto renderizado (variables +
  tienda), pixel `open.png` y clics reescritos + firma; `open.png` → 200
  image/png (67 bytes, magic PNG); `/click` → 302 a
  `https://example.com/presupuesto/QT-DEMO`; eventos en BD `sent → open →
  click` con destinatario y plantilla (segundo open sin duplicar); preview
  con la sección renderizando plantillas y eventos reales (screenshot).

## [Webhooks salientes de eventos CRM (T-051, P2-f) — 2026-08-16]

- **Backend**: modelo `WebhookSubscription` (migración `0019` idempotente,
  downgrade no destructivo) con URL, secreto HMAC por suscripción, eventos
  suscritos (catálogo estable `WEBHOOK_EVENT_CATALOG`: `lead.created`,
  `lead.assigned`, `pipeline.stage_changed`, `quote.confirmed`) e
  `is_active`. CRUD auditado con RBAC: `GET /webhooks/subscriptions`
  (lectura, secreto oculto — solo `secret_set`/`secret_prefix`),
  `POST/PATCH/DELETE` solo admin (alta idempotente con `Idempotency-Key`;
  `secret` vacío en PATCH conserva el existente) y
  `POST /webhooks/subscriptions/{id}/test` que encola `webhook.test` por el
  outbox durable sin tocar red en el request.
- **Anti-SSRF en dos capas**: validación barata en CRUD (esquema, host,
  literales RFC1918/loopback sin DNS) y defensa completa en el dispatcher
  (`_assert_outbound_url_allowed` con resolución DNS): un destino bloqueado
  o no resoluble cae a dead-letter permanente auditada, nunca se reintenta
  ni finge éxito.
- **Transactional outbox**: `OutboxService.enqueue(commit=False)` permite
  que el mensaje viaje en la MISMA transacción que la mutación que produce
  el evento — un fallo de la mutación descarta el mensaje con el rollback.
  Enganchado en `create_lead`, `assign_lead`, `move_opportunity_stage` y
  `confirm_quote_api`. El dispatcher `crm.webhook` firma el payload con
  HMAC-SHA256 y el secreto DE LA SUSCRIPCIÓN (cabeceras
  `X-Bridge-Webhook-Id/Signature/Key-Id=subscription/Timestamp`) y omite de
  forma auditable las suscripciones inactivas/eliminadas.
- **Portal**: sección «Webhooks salientes» (solo admin) con CRUD en tabla,
  activar/desactivar, «Probar» (test ping), formulario de alta con
  checkboxes de eventos y catálogo desplegable; segundo gate de secciones en
  `App.tsx` (`webhooks` solo admin) — sin él el hash `#webhooks` caía a
  resumen.
- **Compose**: `WEBHOOK_OUTBOUND_ALLOWED_HOSTS` expuesta en `environment:`
  de bridge-api (default vacío = política estricta).
- **Pruebas**: 12 evals backend herméticos nuevos
  (`tests/regression/test_p1_webhooks_outbound.py`) — CRUD+RBAC+secreto
  oculto, eventos desconocidos/URLs privadas 422, 428 sin key, duplicado
  409, test ping, enqueue atómico de los 4 eventos CRM, dispatcher con
  firma HMAC verificada sin red, skip inactiva/eliminada, SSRF permanente —
  y 5 evals vitest (`src/webhooks.test.tsx`). Corpus backend
  **522 passed/11 skipped**; portal **58 vitest**; quality gates D-030 PASS.
- **Validación en vivo contra el candidato** (PostgreSQL real, worker del
  outbox activo): suscripción creada y auditada, `lead.created` encolado en
  la misma transacción, test ping entregado por el worker a un listener
  local con **firma HMAC verificada byte a byte** (cuerpo canónico de 197
  caracteres, estado `sent`), y URL `public.test` → dead-letter con
  `webhook_dns_resolution_failed:public.test` auditada (`outbox_dead`).
  Preview con la sección renderizando las suscripciones reales.

## [Import/export CSV de leads (T-050, P2-e) — 2026-08-16]

- **Backend**: `GET /leads/export.csv` (RBAC operadores+) exporta los leads a
  CSV con columnas fijas (email, first_name, phone, company_name, source,
  status, assigned_to como username, created_at) + una columna por campo
  personalizado de lead activo (su ``key`` como cabecera; booleanos ``Sí``/
  ``No``, NULL celda vacía). Orden determinista por alta e id; cabecera
  ``Content-Disposition`` de descarga. `POST /leads/import` (upsert de lote
  con `Idempotency-Key`): valida emails por fila (los inválidos se reportan en
  ``errors`` sin abortar el lote), deduplica por email (``skipped_duplicates``,
  incluida la deduplicación intra-lote) y crea con ``source="import"``;
  ``dry_run`` informa sin crear ni exigir idempotencia. Evento auditado
  ``lead.import_completed`` con conteos.
- **Portal**: botón «Exportar CSV» en la sección Leads (descarga el blob con
  el nombre ``leads.csv``; deshabilitado sin leads).
- **Pruebas**: 5 evals backend herméticos nuevos (export con campos
  personalizados, import crea+deduplica+audita, dry_run sin efectos, 428 sin
  Idempotency-Key, viewer 403) y 1 eval vitest del botón de exportación.
  Corpus backend **510 passed/11 skipped**; portal **53 vitest**; quality
  gates D-030 PASS.

## [Campos personalizados (T-048, P1-c) y lead scoring (T-049, P1-d) — 2026-08-16]

- **Backend (P1-c)**: modelos `CustomFieldDefinition` y `CustomFieldValue`
  (migración `0018_custom_fields.py` idempotente, downgrade no destructivo).
  Definiciones por instalación con clave estable única, tipo
  (text/number/date/boolean/select con opciones), obligatoriedad, orden y
  visibilidad por rol (`all`/`operators`/`admins`); la desactivación
  (`is_active`) sustituye al borrado y conserva los valores. Endpoints
  auditados: `GET /custom-fields` (lista filtrada por visibilidad del rol),
  `POST /custom-fields` (solo admin, evento `custom_field.created`, clave
  duplicada → 409), `PATCH /custom-fields/{id}` (solo admin,
  `custom_field.updated`), `GET /custom-values` (definición+valor por entidad,
  filtrado por visibilidad) y `PUT /custom-values` (upsert idempotente con
  `Idempotency-Key`, valida tipo/opciones contra la definición → 422, campo
  no visible → 403, evento `custom_field.value_updated`).
- **Backend (P1-d)**: `GET /leads/{lead_id}/score` — puntuación determinista
  (0–100) y explicada por señales: origen (chat/web/import/local), antigüedad
  (más reciente = más puntos), oportunidades abiertas, valor abierto e
  histórico de ventas ganadas. Sin LLM ni red: misma entrada → misma salida.
  `GET /pipeline/board` ahora expone `score` y `score_signals` por lead y
  ordena la cola de leads sin asignar por puntuación descendente (desempate
  por antigüedad).
- **Portal**: quinta pestaña «Campos personalizados» en Clientes (solo admin,
  `src/customFields.tsx`): tabla de definiciones con edición inline
  (etiqueta/visibilidad/obligatorio), activar/desactivar y formulario de alta
  con opciones para `select`. La cola del kanban muestra la puntuación de cada
  lead en un badge (verde/ámbar/gris) con las señales en el tooltip. La ficha
  del lead (drawer) muestra y permite editar los valores de los campos
  visibles (`PUT /custom-values` con clave de idempotencia por guardado).
- **Pruebas**: 12 evals backend herméticos nuevos
  (`tests/regression/test_p1_custom_fields_scoring.py`: CRUD+RBAC, visibilidad
  por rol, validación de tipos y opciones, idempotencia del upsert, score
  determinista y orden de la cola) y 5 evals vitest del portal. Corpus
  backend 505 passed/11 skipped; portal 52 vitest; quality gates D-030 PASS.
- **Gobernanza**: `BLOCKERS.md` sincronizado con la evidencia de `STATUS.md`
  (B-007 RESOLVED por el ensayo SS-05; B-003/B-005/B-006/B-010 pasan a
  MITIGADO con su residual documentado). `scripts/quality_gates.py
  --update-baseline` ahora recalcula también el desglose `by_rule` (antes solo
  actualizaba el total y dejaba el desglose desincronizado); baseline ruff
  fijado en 133.

## [Actividades de comercial (T-047): tareas y recordatorios con email — 2026-08-16]

- **Backend**: modelo `Activity` (migración `0017_activities.py` idempotente,
  con downgrade no destructivo e índice `ix_activities_installation_id`) +
  CRUD auditado: `GET /activities` (filtros por estado/lead/oportunidad),
  `POST /activities` (valida lead/oportunidad existentes y que la oportunidad
  pertenezca al lead → 404/422), `PATCH /activities/{id}` (estado
  done/cancelled con `completed_at`/`completed_by`) y
  `POST /activities/{id}/remind` (envío inmediato). Todos RBAC operadores+,
  eventos `activity.created`, `activity.updated` y `activity.reminder_sent` en
  `audit_logs`.
- **Recordatorios automáticos**: `DurableActivityReminderWorker` (opt-in,
  `ACTIVITY_REMINDER_WORKER_ENABLED`, poll configurable) barre actividades
  `pending` con `remind_at <= now` y sin `reminded_at` (el propio `reminded_at`
  es la llave de idempotencia: se marca ANTES de enviar para que réplicas o
  crash entre marca y envío no dupliquen el recordatorio). Destinatario
  `remind_email` o el email del lead por defecto; sin destinatario resoluble
  audita `activity.reminder_skipped`. Envío por el pipeline existente
  (`automations.send_email`): proveedor configurado o spool local con
  degradación auditada — nunca pérdida silenciosa.
- **Compose**: `ACTIVITY_REMINDER_WORKER_ENABLED/POLL_SEC` expuestos en
  `docker-compose.yml` (default `false`, conservador).
- **Portal**: cuarto tab «Tareas» en la sección Clientes (`src/activities.tsx`):
  tabla con filtro por estado, acciones Recordar ahora / Completar / Cancelar,
  y formulario de nueva tarea con lead, fechas, email del recordatorio y
  comercial asignado.
- **Bug real encontrado en validación en vivo**: `_activity_response` hacía
  `None + str` al crear una tarea sin lead vinculado (500). Corregido con
  test de regresión hermético (`test_activity_create_without_lead_returns_none_names`).

## [Timeline de interacción (T-046): historial cronológico por lead — 2026-08-16]

- **Backend**: `GET /leads/{lead_id}/timeline` (RBAC operadores+, 404 si no
  existe) — proyección de fuentes ya auditadas/persistidas, sin duplicar
  estado: creación del lead (`local_lead_created` o el `created_at` del
  registro como fuente canónica si el alta no se auditó), asignación
  (`lead.assigned` con nombres de usuario), oportunidades (creación con
  valor, `pipeline.stage_changed` con nombres de etapa resueltos y notas de
  la oportunidad), ciclo de venta (`quote_created_api` y `quote_confirmed`
  correlacionados por el `external_reference` de la oportunidad = id del
  presupuesto) y emails (`automation.email_*` correlacionados por
  `recipient_sha256` = hash del email del lead; el asunto permanece hasheado
  por privacidad). Orden estrictamente cronológico descendente, máx 500
  entradas, cada una con `kind/title/detail/created_at/actor`.
- **Portal**: la ficha del lead (`src/timeline.tsx`) se abre desde las
  tarjetas del kanban (clic/Enter/Espacio) y desde un botón «Ficha» en la
  cola de leads sin asignar: drawer accesible (role=dialog, Esc cierra) con
  datos del lead + historial cronológico con marcadores por tipo (azul
  normal, ámbar degradado, rojo fallido, verde pedido).
- **Verificación**: 3 evals backend herméticos (fusión de eventos + orden +
  privacidad del asunto, correlación presupuesto/pedido, aislamiento por
  hash + RBAC/404) + 6 evals vitest (ficha con historial, sin leadId,
  vacío, Esc, error, clic en tarjeta abre la ficha). Validación en vivo
  contra el stack candidato con un lead real: creación → oportunidad → nota
  → email en cola (local_spool correlacionado por hash) → 4 cambios de
  etapa auditados, todo cronológico. Corpus **465 passed / 11 skipped**,
  gates PASS, portal tsc + build + **42 vitest**.

## [Reporting de ventas P1-b (T-045): funnel, ticket medio, win-rate y aging — 2026-08-16]

- **Backend** (primer módulo de la T-044 implementado): columna
  `opportunities.stage_changed_at` (migración `0016_stage_changed_at.py` con
  backfill a `created_at`, NOT NULL tras backfill vía `batch_alter_table`
  para SQLite; se inicializa en `create_opportunity` y se actualiza en el
  PATCH de etapa solo cuando la etapa cambia de verdad) y endpoint
  `GET /pipeline/report` (RBAC operadores+) que calcula sobre el board real:
  funnel por etapa (recuento, valor total, aging medio/máximo en días en la
  etapa actual), ticket medio y mediana, win-rate (won/(won+lost)), pipeline
  abierto (recuento y valor) y aging global. Clasificación terminal honesta:
  etapa `won`/`lost` o `status` homónimo; las oportunidades terminales salen
  del pipeline abierto aunque su `status` siga en `open`.
- **Portal**: tercer tab «Reporting de ventas» en la sección Clientes
  (`src/report.tsx`): 5 KPIs (ticket medio, mediana, win-rate con detalle
  ganadas/perdidas, pipeline abierto, aging) + funnel por etapa con barras
  proporcionales y aging en días o **horas** cuando es sub-diario (un aging
  de 0,38 días se muestra como «9 horas», no «0 días»).
- **Verificación**: 3 evals backend herméticos (funnel/ticket/win-rate/aging
  con valores conocidos, reset de aging al mover de etapa, RBAC viewer 403)
  + 4 evals vitest (KPIs, funnel, sub-diario en horas, error de API);
  validación en vivo contra el stack candidato (migración 0016 aplicada a su
  PostgreSQL, `stage_changed_at` NOT NULL): funnel 26 en «Nuevo» (1.124,60 €,
  aging 9 h máx 13 h), ticket medio 43,25 €, mediana 20,40 €, pipeline
  abierto 1.124,60 €, win-rate «—» (0/0, honesto). Corpus **462 passed / 11
  skipped**, gates PASS, portal tsc + build + **36 vitest**.

## [Tarea paraguas CRM completo (T-044) — 2026-08-16]

- Registrada en `TASKS.md` la tarea **T-044** que consolida el análisis del
  hueco CRM completo (2026-08-16): Bridge cubre el back-office comercial pero
  le falta el ~80 % de un CRM de ventas. Alcance priorizado en tres bloques:
  **P1 núcleo vendible (M1 = Pro)** — actividades de comercial con
  recordatorios por email, timeline de interacción, reporting (funnel, ticket
  medio, win-rate, aging, forecast ponderado), campos personalizados por
  instalación y lead scoring en la cola; **P2 crecimiento** — email integrado
  y campañas segmentadas (reusan SMTP/spool), calendario de comercial,
  import/export CSV, API pública + webhooks, SSO/OIDC + MFA; **P3
  enterprise** — tickets con SLA, equipos, multi-tenant RLS, billing, SCIM y
  BI. Incluye datos maestros (cuenta/contacto separados, merge de duplicados,
  probabilidad por etapa, motivos de pérdida) y las dependencias con T-042
  (plan) y T-043 (kanban P1-a, VERIFIED). Cada módulo respeta los invariantes
  del proyecto (auditoría, RBAC, hermetismo D-032, migraciones idempotentes)
  y la regla de venta honesta.

## [Kanban de pipeline P1-a (etapas configurables, drag&drop, cola de leads) — 2026-08-16]

- **Backend** (P1-a del plan CRM `docs/PRODUCT_PLAN_CRM_B2B.md`): nuevo
  modelo `PipelineStage` (etapas con `key` estable, `name` editable y
  `position` no única por diseño — la reconfiguración reordena con UPDATEs en
  lote) y columna `leads.assigned_to` (NULL = lead sin asignar, aparece en la
  cola del kanban). Migración `0015_pipeline_stages.py` (idempotente,
  downgrade no destructivo: la config se re-siembra y la asignación es dato
  de negocio que no se destruye).
- **Endpoints nuevos** (todos auditados): `GET/PUT /pipeline/stages`
  (siembra de las 6 etapas por defecto `new/qualified/quote/negotiation/won/lost`
  y reconfiguración solo admin con reasignación de huérfanos a la primera
  etapa), `GET /pipeline/board` (oportunidades agrupadas por etapa + cola de
  leads sin asignar + usuarios disponibles para asignar, sin exponer hashes),
  `PATCH /opportunities/{id}` (cambio de etapa por drag&drop, valida la
  etapa contra el pipeline, audita `pipeline.stage_changed`) y
  `PATCH /leads/{id}/assign` (asignación/desasignación a un comercial,
  audita `lead.assigned`). RBAC: operadores leen y mueven; solo admin
  reconfigura etapas.
- **Portal**: la sección Clientes gana el toggle «Leads y oportunidades /
  Pipeline (kanban)». El kanban (`portal/src/kanban.tsx`) usa drag&drop
  HTML5 nativo (sin librerías), columnas con contador, tarjetas con cliente y
  valor, cola de leads sin asignar con desplegable de asignación, y editor de
  etapas solo admin (renombrar, reordenar ↑/↓, añadir, eliminar, guardar
  vía PUT auditado). Estilos en `styles.css`.
- **Verificación**: 9 evals backend herméticos
  (`test_p1_pipeline_kanban.py`) + 5 evals frontend vitest
  (`kanban.test.tsx`); validación en vivo contra el stack candidato
  (`agent-candidate-0815`, 41.652 SKUs): board con 6 etapas y 26
  oportunidades, asignación del lead E2E al comercial (cola 27→26, evento
  `lead.assigned` en `audit_logs`) y cambio de etapa `new→won→new` con dos
  eventos `pipeline.stage_changed`. Corpus **459 passed / 11 skipped**;
  gates D-030 PASS; portal tsc + build + 32 vitest OK.

## [Plan de producto: Bridge como CRM B2B por instancia gestionada (2026-08-16)]

- Nuevo documento `docs/PRODUCT_PLAN_CRM_B2B.md` que reposiciona Bridge de
  «operaciones de comercio B2B» a **CRM B2B de ventas + back-office comercial**
  por instancia gestionada: la tesis es que el pipeline se alimenta del ciclo
  de venta real (cada presupuesto del chat es una oportunidad), no de tecleo
  manual.
- **Módulos a añadir** en tres bloques sobre el inventario real
  (`docs/BUSINESS_MODULES.md`): P1 núcleo comercial (kanban configurable,
  actividades de comercial, reporting de ventas, asignación, lead scoring),
  P2 crecimiento (SSO/MFA, campañas segmentadas, API pública + webhooks,
  calendario, import/export CRM) y P3 enterprise (multi-tenant con RLS,
  billing, SCIM, BI, integración ERP/fiscal certificada) — cada módulo indica
  qué código existente reutiliza y su esfuerzo relativo.
- **Precios por segmento**: mantiene los rangos del pitch (Starter €149,
  Pro €499, Enterprise €1.900/mes + setup) y los estructura como planes CRM
  con qué incluye cada tier y el encuadre por segmento.
- **Hoja de ruta M0→M3** desde el estado actual con criterios de salida
  medibles (M1 = v1.0 vendible como Pro; M3 = multi-tenant con la matriz de
  aislamiento existente como red de seguridad) y la regla de venta honesta
  (nunca prometer SBOM/SLA/fiscal/SaaS compartido como estado actual).
- Fila T-042 en `TASKS.md`; evidencia en `docs/PRODUCT_PLAN_CRM_B2B.md`.

## [Gate de regresión LLM-as-judge en quality gates (2026-08-16)]

- **Nuevo gate `llm-judge`** (opt-in, `--with-judge`) en
  `scripts/quality_gates.py`: acción de regresión del evaluador de
  naturalidad. Se dispara SOLO cuando cambian los archivos de prompt/chat
  (`git status --porcelain` sobre `agent_ai.py`, `main.py`,
  `validate_chat_live.py`, `llm_judge_naturalness.py` y sus tests;
  `--force-judge` fuerza la ejecución) y **falla el pipeline si la media
  global del juez baja de 4.0** (`--judge-threshold`) sobre la evidencia
  de validación en vivo más reciente.
- **Degradación fail-open auditada** (coherente con D-032): sin cambios en
  prompt/chat, sin evidencia en `logs/rehearsal/` o sin juez alcanzable
  (probe de 3 s) el gate hace **SKIP** — la infraestructura ausente nunca
  tumba el pipeline; cuando corre, el umbral se aplica de verdad.
- **Juez de referencia por defecto: qwen3-14b en LM Studio local**
  (recomendado en T-039 por notas más consistentes; el 8b deja el baseline
  por debajo del umbral por diseño). Configurable con `--judge-spec`,
  `--judge-base-url` o `QUALITY_GATE_JUDGE_SPEC`/`QUALITY_GATE_JUDGE_BASE_URL`;
  `--judge-runs` sube la self-consistency (por defecto 1 pasada para
  velocidad).
- **Ejecución real**: `quality_gates.py --with-judge --force-judge` →
  `llm-judge PASS` con media global **4.3 ≥ 4.0** (qwen3-14b, 11 respuestas
  de la validación en vivo) y artefacto auditable
  `logs/rehearsal/quality_gate_judge_20260816T110137Z.json`. El criterio
  del evaluador incluye además un mínimo de 2 por dimensión (habría
  detectado la repetición de saludo como mín-1); el gate aplica por defecto
  la regla de media < 4 y muestra los mínimos en el detalle.
- **Verificación**: 6 evals herméticos nuevos (skip sin cambios/sin
  evidencia/juez caído/sin puntuaciones + PASS sobre umbral + FAIL bajo
  umbral, con módulo juez falso sin red) → corpus **450 passed / 11
  skipped / 0 errores**; gates D-030 PASS.

## [Corrección determinista de la repetición de saludo + revalidación con el juez (2026-08-16)]

- **Hallazgo principal de la evaluación LLM-as-judge corregido de forma
  determinista**: deepseek-r1:8b abría cada respuesta con la plantilla
  `¡Hola! Soy <asistente> de <tienda>.` aunque la conversación ya tuviera
  historial. El prompt lo prohibía, pero el modelo lo ignoraba; ahora el
  post-filtro `_strip_greeting_repeat` (en `agent_ai.py`) lo **garantiza**:
  con historial y turno no-saludo se elimina cualquier prefijo de
  saludo/presentación (español/inglés, incluida la pregunta de ofrecimiento
  `¿en qué puedo ayudarte?`); si la respuesta era solo el saludo repetido,
  se cae al fallback extractivo honesto. Espejo determinista
  `_ensure_greeting_persona`: en el primer saludo se garantiza la
  presentación con el nombre del asistente/tienda (el 8b a veces la omite).
- **Historial previo separado del mensaje actual**: el webhook persiste el
  mensaje del cliente antes de generar la respuesta, así que el historial
  cargado incluía el mensaje en curso; las garantías de persona ahora se
  deciden con el historial ANTERIOR a él (primera vuelta en vivo: el espejo
  nunca disparaba).
- **Refuerzo del prompt**: la directiva determinista de idioma/registro
  (`_detect_language_register`) se anexa también al final del prompt de
  usuario (los modelos pequeños siguen mejor la última instrucción) y la
  regla 4 prohíbe explícitamente saludar/presentarse cuando hay historial.
- **Validación en vivo** (Ollama, stack `agent-candidate-0815`):
  `scripts/validate_chat_live.py` PASS **11/11**; follow-ups de memoria y
  persona arrancan directo al contenido («En relación a tu pregunta sobre
  productos con llavero…») y el saludo inicial se presenta («¡Hola! Soy
  Carmen de BTOP Digital…»); heurísticas ampliadas (registro formal
  estructural, `llaver*`, «le interesaría»).
- **Revalidación LLM-as-judge sobre la nueva evidencia**: deepseek-r1:8b
  media 3.17 → **3.30** y qwen3-14b (LM Studio) media 4.12 → **4.28**;
  ambos confirman la corrección: el follow-up que antes rompía coherencia
  (repetición de saludo) pasa de coherencia **1 → 4 (8b) y 1 → 5 (qwen)**.
  El veredicto global sigue FAIL por hallazgos residuales distintos: la
  respuesta del primer turno de memoria afirma disponibilidad («están en
  venta») con stock 0 (honestidad 2, señal real) y ruido del juez en el
  saludo de persona (un saludo puro puntuado como si buscara producto).
- **Verificación**: 9 evals nuevos (strip con variantes, espejo persona,
  integración con historial, primer saludo vía webhook) → corpus
  **444 passed / 11 skipped / 0 errores**; quality gates D-030 PASS.

## [Juez provider-agnóstico + comparación entre modelos (2026-08-16)]

- **El juez de naturalidad ya no está atado a deepseek-r1:8b**: capa de
  proveedores en `scripts/llm_judge_naturalness.py` con la **misma
  superficie de configuración del producto** (`OPENAI_BASE_URL`/`API_KEY`,
  `ANTHROPIC_BASE_URL`/`API_KEY`) y temperatura 0 uniforme:
  - `ollama` (por defecto, deepseek-r1:8b), `openai_compatible` (OpenAI o
    local vía LM Studio/vLLM con `--base-url`/`--api-key`/`--provider`/
    `--model`) y `anthropic`. La rúbrica es idéntica para cualquier
    proveedor.
- **Modo `--compare A B`**: ejecuta dos jueces sobre la misma evidencia y
  produce veredictos y medias por dimensión lado a lado, el delta medio por
  dimensión y el acuerdo global (todas las dimensiones |Δ|≤1).
- **Comparación real** (11 respuestas, evidencia compartida):
  - deepseek-r1:8b: media **3.38** (fluidez 3.55, coherencia 3.27, persona
    2.78, honestidad 3.89) → FAIL.
  - qwen3-14b (LM Studio local): media **4.12** (fluidez 4.36, coherencia
    3.64, persona 4.33, honestidad 4.22) → FAIL (mínimo coherencia 1).
  - **Ambos confirman el hallazgo central**: la repetición del saludo de
    deepseek-r1:8b en follow-ups (qwen puntúa coherencia 1 en memoria y
    persona). El 8b como juez es severo de más en persona (Δ1.55) y algo en
    honestidad (Δ0.91); acuerdo global 3/11.
- **Bug corregido en el camino**: `resolve_provider` aplicaba `--base-url`
  (el de otro proveedor) también al juez ollama; el juez ollama usa siempre
  su servidor local.
- **2 evals nuevos** (resolución de proveedor con defaults del producto y
  transporte `openai_compatible` con system=RUBRIC y temperatura 0). Corpus
  **430 passed / 11 skipped / 0 errores**; quality gates D-030 PASS.

## [Evaluación LLM-as-judge de naturalidad (2026-08-16)]

- **`scripts/llm_judge_naturalness.py`**: evalúa automáticamente la
  naturalidad de las respuestas reales del chat guardadas en
  `logs/rehearsal/chat_live_validation_*.json`. Puntúa cada respuesta con
  un juez LLM (Ollama + deepseek-r1:8b, temperatura 0) según una rúbrica
  fija: **fluidez, coherencia, persona, honestidad** (1-5) + nota.
- **Robustez del juez**: rúbrica corta (el 8b se pierde con prompts largos),
  `format=json` de Ollama con parseo robusto (fences, razonamiento previo,
  wrapper `{"json": …}`), reintento ante drift/parseo fallido y
  **self-consistency** (`--judge-runs N`, por defecto 3 pasadas promediadas)
  porque el juez pequeño es ruidoso entre ejecuciones.
- **Honestidad anclada a la BD real**: `factcheck()` verifica en el catálogo
  real los `SKU=NNNN` citados por cada respuesta; si un SKU no existe,
  `honestidad=1` con nota (overlay determinista autoritativo, independiente
  del juez). Las respuestas deterministas (abstain, cierre de compra) se
  excluyen de persona/honestidad: su honestidad ya está garantizada por
  código y verificada por `skus_existentes`.
- **Contexto por conversación**: se reconstruye el hilo previo (2 turnos de
  memoria) para que `coherencia` evalúe continuidad real.
- **Ejecución real sobre la evidencia (11 respuestas, 3 pasadas)**: media
  global **3.17** (fluidez 3.18, coherencia 3.27, persona 2.67, honestidad
  3.56) → **verdict FAIL honesto**: hallazgo recurrente de que deepseek-r1:8b
  repite el saludo en follow-ups (coherencia 1) y afirma disponibilidad con
  stock 0; **todos los SKUs citados existen** (sin invención).
- **11 evals herméticos** (`tests/regression/test_p1_llm_judge.py`): parseo
  robusto, prompt con persona/historial, agregación con exclusiones,
  umbrales del veredicto, overlay de honestidad y extracción de SKUs.
  Corpus **428 passed / 11 skipped / 0 errores**; quality gates D-030 PASS.

## [Cierre de venta con factura por email + adaptación de idioma/registro (2026-08-15)]

- **El cierre de compra del chat es ahora una venta real**: al responder
  `CONFIRMAR <token>` se crea el pedido y, además, se envía la factura al
  cliente por email. `send_email` ahora admite adjuntos: el spool local los
  conserva en base64 y el proveedor SMTP los adjunta al mensaje
  (`SmtpEmailProvider.send` con `add_attachment`).
- **`send_invoice_email`** (nuevo helper): compone el asunto "Tu factura
  <nº> de <tienda>" (tienda de la persona por cliente), el cuerpo y el PDF
  determinista de `generate_invoice_pdf` como adjunto
  (`factura-<nº>.pdf`). Usa `send_email` → SMTP real o spool local con
  degradación auditada; la venta nunca se rompe por el correo.
- **Webhook CONFIRMAR**: tras `confirm_quote_transactional`, si el pedido es
  nuevo y existe factura, envía el email al email real del cliente (si el
  email es placeholder `@invalid.local` lo audita como
  `automation.invoice_email_skipped` y el chat pide el correo). El reply
  informa: "¡Pedido confirmado! … Tu factura <nº> está lista. La factura se
  ha enviado por email.". El resultado del webhook incluye `invoice_email`.
- **Adaptación de idioma y registro**: `_detect_language_register` detecta
  por tokens el idioma (español/inglés) y el registro (formal/tuteo) del
  cliente y anexa una directiva explícita al prompt de sistema (funciona con
  cualquier modelo, no depende de que el LLM infiera). Se eliminó la plantilla
  de saludo en español del prompt (anclaba a deepseek-r1:8b a responder en
  español) y el saludo extractivo también se adapta al inglés.
- **Driver de validación en vivo ampliado**: `scripts/validate_chat_live.py`
  añade escenas `formal` (usted, sin tuteo), `ingles` (prosa en inglés,
  nombres de producto reales intactos) y `tuteo` (registro cercano), más la
  verificación `skus_existentes` (todo `SKU=NNNN` citado por el LLM debe
  existir en el catálogo real). Nuevo `scripts/validate_sale_live.py` que
  recorre compra → CONFIRMAR → pedido + factura + email (spool) y verifica en
  PostgreSQL.
- **Validación en vivo contra el candidato**: chat PASS 11/11 turnos
  (saludo, búsqueda, comparación, ausente, memoria ×2, persona ×2, formal,
  inglés, tuteo) y cierre de venta PASS 15/15 checks (pedido `confirmed`,
  factura, aprobación pendiente, reserva local, spool con PDF `%PDF`).
- **11 evals nuevos** (2 adjuntos/spool + 1 `send_invoice_email` en
  `test_p1_automations.py`; 2 de cierre en `test_p0_commerce_authority.py`;
  1 de cierre en `test_p1_local_providers.py`; 5 de idioma/registro en
  `test_p1_agent_ai.py`). Corpus **417 passed / 11 skipped / 0 errores**;
  quality gates D-030 PASS.

## [Persona por cliente + validación en vivo del chat con Ollama (2026-08-15)]

- **Persona por cliente completa**: nueva setting `COMMERCE_STORE_NAME`
  (nombre de la tienda) junto a `COMMERCE_ASSISTANT_NAME` (nombre del
  asistente). El prompt de sistema construye la identidad (`Eres Carmen de
  BTOP Digital…`), pide presentarse por nombre y tienda en el primer saludo
  (sin repetir la presentación en cada mensaje) y cierra la compra ofreciendo
  `presupuesto de <tienda>`. Si la tienda ya está contenida en el nombre del
  asistente, no se duplica (`_commerce_persona`).
- **El cierre de compra determinista menciona la tienda**: la respuesta de
  creación de presupuesto del webhook ahora dice `Presupuesto
  <quote_id> de <tienda>: …` (antes no mencionaba ninguna tienda).
- **Las variables llegan al contenedor**: `COMMERCE_ASSISTANT_NAME` y
  `COMMERCE_STORE_NAME` se añaden al `environment` de `bridge-api` en
  `docker-compose.yml` con sus defaults, configurables por despliegue.
- **Validación en vivo contra el stack candidato** (`agent-candidate-0815`,
  Ollama + deepseek-r1:8b, catálogo real de 41.652 SKUs): driver
  `scripts/validate_chat_live.py` que recorre el webhook real de Chatwoot
  (HMAC firmado) con escenarios de saludo, búsqueda, comparación, categoría
  ausente, memoria (2 turnos) y persona (saludo + cierre). Veredicto **PASS**
  (8/8 turnos HTTP 200, persistencia de memoria verificada en PostgreSQL) con
  heurísticas deterministas de naturalidad; evidencia en
  `logs/rehearsal/chat_live_validation_*.json`.
- **Hallazgo corregido por la validación**: el LLM llegó a inventar un
  producto fuera del bloque real (alucinación). Se añadió
  `_enforce_verified_product_output` que reformatea las filas del bloque
  (nunca `SKU=` crudo) y devuelve la respuesta en prosa; además el saludo
  auditó el proveedor LLM real.
- **6 evals nuevos** (5 de persona en `test_p1_agent_ai.py` + 1 de cierre con
  tienda en `test_p0_commerce_authority.py`). Corpus **408 passed / 11
  skipped / 0 errores**; quality gates D-030 PASS.

## [Memoria de conversación en el chat comercial (2026-08-15)]

- **Nuevo modelo `ConversationMessage`** (migración alembic `0014`,
  idempotente) con `installation_id` + `account_id` + `conversation_id` +
  `role` (`client`/`assistant`) + `content` + `sequence`, índices por
  conversación y de búsqueda, y FK al dominio. La memoria es acotada:
  poda los mensajes más antiguos al insertar.
- **`append_conversation_message` / `conversation_history`**: el webhook de
  Chatwoot registra el mensaje del cliente y `_safe_chat_reply` registra cada
  respuesta del asistente (aunque Chatwoot esté desactivado, la memoria es
  del Bridge). Historial con orden estricto por `sequence`, limitado por la
  nueva setting `COMMERCE_CHAT_MEMORY_MESSAGES` (por defecto 12, rango
  2–100).
- **El prompt del asistente recibe el historial**: `commerce_chat` carga los
  últimos N mensajes por conversación (o acepta `history` explícito) y los
  incluye como bloque "Conversación reciente" marcado como contexto de
  continuidad — NUNCA como fuente de datos de producto (las garantías de no
  invención se mantienen).
- **3 evals nuevos**: orden y poda de la memoria (4 mensajes tras insertar 6),
  ignorado de registros vacíos/sin scope, prompt con historial y test de
  integración del webhook (2 turnos completos cliente+asistente persisten en
  la BD del env con la instalación correcta).

## [Calidad de respuestas del chat comercial (2026-08-15)]

- **Persona por cliente**: nueva setting `COMMERCE_ASSISTANT_NAME`
  (por defecto "Asistente de la tienda") que da identidad al asistente en el
  prompt de sistema y en los saludos (útil por instancia gestionada).
- **Prompt de sistema reescrito** (`_commerce_system_prompt`): reglas más
  cortas y sin duplicados, énfasis en responder a la pregunta concreta,
  formato natural (bullets breves, negritas, máx. 1500 caracteres), cierre
  variado por contexto y cierre de compra con presupuesto en el propio chat.
- **Fallback extractivo arreglado y naturalizado**: el saludo ya no responde
  "no encuentro productos" (bug real); `category_empty` reconoce que no hay
  esa categoría y ofrece alternativas reales sin fingir; los resultados se
  agrupan por categoría, se acotan a 12 con nota "y N más", se indica stock
  disponible/agotado y se cierra según la intención (comparación vs.
  presupuesto). Nunca vuelca el bloque crudo de contexto.
- **`_polish_answer`**: recorta extremos y colapsa líneas en blanco (una
  sola entre párrafos) tanto en respuestas LLM como extractivas.
- **5 evals nuevos** en `tests/regression/test_p1_agent_ai.py` (saludo
  cálido, agrupación/cap, polish de respuesta LLM, categoría ausente honesta,
  sin productos). Corpus: **418 passed / 11 skipped / 0 errores**; quality
  gates D-030 PASS.

## [Pitch comercial de venta (2026-08-15)]

- Nuevo `docs/PITCH_COMERCIAL.md`: ficha de producto por segmento
  (distribuidor B2B, fabricante, marketplace) con dolor/solución/evidencia y
  precio orientativo; tabla de diferenciadores con evidencia verificable
  (RPO 25,2 s / RTO 25,1 s SS-05, RBAC 63/63 SS-04, catálogo 41.652 SKUs
  coverage 100 %, ciclo chat→pedido→aprobación real, 413 tests, aislamiento
  P0-006) y la sección explícita de **lo que NO se puede afirmar todavía**
  (SBOM final SS-02, TLS/DNS SS-03, soak SS-06, alertas SS-07) con su cierre
  por fases; plantilla de propuesta por instancia gestionada rellenable
  (alcance, fases con criterios de salida, operación/SLA, condiciones
  económicas, riesgos honestos y anexo de evidencia para el dueño técnico) y
  guion de llamada de 30 min.

## [Propuesta de arquitectura SaaS multi-tenant (2026-08-15)]

- Nuevo documento `docs/ARCHITECTURE_SAAS_MULTI_TENANT.md`: evolución de
  single-tenant por despliegue a **PostgreSQL compartido con RLS**.
  Fundamentado en el inventario real (24 modelos `InstallationOwnedMixin`,
  enforcement ORM deny-by-default, FKs compuestas, `identity_token`,
  `installation_lifecycle`): la columna `installation_id` ya existe en todas
  las tablas, así que el cambio se reduce a (1) resolver el tenant por
  petición (JWT/subdominio) y (2) añadir `FORCE ROW LEVEL SECURITY` con
  `set_config('app.tenant_id', ..., true)` por transacción.
- Incluye: migración 0014 (tabla `tenants`, políticas RLS por tabla owned),
  catálogo de suscripciones `tenant_subscriptions`, matriz de tiers
  Starter/Pro/Enterprise alineada con límites ya existentes (catálogo,
  seats, automatizaciones, RAG, integraciones, SMTP, LLM diario, retención),
  enforcement 402/429 en capa de servicio, plan por fases F0–F4 con
  rollback, riesgos y qué no cambia (modelo, RBAC, backup/restore SS-05).
  Pendiente de decisión de negocio: modelo compartido+RLS como default y
  aislamiento físico (BD por tenant) solo en enterprise.

## [Catálogo de triggers de automatización — tareas + webhooks (2026-08-15)]

- **Catálogo de tipos** en `automations.py` (`SCHEDULED_TASK_TYPES`):
  `automation_sweep`, `prestashop_sync` (diario), `low_stock_alert` y
  `cart_abandonment`. `run_scheduled_task` despacha por tipo con fallo
  explícito para tipos desconocidos.
- **`low_stock_alert`**: resumen por email de productos con stock disponible
  bajo umbral (`threshold`, por defecto 5; `max_items` 20; `recipients`
  obligatorio), solo catálogo de confianza (`import/local/prestashop`, nunca
  demo/fixture), idempotente por producto y ventana ISO; sin destinatarios no
  reclama nada (audita `recipients_missing`).
- **`cart_abandonment`**: follow-up por email de presupuestos en `draft`
  creados hace `abandoned_days` (por defecto 3) y todavía confirmables;
  idempotente por presupuesto y ventana; solo notifica (no confirma ni muta
  importes).
- **`/scheduled-tasks`** acepta los tipos nuevos con validación de payload
  por tipo (422 si falta `recipients`, `threshold`/`abandoned_days` fuera de
  rango, `since` mal formado); el patch valida el resultado fusionado.
  `run-due` ejecuta `prestashop_sync` con lock Redis anti-solapamiento y
  `since` de la última ejecución exitosa; el resto vía catálogo.
- **Webhook triggers** `POST /automations/triggers/{tipo}`: gate de
  aprobación (debe existir una tarea programada `active` aprobada del mismo
  tipo; si no, 409); autenticación por HMAC si `AUTOMATION_WEBHOOK_SECRET`
  está configurado o bearer admin si no; payload fusionado sobre el de la
  tarea aprobada; auditoría `automation_trigger_executed`/`_failed`.
- **Settings nuevos**: `AUTOMATION_WEBHOOK_SECRET` (≥24 chars en producción)
  y `AUTOMATION_WEBHOOK_TIMESTAMP_TOLERANCE_SEC` (por defecto 300,
  conectado a `verify_hmac_signature`).
- **11 evals nuevos** (5 de servicio + 6 de API) en
  `tests/regression/test_p1_automations.py` y
  `tests/regression/test_automation_triggers.py`; dialecto PostgreSQL
  validado contra el catálogo real del candidato (18.734 productos bajo
  umbral 5, 0 demo, SQL de abandono correcto). Corpus: **413 passed / 11
  skipped / 0 errores**; quality gates D-030 PASS.

## [Email real SMTP para automatizaciones — 2026-08-15]

- **Nuevo proveedor** `bridge-api/app/services/smtp_provider.py`
  (`SmtpEmailProvider`): envío real vía SMTP con STARTTLS (587, por defecto)
  o SSL directo (465), autenticación opcional, timeout configurable y
  errores cerrados (`accepted=False` con motivo tipado; nunca éxito fingido).
- **Registro perezoso** en `automations.send_email`: `EMAIL_PROVIDER=smtp`
  activa el envío real sin acoplar el arranque; `local` (default) conserva
  el spool manual sin red. Settings nuevos: `SMTP_HOST/PORT/USERNAME/
  PASSWORD/FROM/STARTTLS/SSL/TIMEOUT_SEC` y `EMAIL_FALLBACK_TO_LOCAL_SPOOL`.
- **Degradación controlada y auditada**: si el proveedor configurado falla y
  el fallback está activo, el correo se encola en el spool local para
  entrega manual conservando el error original (evento
  `automation.email_degraded_to_local` en AuditLog); con fallback
  desactivado, fail-closed (`automation.email_failed`, sin spool).
- **Validación producción** (`validate_runtime_security`): con
  `EMAIL_PROVIDER=smtp` se exigen `SMTP_HOST`, `SMTP_FROM`, puerto válido y
  no SSL+STARTTLS simultáneos.
- **6 evals nuevos** en `tests/regression/test_p1_automations.py` (envío
  STARTTLS con login, fail-closed sin host, éxito auditado, degradación a
  spool, fail-closed sin fallback, proveedor desconocido) — dobles de
  `smtplib`, sin red. Corpus: **402 passed / 11 skipped / 0 errores**;
  quality gates D-030 PASS.

## [Matriz E2E SS-04 — módulos × roles en stack candidato (2026-08-15)]

Cierra el stop-ship **SS-04** (`docs/PRODUCTION_READINESS.md`): E2E final de
los módulos del portal por rol.

- **Nuevo driver** `scripts/e2e_role_matrix.py`: crea un usuario por rol
  (prefijo `e2erm-*`), recorre catálogo, dashboard, clientes, leads,
  presupuestos, pedidos, wiki, tareas programadas y usuarios con cada uno de
  los 7 roles, y verifica el acceso esperado (200/403) según `require_roles`
  + contrato mínimo de cada módulo; desactiva los usuarios al terminar.
- **Resultado en vivo** (proxy `19020`, stack `agent-candidate-0815`):
  **63/63 checks PASS en 5.27 s**. `viewer` recibe 403 en clientes/ventas/
  wiki/tareas/usuarios y 200 solo en catálogo/dashboard; tareas y usuarios
  solo para `provider_admin`/`client_admin`; catálogo y dashboard para todos.
  Dashboard role-aware (`permissions.approve/manage_users`) y envelope del
  catálogo verificados por rol.
- **Limpieza**: usuarios desactivados vía `PATCH /users/{id}` y filas
  borradas por SQL → `users=2` (baseline), 5/5 contenedores healthy.
- Artefacto `logs/rehearsal/e2e_role_matrix_20260815T145447Z.json` y
evidence en `docs/PRODUCTION_READINESS.md` §Evidencia SS-04.

## [Catálogo real + paginación en vivo en stack candidato — 2026-08-15]

### Ejecutado (evidencia operativa)

- **Credenciales PrestaShop** reales (btopdigital.es) inyectadas en
  `.env.candidate-0815` (gitignored) y bridge-api recreado para recogerlas.
- **Sync incremental** `POST /integrations/prestashop/sync?since=1970-01-01`
  (tabla vacía → fetch completo): **41.652 productos creados en 326,5 s**,
  historial `prestashop_sync_history` `success` (incremental, 326,456 s),
  BD `prestashop=41.652 + local=1`.
- **`GET /catalog/products` en vivo** (proxy 19020): `total=41653` con
  envelope `{items,total,limit,offset}`; páginas disjuntas/estables; orden
  por precio/nombre; última página `offset=41600 → 53 items`; recorrido
  completo de **209 páginas → 41.653 IDs únicos (coverage 100 %)**;
  búsqueda `rubik` → 69; `source=local` → 1; `sort` inválido → 422.
- Índice semántico `skipped` en el candidato (sin embeddings remotos); la
  búsqueda léxica opera. Evidencia en `docs/TEST_EVIDENCE.md`.

## [Ensayo integral SS-05 — backup/restore/rollback (2026-08-15)]

Cierra el stop-ship **SS-05** (`docs/PRODUCTION_READINESS.md`): restore/rollback
integral con ensayo final sobre el PostgreSQL real del stack candidato.

### Ejecutado (evidencia operativa, no código)

- **Backup** real con `scripts/backup-restore-integral.py` (formato 4,
  AES-256-CBC + HMAC-SHA256 + SHA256SUMS): 10.9 s, artefacto
  `infrastructure/backups/candidate-0815/candidate-0815-20260815T142452Z-27d46d8c.tar.gz.enc`.
- **Restore** verificado: `restore=PASS` con verificación aislada a destino
  vacío, safety backup previo e inserción in-place. **RTO 25.2 s** a salud
  completa (14:25:39→14:26:04Z).
- **Checks funcionales** post-restore: `alembic_version=0013`, conteos
  idénticos a la baseline, login admin 200, `GET /catalog/products?query=SS05`
  y página pública de wiki 200.
- **RPO** validado por punto-en-el-tiempo: marcadores pre-backup sobreviven;
  el marcador post-backup (`SS05-POST-BACKUP`) se pierde en el restore y
  vuelve a estar presente tras el rollback del safety backup (25.1 s).
- **Limpieza** de marcadores: stack devuelto al estado base (products=1,
  customers=1, wiki=1), 5/5 contenedores healthy, `/ready` 200.

## [Generadores SEO deterministas (T-018) — 2026-08-15]

Porta Contenido/SEO de FlowWink (MIT, D-012) al motor del Bridge sin
Supabase: generadores deterministas sobre el catálogo y la wiki.

### Added

- **`SeoGeneratorService`** (`bridge-api/app/services/seo_generators.py`) —
  genera `sitemap.xml`, `blog-rss.xml` (RSS 2.0), `llms.txt`/`llms-full.txt`
  (formato llmstxt.org) y `knowledge-index.json` (índice con troceo
  determinista para RAG) leyendo solo de PostgreSQL/SQLite vía SQLAlchemy.
- **Rutas públicas locales** en `bridge-api/app/main.py` (tag
  "Publicación local"): `GET /public/sitemap.xml`, `/public/blog-rss.xml`,
  `/public/llms.txt`, `/public/llms-full.txt`, `/public/knowledge-index.json`
  y página pública `GET /public/products/{product_id}` para que los `loc`
  del sitemap resuelvan.
- **Determinismo**: la salida es byte a byte idéntica dado el mismo estado
  de BD y `base_url` — sin timestamps de reloj de pared (`lastBuildDate` e
  `indexed_at` se derivan de los datos), orden estable y escape XML/JSON
  correcto. `base_url` nunca se hardcodea (regla FlowWink): query param
  validado (solo http/https absolutas sin ruta) o origin de la petición;
  valores inválidos → 422.
- **Alcance de contenido**: solo wiki `published`, landings `approved` y
  productos de orígenes de confianza sin demo y comercialmente disponibles
  (mismas reglas que el catálogo operativo). Sin publicación externa:
  cabecera `X-External-Publication: not-performed` y `Cache-Control:
  public, max-age=60`.

### Tests

- `tests/regression/test_seo_generators.py` — 7 evals nuevos: validez de
  salida (XML/RSS parseables con ElementTree, JSON con esquema 1),
  determinismo (dos llamadas idénticas byte a byte), exclusión de
  draft/demo/productos no disponibles, escape de caracteres, derivación de
  `base_url` del origin, rechazo 422 de `base_url` inválida y página pública
  de producto con CSP/sandbox.

## [Catálogo del portal paginado — 2026-08-15]

Cierra el pendiente del informe de auditoría 2026-08-10 (T-027): el portal
operativo no puede volcar catálogos de decenas de miles de productos
(41.652 sincronizados en vivo) en una sola tabla.

### Added

- **`GET /catalog/products`** (`bridge-api/app/main.py`) — envelope paginado
  `{items, total, limit, offset}` con los mismos productos visibles que el
  chat (orígenes de confianza, sin demo, comercialmente disponibles):
  `query` (reutiliza la relevancia del buscador léxico), `limit` (1–200),
  `offset`, `sort`/`order` whitelisted (`name`, `sku`, `category`,
  `unit_price`, `available_stock`, `created_at`, `updated_at`) y filtro
  opcional por `source`. El conteo total aplica la disponibilidad comercial
  en ambos dialectos; en SQLite se filtra en Python (predicado JSON no
  portable), en PostgreSQL en SQL con LIMIT/OFFSET.
- **Frescura** — `_product_dict` expone ahora `created_at`/`updated_at`
  (ISO 8601 UTC con sufijo `Z`) en todas las rutas de producto.
- **Portal** — la sección Productos sustituye el volcado completo por una
  barra de búsqueda, filtro por origen, orden ascendente/descendente,
  paginación (50 por página) y columna "Actualizado" con etiqueta de
  frescura (Hoy / Ayer / Hace N días / fecha). Se conservan la búsqueda
  semántica y la importación con validación previa.

### Tests

- 7 evals backend nuevos (`tests/regression/test_catalog_portal_pagination.py`):
  envelope + frescura, paginación disjunta y estable, orden por precio/nombre,
  filtro por origen, ocultación de demo, ocultación de PrestaShop no vendible
  y rechazo de parámetros inválidos (422).
- 3 evals frontend nuevos (paginación y resumen, búsqueda que pagina,
  controles de orden/filtro); el mock de rutas ahora casa rutas con query
  string.

### Verificación

- Corpus hermético backend: **388 passed, 11 skipped** (80 s).
- Portal: **27/27** tests, typecheck, `format:check` y build verdes.
- Quality gates D-030: PASS (hard 0, clean 0, ratchet 129 ≤ baseline 243).

## [Remediación de auditoría 2026-08-10]

Esta entrada cierra los defectos P0/P1 reabiertos por `docs/PROJECT_STATUS_AUDIT_2026-08-10.md`. Cada cierre incluye eval de regresión en `tests/regression/test_audit_remediation_2026_08_10.py` y en los suites existentes.

### Security / P0

- **Restore destructivo (`bridge-api/app/services/backup.py`)** — `restore_to_url` ya no invoca `Base.metadata.drop_all(engine)` sobre el destino. Ahora exige un marker explícito (`_bridge_restore_marker`) creado por `prepare_restore_target(database_url, schema_version=...)` en una base recién inicializada. Sin marker, o con tablas de aplicación presentes, se lanza `RestoreSafetyError` sin modificar nada. Tres evals (`test_restore_to_url_refuses_base_without_marker`, `test_restore_to_url_with_marker_succeeds` y un test de poblado intacto). La rama `restore_backup(engine, manifest)` (test hermético) y los tests `test_p0_migrations` que usaban `restore_backup` directamente siguen pasando.

### Core / P1

- **Idempotencia del webhook (`bridge-api/app/main.py`)** — el handler `/webhooks/chatwoot` ahora garantiza transición a `state="completed"` tras cada rama de éxito. Cada `return` temprano llama a `_complete_idempotency` y marca `terminal_done=True`; un `try/finally` finalizador (`_complete_idempotency_if_pending`) cierra defensivamente cualquier checkpoint dejado en `processing`. El replay del mismo `message_id` ahora devuelve 200 con la respuesta cacheada en lugar de 202 `processing`. Nuevo eval `test_webhook_replay_returns_cached_result_not_processing` verifica el flujo contra `IdempotencyRecord.state == "completed"`.
- **Migración 0006 (`bridge-api/alembic/versions/0006_product_embeddings.py`)** — la revisión se hace explícitamente dialect-aware: en **PostgreSQL** crea la tabla `product_embeddings` con `pgvector.sqlalchemy.Vector(768)`, FK compuesta tenant-safe `installation_id, product_id → products(installation_id, id) ON DELETE CASCADE`, índice ivfflat opcional y `CREATE EXTENSION IF NOT EXISTS vector`; en **SQLite** (corpus de tests hermético) sale temprano sin crear la tabla ni ejecutar `CREATE EXTENSION`. Downgrade preservador (no-op). Se actualizan los tests `test_p0_migrations` para esperar `0006` como nueva cabeza y se añade `test_0006_is_dialect_skip_on_sqlite`.
- **Catálogo local cuando PrestaShop no está (`bridge-api/app/main.py`)** — nuevo helper `_default_catalog_source()`: devuelve `"prestashop"` si el adaptador está configurado, o `None` (todos los productos visibles del catálogo local) si no. Todas las llamadas del chat comercial (`catalog_overview`, `catalog_full_list`, `verified_product_recommendations`, `catalog_browse_prompt`, comparador y resúmenes de categorías) usan el helper en lugar de hardcodear `source="prestashop"`. Dos evals (`test_default_catalog_source_returns_none_when_prestashop_not_configured` y `test_default_catalog_source_returns_prestashop_when_configured`).
- **NameError `_LOG` (`bridge-api/app/main.py:1983`)** — la rama fallback de `commerce_chat` ya no usa `_LOG` (que no estaba definido). Ahora emite `log_event("WARNING", "commerce_chat_failed_fallback_extractive", ...)` desde `app.services.observability` con redacción determinista.

### Integraciones / P1

- **SSRF Chatwoot (`docker-compose.yml`)** — `SAFE_FETCH_ALLOW_PRIVATE_NETWORK` deja de estar fijado en `"true"` y pasa a `${CHATWOOT_SAFE_FETCH_ALLOW_PRIVATE_NETWORK:-false}`. La postura segura por defecto exigida por la auditoría queda alineada con el override explícito para desarrollo local.
- **Webhooks salientes (`bridge-api/app/services/automations.py::send_webhook`)** — la firma HMAC ya no cae a `idempotency_key` cuando falta `WEBHOOK_OUTBOUND_SECRET`; exige secreto de ≥32 caracteres y `key_id` configurable. Se añaden cabeceras `X-Bridge-Webhook-Key-Id` y `X-Bridge-Webhook-Timestamp` para rotación y anti-replay. Se añade `_assert_outbound_url_allowed()` con allowlist (`WEBHOOK_OUTBOUND_ALLOWED_HOSTS`) y resolución IP previa al envío que bloquea loopback, RFC1918, link-local, multicast, reservados y no-especificados. Errores devueltos con `accepted=False` (`status="rejected"` o `"failed"`), nunca éxito falso.
- **Email provider (`bridge-api/app/services/automations.py::send_email` + `LocalEmailProvider`)** — `LocalEmailProvider.send` ya no silencia `OSError` ni devuelve `accepted=True` cuando el disco falla; ahora `accepted=False` con `error="local_provider_io_error:..."`. `send_email` falla cerrado cuando el proveedor configurado no está registrado (sin fallback silencioso a local). Auditoría diferenciada (`automation.email_sent` vs `automation.email_failed`).

### Pendiente (no cerrado por esta entrada)

- Portal RBAC (matriz de rutas/acciones, navegación por rol, aprobaciones con detalle y confirmación accesible).
- Portal catálogo paginado con búsqueda/orden/filtros + exposición de `updated_at` y origen/frescura.
- Rate limiting/proxy trust endurecido (CIDR allowlist, IP derivada por cadena validada, Redis como backend).
- Production Compose con TLS, listener 443, certificados, redirección 80→443 y eliminación de 9000 público.
- Supply chain (actualizar `nanoid@3.3.16`, fijar imágenes por digest, CI autoritativa con SBOM y escaneo de imágenes).
- Licencias y revisión legal de vendor/EE.

## [Remediación PrestaShop live — 2026-08-10]

Validación end-to-end contra la tienda real `https://btopdigital.es/`
con las credenciales del `.env`. 15 / 15 escenarios verdes con datos
reales (IVA España 0.21, country_id=6, currency_id=EUR, productos
ACUARELA, JOVI, etc.).

**Bug reproducible y corregido:** el Webservice de PrestaShop **no
soporta wildcards** en `filter[name]` ni `filter[reference]`. Verificado
con PrestaShop: `filter[name]=%ACUARELA%` devuelve `[]` aunque existen
productos con "ACUARELA" en `name`. La integración quedaba con 0
resultados en producción sin error visible.

- `bridge-api/app/services/prestashop_adapter.py`: `search_products()`
  cae a listado paginado + filtrado en memoria sobre `name`, `reference` y
  `description_short`, **con parada temprana** al alcanzar `safe_limit`
  matches para no iterar catálogos de 10000+ productos cuando solo queremos 10.
  Mantiene el resto del contrato (límite, `include_details`, sellable,
  stop-words).
- `tests/regression/test_prestashop_webservice_search.py`: 3 evals nuevos
  (1 offline + 2 opt-in con tienda real, skipped sin credenciales).
- `tests/regression/test_p1_prestashop_safety.py`: actualiza
  `test_adapter_search_does_not_expose_non_sellable_products` para
  mockear `_get_paginated_rows` además de `_get`.

Verificación live (`tests/regression/test_prestashop_webservice_search.py`
skipped sin credenciales, ejecutado con `.env` real):

```
search_products('ACUARELA', limit=5) → 5 productos reales
search_products('sacapuntas', limit=5) → 5 SACAPUNTAS reales
search_products('JOVI') → productos JOVI con sku y stock reales
```

Corpus afectado (verificado): 77 / 77 verdes en
`test_prestashop_webservice_search` + `test_p1_prestashop_safety` +
`test_p0_prestashop_contract` + `test_audit_remediation_2026_08_10` +
`test_p1_backup_restore` + `test_p0_migrations` +
`test_p1_idempotency_followups`.

## [Auditoría de estado 2026-08-10]

- Nuevo informe actual: `docs/PROJECT_STATUS_AUDIT_2026-08-10.md` y artefacto HTML autocontenido.
- Reevaluación mantiene `NOT PRODUCTION READY — CRITICAL RISK` y documenta regresiones actuales: restore con `drop_all()` sin guard, migración `0006` incompleta, idempotencia del webhook, catálogo local excluido, quality gates rojos, SSRF/TLS/rate limit, RBAC del portal y supply chain.
- Se actualizan `STATUS.md`, `TASKS.md`, `BLOCKERS.md`, `docs/PRODUCTION_READINESS.md` y `docs/TEST_EVIDENCE.md` sin modificar código de producción ni el cambio ajeno `0006`.

## [Informe de estado 2026-08-09]

- Informe técnico completo del proyecto en `release/project-status-report/PROJECT_STATUS_REPORT.pdf` (21 páginas, A4, ReportLab).
- Generador: `scripts/generate_project_status_report.py` (re-ejecutable: `python scripts/generate_project_status_report.py`).
- Resume: decisión NOT PRODUCTION READY — CRITICAL RISK, defectos abiertos, lo verificado, trabajo pendiente, plan de cierre, bloqueos externos, los 30 criterios PR-, riesgos críticos y roadmap 30/60/90. Cualquier informe previo queda SUPERSEDED para decisiones actuales.

## [Unreleased]

### Added

- Catálogo verificado en preguntas libres de chat (cat_overview): cuando el cliente pregunta algo genérico tipo "¿qué tenéis?", "¿qué me recomiendas?" o nombra un dominio sin match específico, el flujo `/webhooks/chatwoot` cae a un resumen del catálogo sincronizado desde PrestaShop (límite 8, sin LLM) en lugar de transferir al equipo comercial o de abstenerse; helper `_looks_like_product_inquiry` detecta intención de catálogo (tokens de producto/catálogo/existencias/recomendación + hints de dominio) y se respeta la rama previa `verified_product_recommendations` cuando hay coincidencia específica; 3 evals nuevos (`catalog_overview`, `product_inent_falls_back_to_overview_when_no_specific_match`, `short_greeting_is_not_treated_as_product_inquiry`).
- SSRF Chatwoot→Bridge en desarrollo local: `SAFE_FETCH_ALLOW_PRIVATE_NETWORK: "true"` añadido al bloque `&chatwoot-environment` del compose (consumido por `vendor/chatwoot/lib/safe_fetch.rb`) para que el webhook pueda entregar al hostname interno `bridge-api` sin ser filtrado por `ssrf_filter`; en producción el webhook debe ir a un dominio público y la variable debe quedar apagada.
- PrestaShop resultado vacío (D-033/D-034, `7b6f3b1`): PrestaShop devuelve `[]` cuando una búsqueda no tiene resultados; el adaptador lo trataba como "formato inesperado". Ahora se trata como colección vacía. E2E de solo lectura contra la tienda real verificado (`sync?dry_run` leyó productos reales); el test fail-closed se fuerza sin credenciales para no tocar la red (D-032).
- Licencias (D-023, `8a098f3`): `LICENSE` raíz (código propio propietario + puntero a notices), `THIRD_PARTY_NOTICES.md` actualizado y `docs/LICENSE_MATRIX.md` con licencias Python verificadas vía `importlib.metadata`; vendor/EE marcados "requiere revisión legal" (B-008).
- Validación stricta production-like ampliada (D-022, `6c689da`): `validate_runtime_security` (llamada al arrancar) rechaza en producción SQLite, CORS/host abiertos y DEBUG, además de secretos débiles, mocks/stubs, demo y presupuestos de retry/breaker/outbox; 12 evals.
- Preflight atómico de puertos (D-009, `19e7f71`): `provision-client.sh`/`.ps1` validan daemon accesible y puerto proxy libre antes de escribir `.env`/build/up, para no alterar instalaciones existentes ni dejar artefactos parciales; test hermético de `port_in_use` (Linux) y sintaxis bash.
- Chat sin Chatwoot (Ruta A) + E2E (`c2f4b84`): el webhook de chat degrada el reply/efectos de Chatwoot a un canal interno auditado cuando `CHATWOOT_API_TOKEN` no está configurado, y el core completa chat→lead→presupuesto sin dependencias externas; `scripts/e2e_core_chat_to_quote.py` lo verifica en vivo (webhook firmado HMAC → `quote_created` con total determinista 136,00 y token `CONFIRMAR <TOKEN>`); `ChatwootAdapter.api_token` pasa a propiedad (settings o valor fijado).
- Infra runtime verificada (D-008/D-025): proxy nginx con `cap_add` CHOWN/SETGID/SETUID (workers estables sin `setuid EPERM`), upstreams opcionales chatwoot/activepieces con resolución perezosa (`resolver`+variable) para que el perfil core arranque sin ellos (502 graceful), y límites `deploy.resources` (CPU/memoria/pids) por servicio; perfil core levantado y smoke 200 por el puerto 9000.
- Backup/restore/rollback verificables por instalación (D-015/D-016): `app/services/backup.py` con `create_backup` (manifiesto con conteos+sha256 por tabla), `restore_backup` a motor vacío, `verify_backup` (compara conteos y checksums) y `rollback_installation` (restaura datos de una instalación a un punto conocido, independiente del resto); restauración REAL verificada en SQLite y PostgreSQL efímero (opt-in `RUN_POSTGRES_BACKUP=1`, contenedor pgvector, dos BDs, extension vector); 4 evals (`6b34200`).
- Agentes/IA FlowWink sin Supabase, lote 2 (D-012): `app/services/agent_ai.py::docs_chat` (port de `docs-chat`) con búsqueda RAG y ACL por rol, abstención sin evidencia, citas verificables y respuesta extractiva honesta (`provider="extractive"`) cuando no hay LLM real (B-006); endpoint `/agents/docs-chat` con roles; 3 evals; `agent_ai.py` en zona limpia del gate D-030 (`59558a1`).
- Automatizaciones FlowWink sin Supabase, lote 1 (D-012): `app/services/automations.py` con router de email de proveedor local (sin red), `quote-expiry-reminders` idempotente por ventana, `dunning-processor` (solo notifica y marca `overdue`, sin mutar importes), `generate-invoice-pdf` determinista de solo lectura, `send-webhook` firmado HMAC sobre circuit breaker y sweep agregado pull; endpoints `/automations/sweep` y `/automations/invoices/{id}/pdf` con roles; 7 evals; `automations.py` en zona limpia del gate D-030 (`bf647cf`).
- Quality gates D-030: `scripts/quality_gates.py` con tres puertas (`ruff-hard` E9,F sobre todo el código propio, `ruff-clean-zone` reglas completas sobre módulos nuevos y tests, `ruff-ratchet` con trinquete sobre el baseline visible de `scripts/quality_baseline.json`), opciones `--with-tests`/`--with-portal`/`--update-baseline` y 6 evals de regresión (`ca73a6c`).
- Portal con secciones reales y tests de componentes (D-026/D-027): la navegación deja de prometer módulos fantasma — los cinco anchors rotos (catálogo, documentos, agentes, automatizaciones, usuarios) apuntan a secciones renderizadas con datos reales (`GET /tools/products`, nuevo `GET /rag/documents`, `GET /agents`, `GET /users`) y estado explícito de Activepieces con nota de alcance Ruta A; estados vacío/error por sección; i18n recortado a etiquetas reales; runner vitest + testing-library + vitest-axe con 5 evals (accesibilidad axe incluida); endpoint `GET /rag/documents` sin rutas de disco ni contenido (`33d77c1`).
- Ciclo de vida de datos por instalación (D-029): `LifecycleService` con export JSON portable (clientes, catálogo, presupuestos, pedidos, facturas, conversaciones, aprobaciones, RAG, idempotencia y outbox; nunca users ni AuditLog), erase con retención configurable e inmediata, `process_due_erases` para borrados vencidos y legal hold que bloquea cualquier erase; borrado en orden FK con eliminación de archivos RAG; modelo `InstallationLifecycle` + migración aditiva `0005`; endpoints `/lifecycle/{status,export,erase,legal-hold,process-due-erases}` con `ADMIN_ROLES`; auditoría `lifecycle.export/erase/erase_scheduled/erase_skipped/legal_hold` (`ff0eed8`).
- Observabilidad D-028: middleware FastAPI con logs JSON correlacionados (correlation_id, request_id, tenant_id, user_id, route, method, status, latency_ms), contextvars por proceso con restauración robusta, helpers `log_event`/`record_metric` con redacción determinista por clave y valor, métricas Prometheus para HTTP/outbox/breaker/RAG/alertas y reglas in-memory `circuit_breaker_open`/`outbox_dead_letter_growth`/`rag_abstention_rate`/`dlp_findings` integradas en `/metrics` (`af53b8b`).
- Auditoría de dependencias D-017: `scripts/audit_dependencies.py` ejecuta `pip-audit` y `npm audit --omit=dev` y falla si high/critical >0; tests anti-regresión de rangos de Pillow, pypdf y Vite (`7fb4f45`).
- Clasificación, DLP y defensa anti prompt injection para RAG (D-020): niveles `public`/`internal`/`confidential`/`restricted` con ACL deny-by-default (legado sin clasificación conserva ACL estricta); DLP determinista en ingesta (DNI/NIE con letra, tarjeta con Luhn, IBAN ES mod-97, JWT, AWS, claves `sk_live`, claves privadas) que eleva la clasificación a `confidential` sin persistir valores; redacción de secretos en respuesta y citas; bloqueo de consultas con patrones de inyección y marcado `trusted=false` del contenido recuperado (`0541650`).
- Reconciliación GHL previa al efecto (D-010): `find_opportunity_by_reference` (custom field `external_reference`) y `find_note_by_body` en el adaptador, integradas en el dispatcher del outbox y en `/integrations/ghl/leads`; paginación acotada hasta EOF con fallo cerrado ante listados anómalos, DLQ directa para leads sin referencia externa, checkpoint `reconciled` y auditoría `ghl_lead_reconciled` (`ce2723c`).
- Recuperación de crash ambiguo en el webhook comercial (D-035): checkpoint del resultado tras cada efecto externo visible y resume en takeover (`_resume_webhook_from_checkpoint`) que completa desde un checkpoint de éxito sin repetir respuestas ni presupuestos; auditoría `webhook_checkpoint_resume` (`5a3edf8`).
- Resiliencia de integraciones (D-021): circuit breakers por proveedor (`chatwoot`, `ghl`, `prestashop`, `activepieces`), outbox durable con enqueue idempotente, claim CAS, backoff determinista y dead-letter queue, endpoints `GET /outbox`, `POST /outbox/process` y `POST /outbox/{id}/retry` con roles, métricas de outbox/breakers y migración aditiva `0004` (`3733bad`).
- Executor de herramientas deny-by-default (`ToolExecutor`, `/agents/tools/invoke`, `GET /agents/{id}/tools`): allowlist estricta por agente contra un catálogo cerrado, validación de argumentos, herramientas financieras prohibidas para agentes y auditoría de cada decisión (`4d97449`, D-012).
- Prompt operativo raíz en `agents.md`.
- Repositorio Git local y rama `production-remediation`.
- Punto de recuperación pre-remediación `ed77056`.
- Registros autoritativos `TASKS.md`, `STATUS.md`, `DECISIONS.md` y `BLOCKERS.md`.
- Baseline, plan de remediación, readiness y evidencia persistente en `docs/`.
- Registro de 32 defectos, registro de riesgos y evidencia reproducible de Fase 1.
- Diecinueve tests rojos de regresión para aislamiento, demo, confirmación, comercio, migración, integraciones y seguridad.
- Migración `0002` tenant-safe, contexto obligatorio de instalación y 12 relaciones compuestas diferibles.
- Verificadores PostgreSQL efímeros para concurrencia P0, adopción histórica y downgrade/reupgrade seguro.
- Contratos de regresión para demo, confirmación, PrestaShop, stock, aislamiento y falsos positivos del verificador.
- Registro ampliado a 37 defectos tras la revisión adversarial: 7 verificados y 30 abiertos.

### Changed

- La captura de leads GHL ya no se pierde ante averías del proveedor: el webhook comercial completa la respuesta y encola el efecto externo en el outbox con checkpoints durables; la recuperación llega vía `POST /outbox/process` sin duplicar contactos ni oportunidades (`3733bad`, D-021).
- El propietario aprobó la Ruta A (candidata core con limitaciones documentadas) y la parada del stack antiguo, ejecutada el 2026-08-03: compose projects `agent-platform`, `agent-piloto-rc1` y `agent-cliente-demo-es-staging` detenidos con volúmenes intactos; puerto 9000 liberado.
- El estado comercial queda fijado en `NOT PRODUCTION READY — CRITICAL RISK` hasta superar todos los gates.
- Los resultados históricos se tratan como evidencia previa, no como verificación actual.
- La Fase 0 queda cerrada con baseline de host/Git/Docker, inventario, dependencias, propiedad de datos y 30 criterios de readiness bloqueados.
- La Fase 1 contrasta 30 defectos heredados y añade D-031/D-032 sin aplicar todavía correcciones de producción.
- Los seis P0 reproducidos quedan verificados en `de236e9`; la Fase 2 continúa con 25 P1 y 5 P2 abiertos.
- Pricing usa autoridad fiscal/variantes/scopes PrestaShop, precedencia compatible o fail-closed, `Decimal` y umbral de envío por presupuesto.
- El catálogo acepta únicamente orígenes de producción confiables; demo y orígenes desconocidos fallan cerrados.

### Fixed

- La deuda de calidad sin control (D-030): B008 excluido globalmente (patrón `Depends()` de FastAPI, consenso del bloque P1), deuda de estilo en tests legacy corregida (E402 con noqa justificado en `conftest.py`, statements compuestos separados en `test_hardening.py`) y la deuda restante (213 hallazgos) queda documentada por regla en un baseline con trinquete que prohíbe su crecimiento (`ca73a6c`).
- Los claims de documentación contradictorios (D-026): README reescrito contra la fuente autoritativa `docs/PRODUCTION_READINESS.md` y banners SUPERSEDED en `REMEDIATION_REPORT.md`, `MASTER_PLATFORM_REPORT.md`, `FINAL_REPORT.md` y `COMMERCIAL_READINESS_REPORT.md`; la navegación del portal ya no promete módulos sin renderizar (D-027) (`33d77c1`).
- La ausencia de ciclo de vida de datos: ahora cada instalación puede exportar sus datos en formato portable y solicitar el borrado con retención configurable; el legal hold bloquea cualquier erase y queda auditado; los archivos RAG se eliminan del disco dentro del directorio de subidas; el AuditLog y los usuarios sobreviven al borrado operativo (`ff0eed8`, D-029).
- Los logs sin correlación ni redacción: cada petición queda trazada con correlation_id/request_id y los secretos (password, tokens, claves, tarjetas, claves privadas) se redactan antes de emitirse; los imports muertos del middleware de observabilidad se limpiaron en `ff0eed8` (`af53b8b`, D-028).
- Dependencias vulnerables: Pillow fijado en 12.x (cierra 49 CVEs en 10.x/11.x), pypdf en 6.x (cierra CVE de 5.9) y Vite subido a ^7 (esbuild path traversal cerrado). `pip-audit` y `npm audit --omit=dev` reportan 0 vulnerabilidades (`7fb4f45`, D-017).
- La fuga de secretos por DLP evadible y la falta de clasificación RAG: ahora los secretos detectados (DNI, tarjeta, IBAN, JWT, claves) elevan la clasificación del documento a `confidential` y se redactan en respuesta y citas; las consultas que intentan manipular las instrucciones del sistema se rechazan; el contenido recuperado se marca como no confiable (`0541650`, D-020).
- La microventana efecto→checkpoint de GHL (residual de D-035) ya no duplica oportunidades ni notas: como GHL no acepta claves de idempotencia, cada creación se reconcilia antes contra el proveedor y se reutiliza el efecto existente; una búsqueda de reconciliación fallida falla cerrada y nunca se crea a ciegas (`ce2723c`, D-010).
- Un crash del worker entre el efecto externo y el cierre de idempotencia ya no duplica efectos en la redelivery: el takeover detecta el checkpoint de éxito y completa sin reenviar la respuesta ni recrear el presupuesto; la deduplicación por `source_message_id` protege los reintentos sin checkpoint (`5a3edf8`, D-035).
- El cierre de `installation_scope` restaura el ámbito anterior aunque el cleanup se ejecute en un contexto distinto (cierre de dependencias generador tras un error de petición); los errores esperados ya no se convierten en 500 (`3733bad`).
- El outbox cuenta los intentos correctamente al agotar reintentos y los checkpoints del dispatcher GHL se persisten con diccionarios nuevos para que SQLAlchemy detecte cada actualización JSON (`3733bad`).
- Harness de tests hermético (D-032): los unit tests de guards usan valores production-like explícitos; el corpus combinado `pytest tests bridge-api/tests` pasa 159/159 en cualquier orden de colección y sin entorno del operador (`4afd0c7`).
- Confirmación comercial exacta con token HMAC de 128 bits almacenado como SHA-256, caducidad, actor firmado y replay idempotente.
- Reservas locales con TTL y transiciones atómicas de release/cancel/expire; stock externo no se confirma sin autoridad transaccional.
- Downgrades destructivos sustituidos por migraciones explícitas, compatibles y no destructivas.
- Aislamiento ORM de 14 modelos tenant-owned, incluida identidad de sesión al cambiar de instalación.

### Security

- Los agentes ya no pueden ejecutar herramientas fuera de su allowlist; la inyección de instrucciones por `/agents/run` no ejecuta herramientas, los argumentos no declarados (p. ej. `custom_vat_rate`) se rechazan y los roles viewer no pueden invocar (`4d97449`).
- Se comprobó que `.env` permanece ignorado por Git.
- El escaneo de patrones de secretos previo al recovery commit no detectó coincidencias de alta señal en código propio.
- `.env` continúa ignorado/no trazado y el escaneo P0 no detectó patrones de secreto de alta señal.
- El verificador rechaza bases no efímeras ligadas al run, no usa `assert` y elimina todos sus datos sintéticos incluso bajo `python -O`.
