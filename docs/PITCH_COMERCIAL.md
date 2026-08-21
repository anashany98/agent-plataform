# Pitch comercial de venta — Bridge B2B Commerce Ops

**Fecha:** 2026-08-15.
**Uso:** documento de venta para el equipo comercial. Todo claim técnico
tiene una evidencia verificable citada; lo que NO se puede afirmar todavía
está marcado explícitamente (sección 3.2) — el comprador puede y debe
reproducirlo.

> **Qué es Bridge:** operaciones de comercio B2B sobre tu catálogo (PrestaShop
> u otro): presupuestos, pedidos, facturas con aprobaciones, automatizaciones,
> contenido/SEO y un portal con roles — con **evidencia de producción**
> (backup con RPO/RTO medidos, matriz de roles verificada en vivo, corpus de
> 400+ tests herméticos) que ninguna tool de SaaS genérica entrega.

---

## 1. El producto en 60 segundos

| Dimensión | Respuesta |
|---|---|
| **Para quién** | Distribuidores B2B, fabricantes y marketplaces que venden catálogos grandes y necesitan presupuesto → pedido → factura con aprobaciones y auditoría |
| **Modelo de entrega** | **Instancia gestionada por cliente** (una instalación aislada por cliente, tooling `provision-client.sh/ps1` + `rollback-client` + `update-client` ya existente) |
| **Datos que ya corre en producción real** | Catálogo PrestaShop de **41.652 SKUs** sincronizado en vivo (btopdigital.es), búsqueda léxica + semántica, ciclo chat→presupuesto→CONFIRMAR→pedido→aprobación operado en conversaciones reales |
| **Diferenciador** | No es un CRM con módulos: es un sistema con **evidencia** (RPO/RTO medidos, RBAC 63/63 en vivo, 413 tests, quality gates) — el documento de venta se puede auditar |
| **Honestidad** | NO se vende como SaaS compartido ni como producción certificada global; se vende como **piloto de producción por instancia** con un plan de certificación explícito (sección 3.2) |

---

## 2. Ficha de producto por segmento

### 2.1 Distribuidor B2B (perfil actual: btopdigital.es)

| | |
|---|---|
| **Dolor** | Vende por PrestaShop sin presupuestos formales, sin aprobaciones, sin auditoría; el comercial pierde seguimiento del carrito abandonado; el stock lo decide el Excel |
| **Solución Bridge** | Catálogo real sincronizado (sync incremental diario), presupuesto → CONFIRMAR → pedido → factura borrador con **flujo de aprobación de dos pasos**, recordatorios de caducidad, **dunning de cobro**, alertas de stock bajo, follow-up de carritos abandonados, portal por rol |
| **Evidencia clave** | Sync de 41.652 SKUs (326 s, coverage 100 % en 209 páginas); ciclo completo chat→pedido→aprobación en conversación real; RBAC 63/63 |
| **Precio orientativo** | Starter €149/mes · Pro €499/mes (o setup único €2.500 + €299/mes) |
| **Gancho de cierre** | «Tu catálogo ya está sincronizado y paginado; el piloto se monta en una semana» |

### 2.2 Fabricante (venta directa + red de distribuidores)

| | |
|---|---|
| **Dolor** | Precios y stocks distintos por cliente, sin control sobre lo que confirma su red; sin facturación homogénea; sin trazabilidad de la venta |
| **Solución Bridge** | Pricelists con descuento por cliente, presupuestos con token de confirmación y caducidad, **reserva de stock con verificación en vivo contra la autoridad**, aprobación central de facturas, export/erase con retención (cumplimiento), SEO propio (sitemap/RSS/llms.txt/knowledge-index) |
| **Evidencia clave** | P0-004 (reserva atómica bajo concurrencia), P0-003 (pricing con 20 contratos PrestaShop: variantes, IVA, envío), P1-011 (RAG con ACL deny-by-default: la documentación técnica no se filtra a terceros) |
| **Precio orientativo** | Pro €499/mes · Enterprise €1.900/mes + setup |
| **Gancho de cierre** | «Tu red confirma con la misma tarifa y stock que tú; el sistema lo audita todo» |

