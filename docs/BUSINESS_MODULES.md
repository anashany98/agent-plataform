# Módulos de negocio

## Lectura del inventario

`Implementado` describe código y pruebas existentes; no equivale a certificación del stack final. `Core` indica que no requiere el perfil vendor `full`. Los gates definitivos siguen en [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).

| Módulo | Capacidad real | Perfil | Límites que deben comunicarse |
|---|---|---|---|
| Autenticación y usuarios | Login, logout, cambio de contraseña, alta/edición y revocación por `token_version` | Core | JWT en `sessionStorage`; sin MFA/SSO |
| Dashboard | Resumen operativo y capacidades por rol | Core | Métricas internas; no BI histórico externo |
| Clientes | Listado y alta idempotente | Core | CRM local por defecto; sincronización externa separada |
| Catálogo/productos | Búsqueda exacta/textual/semántica local, ficha, stock y pricing | Core | El origen local debe cargarse; PrestaShop es opcional/no certificado |
| Leads y oportunidades | CRM local, listado y creación | Core | No incluye pipeline comercial externo completo |
| Presupuestos | Crear/listar/detalle, cálculo servidor y confirmación | Core | La confirmación crea pedido bajo contrato; requiere control humano operativo |
| Pedidos | Listado/detalle derivados de presupuesto confirmado | Core | Sin fulfillment, logística o pagos integrados certificados |
| Facturas | Borrador, listado, solicitud de aprobación y PDF | Core | `approved` no equivale a emisión fiscal; emisión automática desactivada |
| Aprobaciones | Cola, approve/reject con versión y auditoría | Core | Requiere segregación organizativa definida por el cliente |
| Agentes | Definiciones, tools limitadas, ejecución y activación aprobada | Core | LLM generativo `none` por defecto; tools financieras mutantes prohibidas |
| Documentos/RAG | Ingesta, upload, consulta, citas, ACL y borrado | Core | TF-IDF local; OCR básico; sin AV/DLP externo |
| Wiki | Borrador, preview, edición y publicación local aprobada | Core | HTML con allowlist/CSP; no publica en CMS externo |
| Landing pages | Borrador, preview, aprobación y URL pública local | Core | Render determinista; cabecera confirma que no hubo publicación externa |
| SEO | Proyectos, análisis de HTML y historial append-only | Core | Solo HTML suministrado; no crawler, fetch, monitorización ni publicación |
| Tareas programadas | CRUD y activación aprobada de `automation_sweep` | Core | Único tipo certificado; intervalo entre 60 s y 30 días |
| Automatizaciones | Sweep, workflows, outbox e idempotencia | Core/parcial | El trigger local existe; Activepieces requiere `full` y certificación |
| Importación | JSON/CSV/XLSX para entidades admitidas con idempotencia | Core | Validar plantilla y realizar dry-run/UAT con datos del cliente |
| Ciclo de vida | Estado, exportación, borrado diferido y legal hold | Core | Política legal/retención debe parametrizarse y aprobarse por cliente |
| Email | Generación de mensajes en spool local por instalación | Core | No entrega: `accepted=false`, `queued_for_manual_delivery` |
| Observabilidad | Live/health/ready/metrics, logs JSON y correlación | Core | Sin Prometheus/SIEM/pager externo configurado |
| Chatwoot | Webhook HMAC, respuesta/handoff | Full | Desactivado en core; vendor no certificado para promoción |
| FlowWink | Frontend vendor/orquestación incluida por pin | Full | No forma parte del core candidato; certificación runtime pendiente |
| Activepieces | Webhook/trigger y vendor por digest | Full | Licencia/legal y runtime final pendientes |
| PrestaShop | Consulta/sync/historial | Opcional/full | Requiere egress y credenciales; no necesario para core |
| GoHighLevel | Creación de lead externa | Opcional/full | Requiere egress y credenciales; no necesario para core |

## Flujos críticos

### Presupuesto a pedido

1. El operador crea un presupuesto con `Idempotency-Key`.
2. El backend obtiene catálogo/cliente dentro de la instalación y recalcula importes con `Decimal`.
3. El resultado permanece como presupuesto hasta confirmación explícita.
4. La confirmación idempotente crea el pedido; un retry con la misma clave no duplica el efecto.

### Factura

1. El sistema genera o conserva un borrador.
2. El operador solicita aprobación.
3. Un administrador aprueba o rechaza con control de versión.
4. Una factura aprobada sigue sin constituir emisión fiscal ni envío a la autoridad tributaria.

`ENABLE_AUTOMATIC_INVOICE_ISSUANCE` debe permanecer `false`. La integración fiscal exige un proyecto y certificación independientes.

### Contenido público

Wiki y landing solo exponen la versión aprobada/publicada en rutas locales `/public/...`. Ediciones posteriores no sustituyen silenciosamente esa versión. No existe publicación externa automática certificada.

### SEO

El analizador procesa como máximo el HTML que recibe, extrae señales deterministas (title, meta, H1, canonical, robots, OpenGraph, schema, alt y enlaces) y registra el historial en auditoría. No navega Internet, no rastrea un dominio y no aplica cambios en una web.

## Criterio de aceptación por módulo

Para declarar un módulo apto en un cliente se exige: permiso positivo y negativo por rol; aislamiento A/B; retry idempotente; conflicto de versión; caso vacío; degradación de dependencia; evidencia Portal+API; y resultado persistente tras restart. La suite hermética existente es una base, pero el recorrido sobre la candidata final permanece `PENDING`.
