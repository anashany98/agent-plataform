> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# 05 - Revisión de arquitectura

## Veredicto arquitectónico

El patrón pretendido es **MULTI-INSTANCE SINGLE-TENANT**, pero solo está **PARTIALLY VERIFIED**. Compose puede aislar nombres, redes, DB, Redis, volúmenes y secretos mediante `-p agent-<cliente>` y `.env.<cliente>`. No están verificadas la eliminación segura, restauración, actualización independiente ni ausencia de acceso cruzado bajo error de configuración. La instalación auditada ni siquiera sigue la convención de scripts.

## Arquitectura actual

```mermaid
flowchart LR
  U["Cliente / operador"] -->|HTTP :9000 declarado| PX["Nginx reverse proxy\nBROKEN"]
  PX --> PO["Portal React"]
  PX --> BR["Bridge API"]
  PX --> CW["Chatwoot"]
  PX --> FW["FlowWink SPA"]
  PX --> AP["Activepieces"]
  BR --> BDB[("Bridge PostgreSQL + pgvector")]
  BR -.-> BRD[("Bridge Redis")]
  CW --> CDB[("Chatwoot PostgreSQL")]
  CW --> CR[("Chatwoot Redis")]
  AP --> ADB[("Activepieces PostgreSQL")]
  AP --> AR[("Activepieces Redis/cache")]
  BR -.-x PS["PrestaShop"]
  BR -.-x GHL["GHL"]
  BR -.-x LLM["Ollama / LLM cloud"]
  FW -.-x SB["Supabase externo"]
```

Las líneas con `x` están bloqueadas por ausencia de credenciales y/o ruta por defecto.

## Flujo conversacional actual

```mermaid
sequenceDiagram
  participant C as Cliente
  participant W as Chatwoot
  participant B as Bridge
  participant D as DB Bridge
  participant P as PrestaShop
  C->>W: mensaje
  W-->>B: webhook HMAC (no probado e2e)
  B->>P: búsqueda si parece producto
  P--xB: bloqueada
  B->>D: busca catálogo local, incluido demo
  D-->>B: producto/precio/stock local
  B-->>W: respuesta o presupuesto
  C->>W: texto con "acepto"/"confirmar"
  B->>D: pedido confirmado + reserva + borrador
  Note over B,D: "no acepto" también coincide
```

## Flujo comercial y datos

```mermaid
flowchart TD
  Q["Necesidad"] --> H["Heurística, no agente/tool calling"]
  H --> S["Search local sin filtro source"]
  S --> QT["Presupuesto local"]
  QT --> CF{"Substring aceptar/confirmar"}
  CF -->|sí| O["Pedido confirmado local"]
  O --> R["Reserva local sin expiración"]
  O --> I["Borrador + aprobación"]
  QT -.-> G["GHL upsert/oportunidad"]
  G -.-> T["Chatwoot status open, sin asignación"]
```

## Despliegue por cliente pretendido

```mermaid
flowchart TB
  SRC["Workspace y código compartidos"] --> C1["Compose project agent-cliente-a"]
  SRC --> C2["Compose project agent-cliente-b"]
  C1 --> V1["Volúmenes/redes/secretos A"]
  C2 --> V2["Volúmenes/redes/secretos B"]
  GIT["Checkout Git global"] --> SRC
  Note["Actualizar un cliente cambia el checkout compartido"] --> GIT
```

## Responsabilidades y duplicación

- Bridge concentra autenticación, negocio, orquestación, integraciones, RAG, telemetría y configuración de agentes: demasiadas razones de cambio.
- PrestaShop y Bridge compiten por producto/precio/stock/pedido.
- FlowWink, registro en memoria de Bridge y Activepieces solapan configuración/ejecución de agentes y workflows sin integración real.
- Chatwoot y Customer local duplican identidad/contacto; GHL añade una tercera copia.
- Proxy y Bridge son puntos únicos de fallo; no hay HA ni failover.

## Arquitectura recomendada para piloto

```mermaid
flowchart LR
  U["Cliente"] --> GW["Gateway TLS con health correcto"]
  GW --> CW["Chatwoot"]
  GW --> PO["Portal mínimo"]
  CW -->|webhook firmado + delivery id| BR["Bridge modular"]
  PO --> BR
  BR --> DB[("PostgreSQL por cliente")]
  BR --> PS["PrestaShop: catálogo, precio, stock y pedido"]
  BR --> G["GHL: contacto y oportunidad"]
  BR --> L["LLM opcional; herramientas allowlist"]
  BR --> O["Métricas/logs/alertas"]
  BR --> BK["Backup verificado"]
```

Para el MVP: retirar FlowWink y Activepieces del camino crítico; usar una máquina de estados en Bridge; mantener Chatwoot solo como canal; hacer de PrestaShop la autoridad transaccional; persistir idempotencia/outbox; añadir egress controlado por allowlist.

## Evaluación multi-instance

| Control | Estado | Evidencia/fallo |
|---|---|---|
| Proyecto Compose por cliente | PARTIALLY VERIFIED | Scripts lo generan; instancia actual usa nombre manual |
| DB/Redis/redes/volúmenes independientes | VERIFIED | Nombres por proyecto y recursos separados observados |
| Secretos/config independientes | IMPLEMENTED BUT NOT TESTED | `.env.<cliente>`; plaintext y sin gestor |
| Backup independiente | IMPLEMENTED BUT NOT TESTED | Script parametrizado; no restaurado |
| Actualización independiente | BROKEN | Checkout Git global y workspace sin `.git` |
| Eliminación segura | NOT IMPLEMENTED | No script, borrado criptográfico ni evidencia |
| Ausencia de acceso cruzado | PARTIALLY VERIFIED | Redes separadas; no prueba negativa ni guardas en tablas |

## Archivos revisados

Compose/overrides, proxy, modelos, rutas, servicios, scripts de ciclo de vida y documentos de arquitectura/decisiones.

## Defectos, riesgos y pendiente

- Arquitectura distribuida demasiado grande para un MVP no integrado.
- No hay egress controlado: hay aislamiento, pero también inutilidad funcional.
- Actualización y recuperación no cumplen independencia real.
- Pendiente: prueba de aislamiento con dos instalaciones ficticias, destrucción segura y sandbox e2e.