### 2.3 Marketplace (multi-vendedor incipiente o catálogo agregado)

| | |
|---|---|
| **Dolor** | Agrega catálogos de varios proveedores sin control de procedencia (demo/import/prestashop mezclados); sin confianza en la disponibilidad; sin diferenciación de contenido |
| **Solución Bridge** | **Catálogo con origen y fail-closed**: cada SKU declara `source` (prestashop/import/local) y los proveedores no confiables jamás aparecen en venta; verificación de stock remoto antes de confirmar (409 honesto si falta); RAG local con ACL para documentación por vendedor; generadores SEO deterministas |
| **Evidencia clave** | P0-001 (demo jamás visible en rutas cliente), P0-006 (aislamiento cross-tenant), P0-003 opción C (stock verificado en vivo antes de confirmar), 51.570 embeddings con búsqueda semántica real |
| **Precio orientativo** | Enterprise €1.900/mes + setup (aislamiento físico opcional) |
| **Gancho de cierre** | «Puedes probar que un vendedor no ve ni cita los datos de otro — hay un test que lo demuestra» |

---

## 3. Diferenciadores con evidencia

### 3.1 Claims que SÍ se pueden afirmar (con dónde verificarlo)

| Claim | Evidencia | Dónde se verifica |
|---|---|---|
| **RPO/RTO medidos, no prometidos** | Ensayo integral sobre PostgreSQL real del stack candidato: backup cifrado AES-256-CBC+HMAC+SHA256SUMS en **10,9 s**; restore a destino vacío con **RTO 25,2 s**; rollback vía safety backup **25,1 s**; punto de recuperación probado (marcador post-backup perdido en restore, recuperado en rollback) | `docs/PRODUCTION_READINESS.md` §Evidencia SS-05; artefactos en `infrastructure/backups/candidate-0815/`; reproducible con `scripts/backup-restore-integral.py` |
| **RBAC verificado en vivo, no por diseño** | **63/63 checks** (7 roles × 9 módulos) sobre el stack candidato en 5,27 s: `viewer` recibe 403 en clientes/ventas/wiki/tareas/usuarios; tareas y usuarios solo admins; dashboard role-aware | `docs/PRODUCTION_READINESS.md` §Evidencia SS-04; driver `scripts/e2e_role_matrix.py` |
| **Catálogo real a escala** | **41.652 SKUs PrestaShop** sincronizados y paginados en vivo (coverage 100 % en 209 páginas); búsqueda semántica con 51.570/51.570 embeddings | `docs/TEST_EVIDENCE.md`; `GET /catalog/products` sobre el stack candidato |
| **Ciclo comercial completo operado** | Chat → presupuesto (24,12 €) → CONFIRMAR con token → pedido → aprobación → factura borrador → PDF, en conversación real de Chatwoot | `docs/TEST_EVIDENCE.md`; transcriptos `.freebuff/*_cycle_evidence.json` |
| **Automatizaciones con aprobación y auditoría** | Catálogo de 4 tipos (sweep, sync PrestaShop diario, stock bajo, abandono de carrito) + webhook triggers con HMAC, todos con flujo request-activation → aprobación y evento en AuditLog | `tests/regression/test_automation_triggers.py` (6 evals API); `SCHEDULED_TASK_TYPES` |
| **Aislamiento entre clientes probado** | 24 modelos tenant-owned con enforcement ORM deny-by-default, FKs compuestas y matriz cross-tenant (dos clientes no enumeran datos ajenos) | `tests/regression/test_p0_model_tenant_isolation.py` |
| **Calidad auditable** | Corpus de **413 tests passed / 11 skipped**, quality gates D-030 (deuda legacy por debajo del baseline), zona limpia 0 issues, migraciones no destructivas (P0-005) | `scripts/quality_gates.py`; `docs/TEST_REPORT.md` |
| **Continuidad de operación por cliente** | Scripts `provision-client`, `rollback-client`, `update-client` (sh/ps1) y `CLIENT_ONBOARDING.md` | `scripts/` |

### 3.2 Lo que NO se puede afirmar todavía (y cómo se cierra en la propuesta)

El comprador merece saber el estado real de madurez (SS-02/03/06/07 de
`docs/PRODUCTION_READINESS.md` siguen abiertos, todos de release con
dependencias externas):

