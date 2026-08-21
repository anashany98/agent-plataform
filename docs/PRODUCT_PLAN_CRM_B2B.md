# Plan de producto — Bridge como CRM B2B por instancia gestionada

**Fecha:** 2026-08-16 · **Estado:** propuesta de producto (plan de módulos, precios y hoja de ruta)
**Base técnica verificable:** `docs/BUSINESS_MODULES.md` (inventario real), `docs/PITCH_COMERCIAL.md` (ficha por segmento), `docs/ARCHITECTURE_SAAS_MULTI_TENANT.md` (evolución multi-tenant), `docs/PRODUCTION_READINESS.md` (evidencia SS-04/SS-05).
**Regla de venta:** misma que el pitch §3.2 — se vende un plan con fases y criterios medibles, nunca "producción certificada" ni "SaaS compartido" como estado actual.

---

## 1. Posicionamiento

**Bridge deja de venderse solo como "operaciones de comercio B2B" y pasa a venderse como "CRM B2B de ventas + back-office comercial" por instancia gestionada.**

La tesis de producto: la mayoría de los CRM genéricos obligan al comercial a *teclear* el pipeline; Bridge lo *genera* desde el ciclo de venta real. Cada presupuesto del chat es una oportunidad, cada `CONFIRMAR` es un pedido, cada pedido es una factura con aprobación. El CRM deja de ser una tabla que hay que mantener y pasa a ser el **registro auditado de lo que ya está pasando** en la tienda y en el chat.

| Dimensión | Definición |
|---|---|
| **Qué se vende** | Instancia gestionada por cliente (aislada, con tooling `provision-client`/`rollback-client`/`update-client` ya existente) que cubre el ciclo completo: **captura → seguimiento → venta → facturación → cobro → contenido** |
| **Para quién** | Distribuidores B2B, fabricantes con red de distribuidores, marketplaces con catálogo agregado |
| **Diferenciador real** | Pipeline alimentado por transacciones reales + evidencia medible (RPO/RTO, RBAC 63/63, catálogo de 41.652 SKUs, 450+ tests) que ningún CRM genérico puede mostrar |
| **Límite honesto** | No es HubSpot/Salesforce: el foco es venta B2B de producto, no marketing masivo ni servicios. Lo que falta se planifica aquí |

---

## 2. Estado actual como base (M0) — qué ya ES CRM

Del inventario real (`BUSINESS_MODULES.md`) y la evidencia de la sesión:

| Capacidad CRM | Estado actual | Evidencia |
|---|---|---|
| Contactos/leads | Tabla `leads` (nombre, email, teléfono, empresa, fuente, estado), deduplicada por email e idempotente por `external_reference` | `models.py` + `LocalCRMProvider` |
| Oportunidades | Tabla `opportunities` (pipeline, etapa, valor, moneda, estado, notas) creadas idempotentemente desde el ciclo de venta | `models.py` + tests T-022 |
| Clientes B2B | `customers` con empresa, teléfono, **pricelist con descuento** y exención de IVA | `models.py` |
| Ciclo de venta | chat → lead → presupuesto → `CONFIRMAR` → pedido → factura PDF por email → aprobación | Ciclo operado en conversación real de Chatwoot |
| Seguimiento | Recordatorios de presupuesto, dunning, follow-up de carrito abandonado (automatizaciones con email real) | `SCHEDULED_TASK_TYPES` + SMTP/spool |
| Portal por rol | Clientes, Ventas y facturación, Aprobaciones, Usuarios y permisos; RBAC 63/63 verificado | `scripts/e2e_role_matrix.py` |
| CRM externo | `CRMProvider` dual: GoHighLevel si está configurado, local por defecto | `crm_provider.py` |
| Confianza | Backup/RPO/RTO medidos sobre PostgreSQL real; auditoría completa; aislamiento entre instalaciones probado | SS-04/SS-05 |

