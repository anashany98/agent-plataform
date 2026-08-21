# Agentes de IA especializados por módulo

> Estado: **implementado en su primera fase (T-057)** — registro de agentes
> por módulo con herramientas read-only deterministas, sobre la base ya
> existente de `tool_policy` (deny-by-default), aprobaciones y auditoría.
> El resto (Fase 2 en adelante) es roadmap con criterios de salida.

## 1. Visión

Bridge no es «una app con un chat»: es una **plataforma gobernada por
agentes especializados**, uno por módulo de negocio. Cada agente tiene:

- una **persona y propósito** específicos de su módulo (no un LLM genérico);
- un **alcance** declarado (qué puede mirar y qué puede tocar);
- un **conjunto de herramientas** autorizado (intersección estricta con el
  catálogo deny-by-default — nunca al revés);
- un **nivel de autonomía** (tier) que decide qué hace solo, qué propone y
  qué exige aprobación humana;
- **presupuesto mensual** de LLM y **auditoría completa** de cada invocación.

La regla innegociable del proyecto se mantiene: las herramientas con efecto
financiero/contable (confirmar pedidos, emitir facturas, fijar precios,
reservar stock) **nunca** son invocables por un agente; exigen flujo de
aprobación humana y servicios deterministas dedicados.

## 2. Mapa módulo → agente

| Módulo | Agente | Persona / propósito | Herramientas (hoy) |
|---|---|---|---|
| Catálogo | `catalog_agent` | Especialista en productos, SKUs, stock y precios; responde solo con datos reales del catálogo | `search_products`, `get_product`, `check_stock`, `calculate_price` |
| Ventas | `sales_agent` | Comercial B2B: recomienda, presupuesta (borrador) y deriva a aprobación | `search_products`, `get_product`, `check_stock`, `calculate_price`, `create_quote` |
| Clientes/CRM | `crm_agent` | Comercial de CRM: lee leads, oportunidades, actividades y el pipeline para priorizar y preparar acciones | `list_leads`, `list_activities`, `get_pipeline_report` |
| Escucha social | `social_agent` | Operador de inbox social: vigila mensajes, triaje y SLAs; alerta de quejas | `list_social_inbox`, `get_social_stats` |
| Email y campañas | `marketing_agent` | Responsable de email: revisa campañas, destinatarios y resultados (nunca envía sin aprobación) | `get_campaign_stats`, `list_campaigns` |
| Contenido y SEO | `content_agent` | Documentalista: responde con evidencia del RAG/wiki y abstiene sin fuentes | `rag_search` |
| Operaciones y gobierno | `ops_agent` | Supervisa el estado técnico (workers, outbox, integraciones) y prepara informes | (`monitoring` — Fase 2) |

La duplicación de herramientas entre módulos es **intencional**: cada agente
tiene su subconjunto y su persona; un agente de ventas y uno de catálogo
pueden mirar el mismo producto con propósitos distintos.

## 3. Tiers de autonomía (progresión auditada)

| Tier | Nombre | Qué puede hacer | Aprobación |
|---|---|---|---|
| L0 | Respuesta limitada | Solo responder con lectura | No requiere |
| L1 | Venta asistida | Leer + crear borradores (p. ej. presupuesto borrador) | El borrador queda pendiente de aprobación |
| L2 | Gestión asistida | Proponer acciones dentro del módulo (tareas, recordatorios, drafts) | Cada efecto mutante requiere aprobación |
| L3 | Autónomo | Ejecutar rutinas aprobadas (sync, limpieza) | La rutina se aprueba **una vez** (p. ej. en `ScheduledTask` con aprobación) y luego se audita cada ejecución |

Un agente **nunca** sube de tier sin una definición durable aprobada
(`AgentDefinition.status == active`): el tier se lee de la configuración
persistida, no del prompt.

## 4. Patrón de implementación (Fase 1, hecha)

La Fase 1 materializa la columna vertebral sin tocar el chat:

1. **Herramientas read-only por módulo** en `DeterministicToolsService`:
   `list_leads`, `list_activities`, `get_pipeline_report`,
   `list_social_inbox`, `get_social_stats`, `get_campaign_stats`,
   `list_campaigns`. Todas deterministas, sin LLM/red y **sin mutación**
   (kind `read`).
2. **Registro de agentes** (`AGENT_REGISTRY`): catálogo built-in de agentes
   por módulo con `module`, `module_label`, `scope`, persona (`purpose`/
   `prompt`), `allowed_tools` honestos y presupuesto. Los agentes built-in
   no se sobrescriben por API (409), igual que `sales_agent`/`rag_agent`.
3. **Tool policy**: las tools nuevas entran en `TOOL_SPECS` (kind `read`);
   el executor audita cada invocación (`tool_call` success/denied/error).
   El `AgentConfigSchema` sigue con `extra="forbid"`: `module`/`scope` son
   metadatos de los built-in, no campos editables por el usuario (evita
   suplantar un módulo con un agente propio).
4. **Test hermético**: todo agente del registro tiene `module` + `scope`;
   ninguna `allowed_tools` contiene prohibidas; los agentes invocan sus
   tools; un agente sin tool o una tool desconocida → denied auditado.

## 5. Fase 2 (roadmap): ejecución con aprobación

Conectar los agentes a los canales de acción ya existentes, siempre con el
flujo de aprobación del proyecto:

| Canal | Pieza existente | Uso por agente |
|---|---|---|
| Tareas programadas | `ScheduledTask` + `ApprovalRequest` | El agente propone una rutina; se aprueba una vez; cada ejecución se audita |
| Automatizaciones | catálogo de `automations` (webhook, scheduled) | El agente arma el trigger y el payload; el alta pasa por aprobación |
| Actividades de comercial | `Activity` + reminder worker | L2: el agente propone follow-ups sobre leads que superan SLA |
| Campañas | `POST /campaigns/{id}/send` (admin) | L2: el agente prepara la campaña y **propone** el envío; solo un humano lo dispara |
| Inbox social | `POST /social/messages/{id}/dismiss` | L1: el agente sugiere descartar spam; el descarte lo confirma un operador |

Criterio de salida de cada pieza de la Fase 2: eval hermético de que el
agente **propone pero no ejecuta** sin aprobación, y de que la aprobación
queda auditada con `approval_id`.

## 6. Fase 3 (roadmap): supervisor y plan de pruebas

- **Supervisor** (`ops_agent` ampliado): agrega el estado de todos los
  módulos (workers, outbox, integraciones, SLAs) y deriva incidencias a los
  agentes especializados; un panel en el portal muestra qué agente gestiona
  cada módulo y su última actuación.
- **LLM-as-judge por módulo**: la rúbrica de naturalidad existente se
  parametriza por persona; cada agente se evalúa sobre evidencias de su
  módulo (rehearsal), con gate de calidad (media ≥ 4) en CI.
- **Test de aislamiento**: un agente de un módulo nunca puede invocar
  herramientas de otro (denied + auditado).

## 7. Definición de «hecho» (aplica a cada fase)

1. Catálogo de agentes por módulo visible y con metadatos (`module`,
   `scope`, tier, tools).
2. Tool policy deny-by-default: nuevas herramientas declaradas, validadas y
   con executor; ninguna prohibida autorizada.
3. Evales herméticos backend (registro, RBAC de tools, denied auditado) +
   vitest del portal si cambia UI.
4. Corpus completo y gates D-030 PASS.
5. `TASKS.md`/`STATUS.md`/`CHANGELOG.md`/`TEST_EVIDENCE.md` actualizados.