| Pendiente | Impacto en venta | Cierre en el plan del cliente |
|---|---|---|
| **Imágenes finales con scan + SBOM (SS-02)** | No vender "SBOM certificado" hoy. El pipeline CI con Trivy y SBOM existe (`production-gates.yml`, T-025) pero no se ha ejecutado en un remote | Se entrega como fase 0 del piloto: build final, scan Trivy y SBOM CycloneDX/SPDX por imagen, firmados |
| **TLS/DNS/secretos reales (SS-03)** | El stack corre con TLS de desarrollo/proxy; DNS y secretos dependen del cliente | Fase 1: certificado leaf con SAN del dominio del cliente, DNS, rotación de secretos, preflight release |
| **Soak/rendimiento final (SS-06)** | No vender SLA de rendimiento sin medir | Fase 2: carga acotada + degradación Redis/DB con el catálogo del cliente |
| **Alertas externas (SS-07)** | Las alertas hoy son internas | Fase 2: receptor (email/Slack/webhook) + prueba de alerta |
| **Bloqueos externos** | Legal hold B-008 y sandbox GHL B-004 son dependencias fuera del equipo | Se declaran en la propuesta como supuestos/riesgos |

**Regla de venta:** nunca prometer SBOM, SLA de rendimiento ni "producción
certificada" como estado actual; prometer **un plan con fases, fechas y
criterios de salida medibles** para llegar ahí — con la ventaja de que RPO/RTO,
RBAC, catálogo y ciclo comercial YA están medidos.

---

## 4. Plantilla de propuesta por instancia gestionada

> Copia este bloque a `propuestas/{{CLIENTE}}.md` y rellena los `{{...}}`.
> Los corchetes `[ ]` son casillas de verificación de la fase 0/1 (entregables
> que se validan con el cliente antes de pasar a operación).