**Lectura:** la columna vertebral de un CRM B2B ya existe y está operada por transacciones reales. Lo que falta es la capa de *trabajo comercial* (pipeline visual, actividades, reporting) y la capa de *escala* (SSO, multi-tenant, billing).

---

## 3. Módulos a añadir (carencias vs un CRM completo)

Priorizados en tres bloques. Cada módulo indica qué reutiliza del código existente — el objetivo es que la hoja de ruta sea incremental, no un rewrite.

### 3.1 Bloque P1 — v1.0 del CRM (núcleo comercial)

| Módulo | Qué aporta | Reutiliza | Esfuerzo |
|---|---|---|---|
| **P1-a. Kanban de pipeline configurable** | Etapas por defecto (nuevo → calificado → presupuesto → negociación → ganado/perdido), arrastre entre etapas, cambio de etapa auditado, filtros por comercial/valor/fecha | `opportunities.pipeline/stage` ya existen; RBAC y AuditLog existentes | M (2–3 semanas) |
| **P1-b. Actividades de comercial** | Llamadas, reuniones, seguimientos con vencimiento (due date) y responsable; recordatorios por email vía outbox; notas por actividad | `opportunities.notes` (JSON), outbox durable, email SMTP/spool, `automation_sweep` para recordatorios | M (2–3 semanas) |
| **P1-c. Reporting de ventas** | Funnel por etapa (conversión), ticket medio por cliente, aging de presupuestos, ventas por comercial — en el dashboard por rol | Dashboard role-aware existente; datos ya en `leads/opportunities/orders/invoices` | M (2–3 semanas) |
| **P1-d. Asignación de comerciales** | Ownership de lead/oportunidad por usuario, transferencia con auditoría, cola de leads sin asignar | Usuarios+roles existentes; `pending_approvals` como patrón | S (1–2 semanas) |
| **P1-e. Lead scoring básico** | Score por fuente, valor del presupuesto, actividad reciente y carrito abandonado; visible en la ficha | Automatizaciones existentes (sweep + webhook) | S (1 semana) |

**Criterio de salida P1:** un comercial opera el ciclo completo desde el kanban (captura → seguimiento → cierre → factura) sin salir del portal, con cada cambio auditado; driver E2E por rol como `e2e_role_matrix.py`.

### 3.2 Bloque P2 — crecimiento (multi-usuario y comunicaciones)

| Módulo | Qué aporta | Reutiliza | Esfuerzo |
|---|---|---|---|
| **P2-a. SSO (OIDC) + MFA** | Login con proveedor corporativo y segundo factor; hoy es JWT en `sessionStorage` sin MFA/SSO (límite declarado en `BUSINESS_MODULES.md`) | Capa de auth existente (`token_version`, revocación) | M–L (3–4 semanas) |
| **P2-b. Campañas de email por segmento** | Envíos transaccionales segmentados (clientes por pricelist, carritos abandonados, leads por etapa) con plantillas aprobadas y auditoría | SMTP/spool, automatizaciones, RBAC de aprobación | M (2–3 semanas) |
| **P2-c. API pública + webhooks salientes** | Claves de API por instalación con permisos acotados, eventos salientes firmados (lead_created, order_confirmed, invoice_approved) | Idempotencia, HMAC de Chatwoot, outbox | M (2–3 semanas) |
| **P2-d. Calendario de vendedores** | Vista de agenda por comercial, solapamiento de reuniones, recordatorios integrados con P1-b | Actividades P1-b | M (2 semanas) |
| **P2-e. Importación/exportación CRM completa** | CSV de leads/oportunidades con mapeo, plantilla y dry-run (mismo patrón que la importación de catálogo) | Importador genérico JSON/CSV/XLSX con idempotencia | S (1 semana) |

### 3.3 Bloque P3 — enterprise (escala SaaS)

