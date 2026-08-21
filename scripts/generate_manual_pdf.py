"""Genera el manual PDF de recorrido de la app Bridge B2B Commerce Ops.

Contenido: qué hace hoy la app módulo a módulo, porcentaje de finalización,
módulos actuales vs futuros, recorrido de negocio y cómo venderla (pitch).
Genera ``docs/MANUAL_RECORRIDO_APP.pdf`` con reportlab.

Fuentes autoritativas: ``STATUS.md``, ``TASKS.md``, ``CHANGELOG.md``,
``docs/PITCH_COMERCIAL.md``, ``docs/PRODUCT_PLAN_CRM_B2B.md``,
``docs/BUSINESS_MODULES.md`` y ``docs/TEST_EVIDENCE.md``.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "MANUAL_RECORRIDO_APP.pdf"

NAVY = colors.HexColor("#111827")
BLUE = colors.HexColor("#1d4ed8")
LIGHT = colors.HexColor("#f3f4f6")
GREEN = colors.HexColor("#15803d")
AMBER = colors.HexColor("#92400e")
BORDER = colors.HexColor("#d7dce3")

styles = getSampleStyleSheet()

H1 = ParagraphStyle(
    "H1",
    parent=styles["Heading1"],
    fontName="Helvetica-Bold",
    fontSize=17,
    leading=21,
    textColor=NAVY,
    spaceBefore=10,
    spaceAfter=8,
)
H2 = ParagraphStyle(
    "H2",
    parent=styles["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=12.5,
    leading=16,
    textColor=BLUE,
    spaceBefore=10,
    spaceAfter=4,
)
BODY = ParagraphStyle(
    "Body",
    parent=styles["BodyText"],
    fontName="Helvetica",
    fontSize=9.5,
    leading=13,
    alignment=TA_LEFT,
    spaceAfter=5,
)
BULLET = ParagraphStyle(
    "Bullet",
    parent=BODY,
    leftIndent=10,
    bulletIndent=2,
    spaceAfter=3,
)
SMALL = ParagraphStyle(
    "Small",
    parent=BODY,
    fontSize=8,
    leading=10.5,
    textColor=colors.HexColor("#4b5563"),
)
CENTER = ParagraphStyle("Center", parent=BODY, alignment=TA_CENTER)

PILL = ParagraphStyle(
    "Pill",
    parent=BODY,
    fontSize=8,
    leading=10,
    textColor=colors.white,
)

W = 174 * mm  # ancho útil A4 con márgenes de 18 mm


class ManualTemplate(SimpleDocTemplate):
    """Plantilla con índice y cabecera/pie por página."""

    def afterFlowable(self, flowable) -> None:  # noqa: D102
        if isinstance(flowable, Paragraph):
            style = flowable.style.name
            if style == "H1":
                self.notify("TOCEntry", (0, flowable.getPlainText(), self.page))
            elif style == "H2":
                self.notify("TOCEntry", (1, flowable.getPlainText(), self.page))


def header_footer(canvas, doc) -> None:  # noqa: D103
    canvas.saveState()
    if doc.page == 1:
        canvas.restoreState()
        return
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#6b7280"))
    canvas.drawString(18 * mm, A4[1] - 12 * mm, "Bridge B2B Commerce Ops · Manual de recorrido")
    canvas.drawRightString(A4[0] - 18 * mm, A4[1] - 12 * mm, "candidate-0815 · v0.9.1")
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.4)
    canvas.line(18 * mm, A4[1] - 14 * mm, A4[0] - 18 * mm, A4[1] - 14 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(A4[0] / 2, 12 * mm, f"Página {doc.page}")
    canvas.restoreState()


def P(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(text, style)


def bullets(items: list[str]) -> list:
    return [Paragraph(f"<bullet>&bull;</bullet>{item}", BULLET) for item in items]


def table(rows: list[list], widths: list[float] | None = None, header: bool = True) -> Table:
    data = [[Paragraph(f"<b>{str(c)}</b>", SMALL) if (header and i == 0) else Paragraph(str(c), SMALL) for c in row] for i, row in enumerate(rows)]
    t = Table(data, colWidths=widths or [W / len(rows[0])] * len(rows[0]), repeatRows=1 if header else 0)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT) if header else ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    t.setStyle(TableStyle(style))
    return t


def block(title: str, color: str = "blue") -> Table:
    """Bloque de título de sección con barra de color."""
    bar = Table(
        [[Paragraph(f"<b>{title}</b>", ParagraphStyle("sec", parent=BODY, fontSize=10.5, textColor=colors.white, leading=13))]],
        colWidths=[W],
    )
    bar.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BLUE if color == "blue" else NAVY),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return bar


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = ManualTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title="Manual de recorrido — Bridge B2B Commerce Ops",
        author="Bridge Platform",
    )
    story: list = []

    # ------------------------------------------------------------------ portada
    cover = Table(
        [
            [Paragraph("BRIDGE", ParagraphStyle("c1", parent=BODY, fontSize=30, textColor=colors.white, alignment=TA_CENTER, leading=34))],
            [Paragraph("B2B Commerce Ops + CRM por instancia gestionada", ParagraphStyle("c2", parent=BODY, fontSize=13, textColor=colors.HexColor("#c7d2fe"), alignment=TA_CENTER, leading=17))],
            [Spacer(1, 40)],
            [Paragraph("Manual de recorrido de la aplicación", ParagraphStyle("c3", parent=BODY, fontSize=20, textColor=colors.white, alignment=TA_CENTER, leading=26))],
            [Paragraph("Módulos actuales · Qué puede hacer hoy · % de finalización · Módulos futuros · Recorrido de negocio · Cómo venderlo", ParagraphStyle("c4", parent=BODY, fontSize=10, textColor=colors.HexColor("#e5e7eb"), alignment=TA_CENTER, leading=15))],
            [Spacer(1, 60)],
            [Paragraph("Fecha: 17 de agosto de 2026 · Versión 0.9.1-candidate.3", ParagraphStyle("c5", parent=BODY, fontSize=9, textColor=colors.HexColor("#9ca3af"), alignment=TA_CENTER, leading=12))],
            [Paragraph("Documento generado desde el estado autoritativo del repositorio (STATUS.md / TASKS.md / docs)", ParagraphStyle("c6", parent=BODY, fontSize=8, textColor=colors.HexColor("#9ca3af"), alignment=TA_CENTER, leading=11))],
        ],
        colWidths=[W],
    )
    cover.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("TOPPADDING", (0, 0), (-1, 0), 60),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 40),
            ]
        )
    )
    story.append(cover)
    story.append(PageBreak())

    # --------------------------------------------------------------------- TOC
    story.append(block("Índice", "navy"))
    story.append(Spacer(1, 6))
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle("tocH1", parent=BODY, fontName="Helvetica-Bold", fontSize=10.5, leading=16),
        ParagraphStyle("tocH2", parent=BODY, fontSize=9, leading=13, leftIndent=14),
    ]
    story.append(toc)
    story.append(PageBreak())

    # ------------------------------------------------------------- 1. resumen
    story.append(block("1. Resumen ejecutivo"))
    story.append(
        P(
            "Bridge es una plataforma de operaciones de comercio B2B que, sobre un catálogo real (PrestaShop u otro), "
            "opera el ciclo completo <b>presupuesto → CONFIRMAR → pedido → factura con aprobaciones</b>, y encima de esas "
            "transacciones reales construye un <b>CRM B2B de ventas</b>: pipeline kanban, actividades y calendario de "
            "comercial, reporting con forecast ponderado, datos maestros (cuenta/contacto, merge, motivos de cierre), "
            "email integrado con tracking y campañas segmentadas. Todo por instancia gestionada, con roles verificados "
            "en vivo y evidencia medible."
        )
    )
    story.append(P("Estado a 17-08-2026 (datos del repositorio):"))
    story.extend(
        bullets(
            [
                "<b>Corpus de calidad:</b> 548 tests passed / 12 skipped; portal con 75 tests vitest, typecheck y build limpios; gates D-030 PASS.",
                "<b>Catálogo real:</b> 41.652 SKUs de PrestaShop sincronizados y paginados en vivo (coverage 100 % en 209 páginas); búsqueda léxica + semántica (51.570 embeddings).",
                "<b>Seguridad verificada:</b> RBAC 63/63 checks (7 roles × 9 módulos) en vivo; 24 modelos tenant-owned con aislamiento probado; auditoría completa.",
                "<b>Continuidad:</b> ensayo integral backup/restore/rollback sobre PostgreSQL real — backup cifrado en 10,9 s, restore con RTO 25,2 s, rollback 25,1 s.",
                "<b>CRM:</b> núcleo vendible P1 completo (kanban, reporting, timeline, actividades, campos personalizados, scoring) y P2 casi completo (import/export, email, calendario, webhooks, datos maestros, campañas).",
                "<b>Honestidad:</b> NO se vende como SaaS compartido ni producción certificada global; se vende como piloto de producción por instancia con plan de fases (ver sección 8).",
            ]
        )
    )

    # ----------------------------------------------------------- 2. acceso
    story.append(block("2. Acceso y roles — el punto de entrada"))
    story.append(P("El usuario entra por la URL de su instalación (HTTPS), con usuario nominal y contraseña. El primer acceso obliga a cambiar la contraseña. La sesión vive en la pestaña (sessionStorage) y se revoca con 401 al cerrar sesión o expirar."))
    story.append(P("Las opciones visibles dependen del rol. La matriz de permisos está verificada en vivo (63/63):"))
    story.append(
        table(
            [
                ["Rol", "Qué puede hacer"],
                ["client_admin / admin", "Todo: usuarios, aprobaciones, configuración, campañas, webhooks, email"],
                ["supervisor", "Ventas, clientes, reporting, aprobaciones de su equipo"],
                ["commercial", "Pipeline, leads, actividades, calendario, presupuestos, ventas"],
                ["support", "Clientes y consultas; sin mutar finanzas"],
                ["operator", "Operaciones de catálogo y comercio"],
                ["viewer", "Solo lectura; recibe 403 en clientes/ventas/wiki/tareas/usuarios"],
            ],
            widths=[W * 0.28, W * 0.72],
        )
    )
    story.append(Spacer(1, 4))
    story.append(
        P(
            "Navegación principal del portal: <b>Resumen · Aprobaciones · Productos · Ventas y facturación · Documentos · "
            "Agentes de IA · Clientes · Contenido y SEO · Tareas programadas · Webhooks salientes · Email integrado · "
            "Automatizaciones · Usuarios y permisos</b>. Dentro de <b>Clientes</b> hay pestañas: Leads y oportunidades, "
            "Pipeline (kanban), Reporting de ventas, Tareas, Calendario, Cuentas, Campos personalizados y Campañas."
        )
    )

    # ------------------------------------------------------- 3. recorrido módulos
    story.append(block("3. Recorrido de la aplicación, módulo a módulo"))
    story.append(P("Cada módulo indica <b>qué hace hoy</b>, <b>cómo se usa</b> y su <b>evidencia</b>."))

    story.append(P("3.1 Resumen (dashboard)", H2))
    story.append(
        P(
            "Indicadores operativos, estado de servicios e integraciones, y tarjetas de capacidad <b>según el rol</b>. "
            "Métricas internas, no BI histórico externo. Un comercial ve su pipeline y pendientes; un admin ve estado "
            "del sistema y aprobaciones."
        )
    )

    story.append(P("3.2 Catálogo de productos", H2))
    story.extend(
        bullets(
            [
                "Búsqueda <b>exacta, textual y semántica</b> (embeddings locales TF-IDF), ficha con precio, impuesto, stock y origen.",
                "<b>Sync PrestaShop incremental diario</b>: 41.652 SKUs con coverage 100 % en 209 páginas (326 s); también importación JSON/CSV/XLSX idempotente.",
                "Cada SKU declara su <b>origen</b> (prestashop/import/local) y el catálogo es fail-closed: un proveedor no confiable jamás aparece en venta.",
                "Pricelists con descuento por cliente y exención de IVA (pricing con variantes e IVA de los contratos reales).",
            ]
        )
    )

    story.append(P("3.3 Ventas y facturación", H2))
    story.extend(
        bullets(
            [
                "<b>Presupuesto:</b> cálculo 100 % en servidor (Decimal), con Idempotency-Key; caducidad y recordatorio por email.",
                "<b>CONFIRMAR &lt;token&gt;:</b> la confirmación crea el pedido con <b>reserva atómica de stock</b> verificada contra la autoridad (409 honesto si falta) y envía la factura PDF por email.",
                "<b>Facturas:</b> borrador → solicitud de aprobación → aprobación/rechazo con control de versión y auditoría; PDF determinista.",
                "<b>Dunning y cobro:</b> recordatorios de caducidad y dunning sin mutar importes; seguimiento del ciclo de vida (legal hold, exportación, borrado diferido).",
                "La emisión fiscal automática permanece desactivada (`ENABLE_AUTOMATIC_INVOICE_ISSUANCE=false`): la integración fiscal es un proyecto certificado aparte.",
            ]
        )
    )

    story.append(P("3.4 Chat comercial (agente de IA)", H2))
    story.extend(
        bullets(
            [
                "Asistente con <b>persona configurable por instalación</b> (`COMMERCE_ASSISTANT_NAME`) y <b>memoria de conversación</b> (últimos N mensajes).",
                "Responde en el <b>idioma y registro del cliente</b> (formal / tuteo / inglés), con directiva determinista de idioma/registro.",
                "Busca y compara productos del catálogo real: <b>cada SKU citado existe</b> (verificación determinista), con honestidad ante categorías ausentes.",
                "<b>Cierre de venta en el chat:</b> el cliente confirma el presupuesto con CONFIRMAR &lt;token&gt; y se crea pedido + factura + email, con degradación a spool si falla el proveedor.",
                "Calidad controlada por <b>LLM-as-judge</b> (rúbrica fluidez/coherencia/persona/honestidad, media global ≥ 4 como gate) sobre evidencias guardadas.",
            ]
        )
    )

    story.append(P("3.5 CRM completo (Clientes)", H2))
    story.extend(
        bullets(
            [
                "<b>Leads y oportunidades:</b> captura local idempotente (email único, referencia externa), deduplicación y origen (chat/web/form/import/local).",
                "<b>Pipeline kanban:</b> etapas configurables, drag&amp;drop, cambio de etapa auditado, cola de leads sin asignar, probabilidad por etapa y cierre won/lost con motivo.",
                "<b>Reporting de ventas:</b> funnel por etapa, ticket medio, win-rate, aging, `lost_reasons` y <b>forecast ponderado</b> (Σ valor × probabilidad).",
                "<b>Timeline de interacción:</b> historial cronológico por lead/oportunidad (email, nota, cambio de etapa, asignación, pedido).",
                "<b>Actividades y calendario:</b> tareas/recordatorios por lead u oportunidad con alerta por email (spool), vistas día/semana/mes con zona horaria del navegador.",
                "<b>Datos maestros:</b> cuentas (empresa) vs contactos (persona), merge de duplicados sin perder historial, probabilidad por etapa.",
                "<b>Campos personalizados:</b> por instalación, con tipos y visibilidad por rol; <b>lead scoring</b> determinista 0-100 con señales explicadas.",
                "<b>Import/export CSV</b> de leads con mapeo, plantilla y dry-run.",
            ]
        )
    )

    story.append(P("3.6 Email integrado", H2))
    story.extend(
        bullets(
            [
                "Plantillas con variables (`{{lead.first_name}}`, `{{store_name}}`, …), firma por instalación o por plantilla.",
                "<b>Tracking de apertura y clics</b>: pixel PNG 1×1 y redirect 302 por token, idempotente; sin base URL configurada no se emiten URLs rotas.",
                "Proveedor SMTP real con <b>degradación auditada al spool local</b> si falla (nunca pérdida silenciosa).",
            ]
        )
    )

    story.append(P("3.7 Campañas segmentadas", H2))
    story.extend(
        bullets(
            [
                "Segmento por <b>score, fuente, comercial asignado, cuenta y campos personalizados</b> (eq/gt/contains/is_set…, fail-closed).",
                "Preview (cuenta + muestra) antes de enviar; envío idempotente con <b>token de tracking por destinatario</b>.",
                "Respeto al <b>opt-out RGPD</b> (`email_opt_out`): los leads que optan fuera se omiten, nunca se les escribe.",
                "Estadísticas por campaña: enviados, abiertos y clics por destinatario.",
            ]
        )
    )

    story.append(P("3.8 Webhooks salientes", H2))
    story.extend(
        bullets(
            [
                "Suscripciones por evento CRM (lead.created, lead.assigned, pipeline.stage_changed, quote.confirmed, opportunity.closed).",
                "Firma <b>HMAC-SHA256 por suscripción</b>, outbox durable en la misma transacción que la mutación y <b>anti-SSRF</b> en dos capas.",
                "Test ping sin tocar la red; fallos a dead-letter auditada, nunca éxito fingido.",
            ]
        )
    )

    story.append(P("3.9 Documentos, wiki, landing y SEO", H2))
    story.extend(
        bullets(
            [
                "<b>RAG local</b> con clasificación y ACL deny-by-default, DLP en ingesta (redacción de secretos) y citas.",
                "<b>Wiki</b> con borrador/preview/publicación aprobada; <b>landing pages</b> locales aprobadas.",
                "<b>Generadores SEO deterministas</b> sobre catálogo y wiki: sitemap.xml, blog-rss, llms.txt y knowledge-indexer.",
            ]
        )
    )

    story.append(P("3.10 Tareas programadas y automatizaciones", H2))
    story.extend(
        bullets(
            [
                "Catálogo: sweep de caducidad/dunning, sync PrestaShop diario, alerta de stock bajo y follow-up de carrito abandonado; triggers por tiempo y por webhook.",
                "Cada automatización pasa por <b>request → activación con aprobación</b> y queda auditada; sin efecto financiero sin aprobación.",
            ]
        )
    )

    story.append(P("3.11 Usuarios y permisos", H2))
    story.extend(
        bullets(
            [
                "Alta/edición/revocación por `token_version`; cambio de contraseña obligatorio en primer acceso; RBAC 63/63 verificado en vivo.",
                "Auditoría completa de cada mutación con correlation_id y redacción de secretos en logs.",
            ]
        )
    )

    story.append(P("3.12 Observabilidad, backup y continuidad", H2))
    story.extend(
        bullets(
            [
                "Logs JSON correlacionados, métricas Prometheus, circuit breakers por proveedor, outbox con DLQ y alertas internas.",
                "Backup cifrado AES-256-CBC + HMAC + SHA256SUMS; ensayo integral sobre PostgreSQL real: backup 10,9 s, restore RTO 25,2 s, rollback 25,1 s.",
                "Tooling por cliente: provision-client, update-client, rollback-client (sh/ps1) + runbooks.",
            ]
        )
    )

    # ------------------------------------------------------------- 4. qué hace hoy
    story.append(block("4. Qué puede hacer la app HOY (resumen ejecutable)"))
    story.append(
        table(
            [
                ["Área", "Capacidad real verificada"],
                ["Catálogo", "41.652 SKUs PrestaShop sincronizados, búsqueda semántica, pricing por cliente, import/export"],
                ["Venta", "Presupuesto → CONFIRMAR → pedido → factura PDF → aprobación, con stock atómico y dunning"],
                ["Chat", "Asistente con persona, memoria, idioma/registro adaptado y cierre de venta en conversación"],
                ["CRM", "Kanban, reporting con forecast, timeline, actividades, calendario, cuentas/contactos, campos, scoring"],
                ["Email", "Plantillas, firma, tracking de apertura/clics, SMTP con degradación a spool"],
                ["Marketing", "Campañas segmentadas con opt-out y estadísticas por destinatario"],
                ["Integración", "Webhooks salientes firmados, outbox durable, anti-SSRF"],
                ["Contenido", "Wiki, landing, RAG con ACL, SEO (sitemap/RSS/llms.txt/knowledge-index)"],
                ["Gobierno", "RBAC 63/63, auditoría, observabilidad, backup/restore con RPO/RTO medidos"],
            ],
            widths=[W * 0.22, W * 0.78],
        )
    )

    # ------------------------------------------------------------- 5. finalización
    story.append(block("5. Porcentaje de finalización"))
    story.append(
        P(
            "Cifras calculadas desde <b>TASKS.md</b> (plan de remediación, 56 tareas) y el estado del plan CRM (T-044). "
            "«Finalizado» = estado VERIFIED en el repositorio (implementado + tests + evidencia)."
        )
    )
    story.append(
        table(
            [
                ["Bloque", "Estado", "%"],
                ["Gobierno y baseline (fase 0)", "4/4 VERIFIED", "100 %"],
                ["Núcleo de operaciones comerciales (catálogo, ventas, facturación, seguridad, observabilidad, backup, chat, SEO, automatizaciones, ciclo de vida)", "T-004…T-043 VERIFIED (3 del bloque histórico en curso: T-022/23/24)", "≈ 95 %"],
                ["CRM P1 — núcleo vendible (kanban, reporting, timeline, actividades, campos, scoring)", "6/6 VERIFIED", "100 %"],
                ["CRM P2 — crecimiento (import/export, email, calendario, webhooks, datos maestros, campañas)", "6/7 VERIFIED", "86 %"],
                ["CRM P2 — SSO/OIDC + MFA", "pendiente", "0 %"],
                ["CRM P3 — enterprise (multi-tenant RLS, billing, SCIM, BI, ERP/fiscal)", "0/5", "0 %"],
                ["Plan global (TASKS.md)", "46/56 VERIFIED", "82 %"],
            ],
            widths=[W * 0.66, W * 0.22, W * 0.12],
        )
    )
    story.append(Spacer(1, 4))
    story.append(
        P(
            "<b>Lectura:</b> la plataforma que se puede vender HOY como CRM B2B Pro está esencialmente completa "
            "(M0 + M1 al 100 %, M2 al 86 %). Lo pendiente son capacidades enterprise (multi-tenant, billing, SCIM, BI) "
            "y la seguridad de release (SBOM/TLS/soak/alertas externas — SS-02/03/06/07), que se entregan como fases "
            "del piloto, no como promesa de estado actual."
        )
    )

    # ------------------------------------------------------------- 6. actuales vs futuros
    story.append(block("6. Módulos actuales vs módulos futuros"))
    story.append(P("Módulos actuales (implementados y verificados):", H2))
    story.append(
        table(
            [
                ["Módulo", "Pase", "Detalle"],
                ["Catálogo + PrestaShop", "núcleo", "Sync incremental, búsqueda semántica, pricing, import/export"],
                ["Comercio (presupuestos/pedidos/facturas/aprobaciones)", "núcleo", "Ciclo completo con stock atómico y dunning"],
                ["Chat comercial IA", "núcleo", "Persona, memoria, idioma/registro, cierre de venta"],
                ["CRM P1-a kanban", "P1", "Etapas configurables, drag&drop, auditoría"],
                ["CRM P1-b reporting", "P1", "Funnel, ticket medio, win-rate, aging, forecast ponderado"],
                ["CRM P1-c timeline", "P1", "Historial cronológico por lead/oportunidad"],
                ["CRM P1-d actividades", "P1", "Tareas/recordatorios con alerta por email"],
                ["CRM P1-e campos personalizados + scoring", "P1", "Tipos/visibilidad por rol; score 0-100 explicado"],
                ["Import/export CSV", "P2", "Plantilla, mapeo y dry-run"],
                ["Email integrado", "P2", "Plantillas, firma, tracking apertura/clics, SMTP+spool"],
                ["Calendario de comercial", "P2", "Vistas día/semana/mes con tz del navegador"],
                ["Webhooks salientes", "P2", "HMAC por suscripción, outbox, anti-SSRF"],
                ["Datos maestros", "P2", "Cuenta/contacto, merge, probabilidad, motivos de cierre"],
                ["Campañas segmentadas", "P2", "Segmento por score/fuente/campos, opt-out, tracking por destinatario"],
                ["RAG + wiki + landing + SEO", "núcleo", "ACL deny-by-default, sitemap/RSS/llms.txt/knowledge-index"],
                ["Automatizaciones", "núcleo", "Sweep, sync diario, stock bajo, carrito abandonado, triggers webhook"],
                ["Gobierno", "núcleo", "RBAC 63/63, auditoría, observabilidad, backup/restore"],
            ],
            widths=[W * 0.34, W * 0.1, W * 0.56],
        )
    )
    story.append(Spacer(1, 6))
    story.append(P("Módulos futuros (roadmap honesto):", H2))
    story.append(
        table(
            [
                ["Módulo", "Bloque", "Qué aportaría"],
                ["SSO/OIDC + MFA", "P2", "Login corporativo y segundo factor (reusa revocación por token_version)"],
                ["Tickets/soporte con SLA", "P3", "Atención al cliente ligada a pedidos"],
                ["Equipos (grupos de comerciales)", "P3", "Reparto de cola y visibilidad por equipo"],
                ["Multi-tenant con RLS", "P3", "tenant_id + row-level security sobre los 24 modelos owned (esquema ya diseñado)"],
                ["Billing integrado", "P3", "Suscripción por tier con límites y suspensión controlada"],
                ["SCIM + gobernanza de acceso", "P3", "Aprovisionamiento/deprovisionamiento automático"],
                ["BI embebido", "P3", "Datamart de ventas + exportación a Power BI/Looker"],
                ["ERP/fiscal certificado", "P3", "Facturación fiscal (proyecto independiente con certificación)"],
                ["Agente de escucha social (Instagram, WhatsApp, Facebook, LinkedIn, X)", "idea", "Ingesta de menciones/DM de redes → triaje IA → leads y actividades en el CRM (ver nota)"],
            ],
            widths=[W * 0.34, W * 0.1, W * 0.56],
        )
    )
    story.append(Spacer(1, 4))
    story.append(
        P(
            "<b>Nota (idea de producto recogida en sesión):</b> un agente de escucha social conectaría los canales "
            "(Instagram, WhatsApp, Facebook, LinkedIn, X) para convertir menciones y mensajes en leads, actividades y "
            "seguimientos dentro del CRM — encaja como módulo P2/P3 de adquisición, reutilizando el pipeline de leads, "
            "actividades y el spool de email."
        )
    )

    # ------------------------------------------------------------- 7. recorrido de negocio
    story.append(block("7. Recorrido de negocio — el ciclo de venta completo"))
    story.append(
        P(
            "Cómo se gana dinero con la app y cómo el comercial opera el día a día, de la captura al cobro y la retención:"
        )
    )
    journey = [
        ["#", "Paso", "Dónde ocurre", "Qué produce"],
        ["1", "Captura", "Chat comercial / web / formulario / import", "Lead con fuente, score y señales"],
        ["2", "Calificación", "Kanban: cola de leads sin asignar → asignación al comercial", "Lead asignado, etapa «calificado»"],
        ["3", "Propuesta", "Presupuesto con precios del servidor y caducidad", "Oportunidad en etapa «presupuesto»"],
        ["4", "Negociación", "Timeline + actividades (llamada, reunión, follow-up)", "Historial auditado y recordatorios"],
        ["5", "Cierre", "CONFIRMAR <token> en el chat o confirmación en portal", "Pedido + reserva atómica de stock"],
        ["6", "Facturación", "Factura borrador → aprobación → PDF por email", "Factura con tracking de apertura"],
        ["7", "Cobro", "Dunning y recordatorios de caducidad (automatizaciones)", "Seguimiento de cobro sin perderla"],
        ["8", "Post-venta", "Actividades, calendario, campañas de retención", "Renovación / cross-sell con el CRM"],
        ["9", "Medición", "Reporting: funnel, win-rate, ticket medio, aging, motivos de pérdida", "Forecast ponderado para dirección"],
    ]
    story.append(
        table(journey, widths=[W * 0.05, W * 0.2, W * 0.45, W * 0.3])
    )
    story.append(Spacer(1, 4))
    story.append(
        P(
            "<b>Clave del modelo:</b> el CRM no se rellena a mano — se llena solo con cada presupuesto del chat y cada "
            "pedido. El comercial opera el ciclo completo desde el portal sin salir de él, y cada cambio queda auditado."
        )
    )

    # ------------------------------------------------------------- 8. cómo venderlo
    story.append(block("8. Cómo venderlo — pitch comercial"))
    story.append(P("8.1 Posicionamiento y segmentos", H2))
    story.append(
        P(
            "Se vende como <b>CRM B2B + back-office comercial por instancia gestionada</b> (una instalación aislada por "
            "cliente con tooling de provision/update/rollback ya existente), no como SaaS compartido. Tres segmentos:"
        )
    )
    story.append(
        table(
            [
                ["Segmento", "Dolor", "Gancho de cierre"],
                ["Distribuidor B2B", "Presupuestos manuales, sin aprobaciones ni auditoría, stock en Excel", "«Tu catálogo ya está sincronizado y paginado; el piloto se monta en una semana»"],
                ["Fabricante con red", "Precios/stocks distintos por cliente, red sin control", "«Tu red confirma con tu tarifa y stock; el sistema lo audita todo»"],
                ["Marketplace", "Catálogos mezclados sin control de origen", "«Cada vendedor ve solo lo suyo; el aislamiento se demuestra con un test»"],
            ],
            widths=[W * 0.22, W * 0.4, W * 0.38],
        )
    )
    story.append(Spacer(1, 6))
    story.append(P("8.2 Precios (por instancia gestionada, no por usuario)", H2))
    story.append(
        table(
            [
                ["Tier", "Precio/mes", "Setup", "Incluye"],
                ["Starter", "€149", "€0–1.000", "Catálogo + chat, presupuesto→pedido→factura, kanban básico, 3 usuarios"],
                ["Pro", "€499", "€2.500", "Todo Starter + pipeline configurable, actividades, reporting, scoring, automatizaciones, 15 usuarios"],
                ["Enterprise", "€1.900", "€5.000–10.000", "Todo Pro + SSO/MFA, campañas segmentadas, API/webhooks, calendario, soporte prioritario"],
                ["Add-ons", "variable", "—", "Multi-tenant con billing, SCIM, BI, ERP/fiscal certificado (por proyecto)"],
            ],
            widths=[W * 0.16, W * 0.13, W * 0.16, W * 0.55],
        )
    )
    story.append(Spacer(1, 6))
    story.append(P("8.3 Diferenciadores con evidencia (todo reproducible por el comprador)", H2))
    story.append(
        table(
            [
                ["Claim", "Evidencia"],
                ["RPO/RTO medidos, no prometidos", "Ensayo sobre PostgreSQL real: backup 10,9 s · restore RTO 25,2 s · rollback 25,1 s (SS-05)"],
                ["RBAC verificado en vivo", "63/63 checks (7 roles × 9 módulos) en 5,27 s (SS-04)"],
                ["Catálogo real a escala", "41.652 SKUs sincronizados, coverage 100 % en 209 páginas"],
                ["Ciclo comercial completo operado", "Chat → presupuesto → CONFIRMAR → pedido → aprobación → factura PDF en conversación real"],
                ["Calidad auditable", "Corpus 548 tests, gates D-030, zona limpia 0 issues, migraciones no destructivas"],
                ["Aislamiento probado", "24 modelos tenant-owned, matriz cross-tenant verde"],
            ],
            widths=[W * 0.32, W * 0.68],
        )
    )
    story.append(Spacer(1, 6))
    story.append(P("8.4 Qué NO prometer (regla de venta)", H2))
    story.extend(
        bullets(
            [
                "No vender «SBOM certificado» hoy: se entrega como fase 0 del piloto (build final + Trivy + SBOM firmado).",
                "No vender SLA de rendimiento sin medir: fase 2 (soak + degradación Redis/DB con el catálogo del cliente).",
                "No vender «producción certificada global» ni «SaaS compartido»: se vende un plan con fases, fechas y criterios de salida medibles.",
                "Emisión fiscal automática fuera del alcance del producto base (requiere proyecto certificado aparte).",
            ]
        )
    )
    story.append(
        P(
            "<b>Máxima de venta:</b> «El contrato incluye las pruebas; tú puedes ejecutarlas.» Y guion de llamada de 30 "
            "min: (1) demo del ciclo chat→presupuesto→CONFIRMAR→pedido→aprobación; (2) diferenciador con evidencia; "
            "(3) alcance por segmento + fases 0-3 con fechas; (4) cierre con piloto en una semana y propuesta en 48 h."
        )
    )

    # ------------------------------------------------------------- 9. anexo
    story.append(block("9. Anexo — dónde verificar cada afirmación"))
    story.append(
        table(
            [
                ["Afirmación", "Fuente"],
                ["Estado y métricas actuales", "STATUS.md · CHANGELOG.md · TASKS.md"],
                ["Evidencia de pruebas", "docs/TEST_EVIDENCE.md · docs/TEST_REPORT.md"],
                ["Pitch y propuesta", "docs/PITCH_COMERCIAL.md"],
                ["Plan de producto CRM y precios", "docs/PRODUCT_PLAN_CRM_B2B.md"],
                ["Inventario de módulos", "docs/BUSINESS_MODULES.md"],
                ["Readiness y stop-ships", "docs/PRODUCTION_READINESS.md (SS-01…SS-07)"],
                ["Esquema multi-tenant", "docs/ARCHITECTURE_SAAS_MULTI_TENANT.md"],
                ["Manual de usuario y admin", "docs/USER_MANUAL.md · docs/ADMIN_MANUAL.md"],
            ],
            widths=[W * 0.42, W * 0.58],
        )
    )

    doc.multiBuild(story, onFirstPage=header_footer, onLaterPages=header_footer)
    print(f"OK: {OUT}")


if __name__ == "__main__":
    build()