```markdown
# Propuesta de Bridge B2B Commerce Ops — {{CLIENTE}}

**Fecha:** {{fecha}} · **Versión:** 0.1 (borrador para revisión)
**Contacto comercial:** {{nombre}} · **Contacto técnico:** {{nombre}}

## 1. Contexto y objetivo
{{2-3 frases: qué vende el cliente, qué le duele hoy (presupuestos
manuales / stock descontrolado / sin auditoría), qué espera lograr}}

## 2. Alcance (módulos contratados)
- [ ] **Catálogo**: sync PrestaShop incremental diario + paginación +
      búsqueda léxica/semántica (`{{tamaño_catálogo}}` SKUs)
- [ ] **Comercio**: presupuestos → CONFIRMAR → pedido → factura borrador +
      aprobaciones en 2 pasos
- [ ] **Portal por rol**: catálogo, clientes, ventas, contenido, tareas,
      usuarios (7 roles, matriz verificable)
- [ ] **Automatizaciones** (elegir N de 4): [ ] sweep caducidad/dunning
      [ ] sync diario [ ] stock bajo [ ] abandono de carrito
- [ ] **Email**: [ ] spool manual (sin coste SMTP) [ ] SMTP real
      ({{proveedor}})
- [ ] **Contenido/SEO**: wiki + sitemap.xml, blog-rss, llms.txt,
      knowledge-index
- [ ] **RAG local** ({{MB}} de documentos, con ACL deny-by-default)
- [ ] **Integraciones** (elegir): [ ] PrestaShop [ ] GHL [ ] Chatwoot
      [ ] Activepieces — {{cuáles}}
- [ ] **Fuera de alcance** (explícito): {{cosas que el cliente pidió y NO
      incluye esta propuesta}}

## 3. Modelo de entrega: instancia gestionada
- Una instalación aislada por cliente (red y volúmenes propios) en
  {{infraestructura: cloud del cliente / hosting del proveedor}}
- Provisionado con `provision-client.sh/ps1`; actualizaciones con
  `update-client`; baja con `rollback-client`
- Datos del cliente en su propia BD PostgreSQL; backups cifrados
  (AES-256-CBC + HMAC + checksums) con **RPO {{x}} h** y **RTO {{y}} min**
  medidos en la fase 1 (objetivo: los 25 s del ensayo de referencia)

## 4. Fases, entregables y criterios de salida
| Fase | Contenido | Entregable al cliente | Criterio de salida |
|---|---|---|---|
| 0. Preparación | Build final + scan Trivy + SBOM + secrets | SBOM CycloneDX/SPDX firmado; informe de scan | Cero críticos; SBOM firmado |
| 1. Puesta en producción | TLS/DNS reales, DNS, rotación de secretos, preflight | URL https://{{dominio}}; preflight release PASS | Preflight PASS documentado |
| 2. Validación | Soak + degradación Redis/DB con catálogo real; E2E por rol | Informe de rendimiento; matriz E2E | Carga objetivo {{req/s}} sin error; RPO/RTO medidos |
| 3. Operación | Runbook, alertas externas, soporte | Runbook + alerta probada | Alerta disparada por fault injection |
| 4. Acompañamiento | Formación de {{N}} usuarios, 30 días | Manual del usuario + UAT firmado | UAT con {{N}} usuarios operando |

## 5. Operación y soporte
- Horario de soporte: {{L-V 9-18 / 24x7}} · canal: {{email/Slack}}
- Supervisión: logs JSON + métricas + alertas {{internas/externas}}
- Actualizaciones: ventana {{domingo 04:00}} con `update-client` y rollback
  automático si falla la salud
- Copias: {{diaria retención N días + semanal + mensual}} — RPO/RTO medidos
  en la fase 2 y revisados semestralmente

## 6. Condiciones económicas
| Concepto | Importe |
|---|---|
| Setup / implantación (fases 0–1) | €{{x}} (único) |
| Mensualidad (instancia gestionada, tier {{tier}}) | €{{x}}/mes |
| Correo SMTP real / integraciones extra | +€{{x}}/mes |
| Soporte ampliado / SLA | +€{{x}}/mes |
| **Total recurrente** | **€{{x}}/mes** |

Precios sin IVA. {{Condiciones de pago: 50 % setup + mensualidad}}.

## 7. Riesgos y supuestos (honestidad contractual)
- [ ] Legal hold / borrado de datos: {{pendiente legal B-008}} — supuesto:
      {{...}}
- [ ] Sandbox GHL {{pendiente}} — supuesto: {{...}}
- [ ] Credenciales reales (PrestaShop, SMTP, DNS) las aporta el cliente
- [ ] El catálogo {{tamaño}} se sincroniza con {{frecuencia}}
- [ ] {{otros riesgos específicos del cliente}}

## 8. Anexo: evidencia verificable (para el dueño técnico del cliente)
- RPO/RTO: `docs/PRODUCTION_READINESS.md` §Evidencia SS-05 (reproducible)
- RBAC: `docs/PRODUCTION_READINESS.md` §Evidencia SS-04 + `scripts/e2e_role_matrix.py`
- Catálogo/paginación: `docs/TEST_EVIDENCE.md`
- Aislamiento entre clientes: `tests/regression/test_p0_model_tenant_isolation.py`
- Calidad: `scripts/quality_gates.py` (413 tests, D-030)

## 9. Firma
| | Nombre | Fecha |
|---|---|---|
| Cliente | {{}} | |
| Proveedor | {{}} | |
```

---

## 5. Guion de llamada (30 min)

1. **(0–5 min)** «Tu catálogo ya es digital; el problema es lo que pasa
   DESPUÉS de la búsqueda: presupuesto, aprobación, cobro, seguimiento.»
   Demo del ciclo chat→presupuesto→CONFIRMAR→pedido→aprobación.
2. **(5–15 min)** Diferenciador: «No te pido confianza, te doy evidencia» —
   tabla 3.1: RPO/RTO medidos, RBAC verificado en vivo, 413 tests, catálogo
   41.652 SKUs paginado.
3. **(15–25 min)** Alcance por segmento (sección 2) + fases 0–3 con fechas.
4. **(25–30 min)** Cierre: setup + piloto en una semana (catálogo real ya
   sincronizado), propuesta en 48 h con la plantilla de la sección 4.

**Máxima de venta:** «El contrato incluye las pruebas; tú puedes ejecutarlas.»