| Módulo | Qué aporta | Reutiliza | Esfuerzo |
|---|---|---|---|
| **P3-a. Multi-tenant con RLS** | `tenant_id` sobre los modelos owned + row-level security en PostgreSQL compartido, siguiendo `docs/ARCHITECTURE_SAAS_MULTI_TENANT.md` (esquema ya diseñado) | Modelos tenant-owned (24) y matriz de aislamiento existentes | L (8–12 semanas) |
| **P3-b. Billing integrado** | Suscripción por tier con límites (usuarios, SKUs, automatizaciones), facturación recurrente y suspensión controlada | Pricelists, facturas, ciclo de vida (legal hold) | L (6–8 semanas) |
| **P3-c. SCIM + gobernanza de acceso** | Aprovisionamiento/deprovisionamiento automático, sesiones y auditoría de administradores | RBAC existente | M (3–4 semanas) |
| **P3-d. Integraciones ERP/fiscal** | Facturación fiscal certificada (requiere proyecto independiente: `ENABLE_AUTOMATIC_INVOICE_ISSUANCE` permanece `false`), transportistas, pasarelas de pago | Facturas+aprobaciones, webhooks salientes P2-c | L (proyecto propio) |
| **P3-e. BI embebido / exportación** | Datamart de ventas, exportación a Power BI/Looker con gobernanza de datos | Reporting P1-c | M (3 semanas) |

---

## 4. Precios por segmento (modelo CRM por instancia gestionada)

Se mantienen los rangos del pitch (`PITCH_COMERCIAL.md` §2) y se estructuran como **planes CRM** con lo añadido, sin inventar precios nuevos: la tabla solo enmarca qué módulos van en cada tier.

### 4.1 Planes transversales

| Tier | Precio/mes (instancia gestionada) | Setup | Incluye (CRM) |
|---|---|---|---|
| **Starter** | €149 | €0–€1.000 (migración) | Catálogo + chat comercial, leads/oportunidades, presupuesto→pedido→factura, kanban básico, 3 usuarios, email transaccional |
| **Pro** | €499 | €2.500 | Todo Starter + pipeline configurable (P1-a), actividades y recordatorios (P1-b), reporting (P1-c), asignación (P1-d), scoring (P1-e), automatizaciones completas (dunning, abandono de carrito), 15 usuarios |
| **Enterprise** | €1.900 | €5.000–€10.000 | Todo Pro + SSO/MFA (P2-a), campañas segmentadas (P2-b), API pública (P2-c), calendario (P2-d), soporte prioritario con RTO operativo, aislamiento reforzado |
| **Add-ons** | Variable | — | Multi-tenant con billing (P3-a/b), SCIM (P3-c), integración ERP/fiscal certificada (P3-d), BI embebido (P3-e) |

### 4.2 Encuadre por segmento (del pitch §2)

| Segmento | Tier recomendado | Gancho CRM específico |
|---|---|---|
| **Distribuidor B2B** | Starter→Pro | «El pipeline se llena solo con cada presupuesto del chat; el comercial deja de teclear» |
| **Fabricante con red** | Pro→Enterprise | «Tu red confirma con tu tarifa y stock; el CRM audita cada venta y su aprobación» |
| **Marketplace** | Enterprise + add-ons | «Cada vendedor ve solo su pipeline; aislamiento demostrable por test» |

**Reglas de precio:** por instancia gestionada (no por usuario), alojamiento+backup+soporte incluidos; los add-ons enterprise se cotizan por proyecto; la integración fiscal y el SaaS compartido se venden siempre como fase con certificación, nunca como estado actual.

---

## 5. Hoja de ruta desde el estado actual

Fases con alcance, esfuerzo, dependencias y criterio de salida medible. El M0 ya está operado (evidencia de la sesión); M1 es la v1.0 vendible como CRM.

### M0 — Base (entregado, 2026-08)
- **Qué:** lo que ya corre y se valida en vivo: catálogo 41.652 SKUs, chat comercial con persona/memoria, ciclo presupuesto→CONFIRMAR→pedido→factura, CRM local (leads/oportunidades/clientes), RBAC 63/63, automatizaciones, backup RPO/RTO, quality gates con juez LLM.
- **Criterio:** corpus 450+ tests, gates PASS, validación en vivo del candidato.

### M1 — v1.0 del CRM (3–4 meses)
- **Alcance:** P1-a kanban configurable, P1-b actividades, P1-c reporting, P1-d asignación, P1-e scoring; revisión de UX del módulo Clientes/Ventas.
- **Dependencias:** ninguna externa (todo sobre modelos existentes).
- **Criterio de salida:** un comercial opera el ciclo completo desde el kanban sin salir del portal; driver E2E por rol verde; **esto es lo que se vende en el pitch como Pro**.
- **Riesgo:** sobre-ingeniería del kanban (acotar a drag&drop + etapas configurables + auditoría).

### M2 — Crecimiento (meses 4–8)
- **Alcance:** P2-a SSO/MFA, P2-b campañas segmentadas, P2-c API pública, P2-d calendario, P2-e importación/exportación CRM.
- **Dependencias:** proveedor OIDC del cliente (fase de piloto); alta de SMTP transaccional.
- **Criterio:** piloto con 2 clientes reales; SSO y campañas operados en producción de piloto; API pública con 1 integración de terceros.
- **Riesgo:** MFA/SSO añade superficie de seguridad — reusar el modelo de revocación por `token_version` y auditarlo.

### M3 — Enterprise (meses 8–14)
- **Alcance:** P3-a multi-tenant con RLS, P3-b billing, P3-c SCIM, P3-e BI; P3-d (ERP/fiscal) como proyecto independiente con certificación.
- **Dependencias:** decisión de SaaS compartido vs instancias (recomendado: instancias gestionadas + multi-tenant opcional según cliente, ver `ARCHITECTURE_SAAS_MULTI_TENANT.md`).
- **Criterio:** onboarding de tenant self-service con RLS probado (matriz cross-tenant existente extendida); billing con ciclo de vida completo; certificación fiscal fuera del alcance del producto base.
- **Riesgo:** el multi-tenant toca los 24 modelos owned — la matriz de aislamiento existente es la red de seguridad; no romperla con el esquema de `tenant_id`.

---

## 6. Qué NO prometer (regla de venta)

| Pendiente (SS-02/03/06/07, bloqueos externos) | Impacto en venta |
|---|---|
| SBOM/imágenes finales sin ejecutar en remote | No vender "SBOM certificado" hoy; entregarlo como fase 0 del piloto (T-025) |
| TLS/DNS/secretos reales | Dependen del cliente; fase 1 del piloto |
| SLA de rendimiento / soak final | No vender sin medir (SS-06); fase 2 |
| Alertas externas (SS-07) | Hoy internas; fase 2 |
| Emisión fiscal automática | `ENABLE_AUTOMATIC_INVOICE_ISSUANCE=false`; integración fiscal = proyecto certificado aparte |
| Legal hold B-008 / sandbox GHL B-004 | Dependencias externas; declarar como supuestos en la propuesta |

---

## 7. Vínculos con la documentación existente

- `docs/PITCH_COMERCIAL.md` — ficha por segmento y plantilla de propuesta (este plan añade la capa CRM y la hoja de ruta).
- `docs/ARCHITECTURE_SAAS_MULTI_TENANT.md` — esquema de `tenant_id` + RLS + tiers para M3.
- `docs/BUSINESS_MODULES.md` — inventario real del que parte cada módulo nuevo.
- `docs/PRODUCTION_READINESS.md` — evidencia SS-04/SS-05 (RBAC, RPO/RTO) citable en la venta.
- `docs/CLIENT_ONBOARDING.md` y `scripts/provision-client*` — el modelo de entrega por instancia gestionada ya existe.
