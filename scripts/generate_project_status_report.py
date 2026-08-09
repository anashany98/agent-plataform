"""Generate a comprehensive project status report in PDF.

Produces: release/project-status-report/PROJECT_STATUS_REPORT.pdf
Author: ZCode (autonomous remediation workflow)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


PROJECT_ROOT = Path(r"C:\Users\PC\Desktop\PROYECTOS\agent-platform-fixed")
OUTPUT_DIR = PROJECT_ROOT / "release" / "project-status-report"
OUTPUT_PDF = OUTPUT_DIR / "PROJECT_STATUS_REPORT.pdf"


# ----------------------------- Styling helpers ----------------------------- #


def build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    styles: dict[str, ParagraphStyle] = {}

    styles["title"] = ParagraphStyle(
        "title",
        parent=base["Title"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=colors.HexColor("#0B2545"),
        spaceAfter=8,
        alignment=TA_CENTER,
    )
    styles["subtitle"] = ParagraphStyle(
        "subtitle",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#134074"),
        alignment=TA_CENTER,
        spaceAfter=12,
    )
    styles["h1"] = ParagraphStyle(
        "h1",
        parent=base["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0B2545"),
        spaceBefore=18,
        spaceAfter=8,
    )
    styles["h2"] = ParagraphStyle(
        "h2",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#13315C"),
        spaceBefore=12,
        spaceAfter=6,
    )
    styles["h3"] = ParagraphStyle(
        "h3",
        parent=base["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#1B4D89"),
        spaceBefore=8,
        spaceAfter=4,
    )
    styles["body"] = ParagraphStyle(
        "body",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#1A1A1A"),
        alignment=TA_JUSTIFY,
        spaceAfter=6,
    )
    styles["bullet"] = ParagraphStyle(
        "bullet",
        parent=styles["body"],
        leftIndent=14,
        bulletIndent=2,
        spaceAfter=2,
    )
    styles["code"] = ParagraphStyle(
        "code",
        parent=base["Code"],
        fontName="Courier",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#0E1B2C"),
        backColor=colors.HexColor("#F2F4F7"),
        leftIndent=6,
        spaceAfter=6,
    )
    styles["caption"] = ParagraphStyle(
        "caption",
        parent=base["Italic"],
        fontName="Helvetica-Oblique",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#52606D"),
        alignment=TA_LEFT,
        spaceAfter=10,
    )
    styles["cover_meta"] = ParagraphStyle(
        "cover_meta",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=16,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#13315C"),
    )
    return styles


# ----------------------------- Page templates ----------------------------- #


class StatusDoc(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs) -> None:
        super().__init__(filename, pagesize=A4, **kwargs)
        margin = 18 * mm
        self.addPageTemplates(
            [
                PageTemplate(
                    id="cover",
                    frames=[
                        Frame(
                            margin,
                            margin,
                            A4[0] - 2 * margin,
                            A4[1] - 2 * margin,
                            id="cover-frame",
                            showBoundary=0,
                        )
                    ],
                    onPage=self._draw_cover_decoration,
                ),
                PageTemplate(
                    id="content",
                    frames=[
                        Frame(
                            margin,
                            margin + 12 * mm,
                            A4[0] - 2 * margin,
                            A4[1] - 2 * margin - 12 * mm,
                            id="content-frame",
                            showBoundary=0,
                        )
                    ],
                    onPage=self._draw_page_decoration,
                ),
            ]
        )

    def _draw_cover_decoration(self, canvas, doc) -> None:  # noqa: D401
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#0B2545"))
        canvas.rect(0, 0, A4[0], 18 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(18 * mm, 6 * mm, "agent-platform — Estado de remediación")
        canvas.drawRightString(A4[0] - 18 * mm, 6 * mm, "Informe técnico completo")
        canvas.restoreState()

    def _draw_page_decoration(self, canvas, doc) -> None:  # noqa: D401
        canvas.saveState()
        # Header band
        canvas.setFillColor(colors.HexColor("#0B2545"))
        canvas.rect(0, A4[1] - 12 * mm, A4[0], 12 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(18 * mm, A4[1] - 8 * mm, "agent-platform — Informe de estado")
        canvas.drawRightString(
            A4[0] - 18 * mm, A4[1] - 8 * mm, "Rama production-remediation"
        )
        # Footer
        canvas.setFillColor(colors.HexColor("#52606D"))
        canvas.setFont("Helvetica", 8)
        canvas.drawString(18 * mm, 8 * mm, "ZCode — flujo autónomo de remediación")
        canvas.drawRightString(
            A4[0] - 18 * mm, 8 * mm, f"Página {doc.page}"
        )
        canvas.restoreState()


# ----------------------------- Content blocks ------------------------------ #


def p(text: str, style) -> Paragraph:
    return Paragraph(text, style)


def bullet(text: str, styles) -> Paragraph:
    return Paragraph(f"• {text}", styles["bullet"])


def make_table(rows: list[list[str]], col_widths: list[float]) -> Table:
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#13315C")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor("#F2F4F7")]),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#13315C")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C1C9D2")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


# ----------------------------- Cover & TOC -------------------------------- #


def build_cover(styles) -> list:
    story = []
    story.append(Spacer(1, 6 * cm))
    story.append(p("Informe técnico completo", styles["subtitle"]))
    story.append(p("Estado, fallos, trabajo pendiente y plan para producción", styles["subtitle"]))
    story.append(Spacer(1, 0.8 * cm))
    story.append(p("Agente de IA empresarial", styles["title"]))
    story.append(p("agent-platform — Rama production-remediation", styles["title"]))
    story.append(Spacer(1, 1.2 * cm))
    story.append(p("Fecha de evaluación: 9 de agosto de 2026", styles["cover_meta"]))
    story.append(p("Recovery commit: ed77056 · Commit P0: de236e9", styles["cover_meta"]))
    story.append(p("Decisión actual: NOT PRODUCTION READY — CRITICAL RISK", styles["cover_meta"]))
    story.append(Spacer(1, 2.0 * cm))
    story.append(
        p(
            "Documento único que consolida el estado del proyecto, lo que falla, lo que "
            "falta para completarlo, cómo solucionarlo y qué se necesita para llevar la "
            "plataforma a producción. Resume los registros autoritativos "
            "(<font face='Courier'>docs/PRODUCTION_READINESS.md</font>, <font face='Courier'>TASKS.md</font>, "
            "<font face='Courier'>STATUS.md</font>, <font face='Courier'>BLOCKERS.md</font> y la auditoría "
            "técnica en <font face='Courier'>docs/audit/</font>).",
            styles["body"],
        )
    )
    story.append(NextPageTemplate("content"))
    story.append(PageBreak())
    return story


def build_toc(styles) -> list:
    story = []
    story.append(p("Índice", styles["h1"]))
    sections = [
        ("1. Resumen ejecutivo y decisión", "5"),
        ("2. Estado por fases (0–29)", "7"),
        ("3. Lo que falla — defectos P0/P1/P2 abiertos", "10"),
        ("4. Lo que ya está corregido y verificado", "13"),
        ("5. Lo que falta para completarlo (trabajo pendiente)", "15"),
        ("6. Cómo solucionarlo (plan técnico)", "17"),
        ("7. Bloqueos externos y dependencias", "19"),
        ("8. Lo que falta para producción (30 criterios PR-)", "20"),
        ("9. Riesgos críticos y residuales", "23"),
        ("10. Roadmap 30/60/90 y release candidata", "24"),
        ("11. Recomendaciones finales", "26"),
        ("12. Anexos: artefactos y referencias", "27"),
    ]
    rows = [["Sección", "Pág."]]
    for name, page in sections:
        rows.append([name, page])
    story.append(make_table(rows, [15.5 * cm, 1.5 * cm]))
    story.append(Spacer(1, 1 * cm))
    story.append(p("Aviso de fuente autoritativa", styles["h3"]))
    story.append(
        p(
            "Cualquier informe previo que contradiga lo afirmado aquí queda "
            "<b>SUPERSEDED</b>. La única fuente válida para tomar decisiones de "
            "readiness es <font face='Courier'>docs/PRODUCTION_READINESS.md</font>.",
            styles["body"],
        )
    )
    story.append(PageBreak())
    return story


# --------------------------- Section builders ----------------------------- #


def section_1_executive_summary(styles) -> list:
    story = []
    story.append(p("1. Resumen ejecutivo y decisión", styles["h1"]))

    story.append(p("1.1 Decisión actual", styles["h2"]))
    rows = [
        ["Atributo", "Valor"],
        ["Decisión", "NOT PRODUCTION READY — CRITICAL RISK"],
        ["Rama", "production-remediation"],
        ["Recovery commit", "ed77056"],
        ["Commit P0", "de236e9 (seis P0 verificados)"],
        ["Corpus combinado", "245/245 verde en ambos órdenes de colección"],
        ["Defectos P0 abiertos", "0 (seis cerrados y verificados en rama)"],
        ["Defectos P1 abiertos", "9 (todos de runtime / bloqueados por sandbox)"],
        ["Defectos P2 abiertos", "0"],
        ["Criterios VERIFIED", "0 / 30 (todos siguen BLOCKED)"],
        ["Release candidata", "No existe"],
        ["Sandboxes externas", "No autorizadas (PrestaShop, GHL, Chatwoot, IA)"],
    ]
    story.append(make_table(rows, [5.5 * cm, 11.5 * cm]))
    story.append(Spacer(1, 0.4 * cm))

    story.append(p("1.2 ¿Qué es el proyecto?", styles["h2"]))
    story.append(
        p(
            "Plataforma empresarial multi-cliente de agentes de IA orientada a venta, "
            "atención, soporte, leads, presupuestos, pedidos, facturación controlada, "
            "wiki, RAG documental, SEO técnico, landing pages y automatizaciones. La "
            "arquitectura sigue la <b>Ruta A</b>: Bridge API como núcleo transaccional, "
            "Portal de administración, Chatwoot para conversaciones, FlowWink como "
            "framework visual de apoyo y Activepieces como motor externo de "
            "automatizaciones. Toda la operativa crítica vive en el Bridge; los "
            "proveedores externos son adaptadores intercambiables.",
            styles["body"],
        )
    )

    story.append(p("1.3 Foto del estado", styles["h2"]))
    rows = [
        ["Aspecto", "Estado actual", "Veredicto"],
        ["Bloque P0 (riesgo crítico de datos/transacción)", "6 verificados en rama con pruebas y PostgreSQL real", "OK rama / pendiente candidata"],
        ["Bloque P1 Wave 1 (defectos corregibles sin runtime)", "VERIFIED en rama (tool policy, resiliencia, webhooks, GHL, RAG, dependencias, observabilidad, lifecycle, portal/docs, quality gates, backup/restore, automatizaciones FlowWink, agentes/IA)", "OK rama"],
        ["Wave 1 de P1 (defectos restantes)", "Cerrada por completo (Wave 1 agotada el 2026-08-03)", "OK rama"],
        ["P1 runtime/bloqueados", "9 abiertos (egress live, preflight puertos, handoff Chatwoot, release/digest, alcance FlowWink, licencias, etc.)", "BLOQUEADO"],
        ["Stack core", "Levantado en Docker (bridge-db/redis/api/portal + proxy SETUID); opcionales en 502 graceful", "OK runtime parcial"],
        ["Build limpio", "Abortado a 95,3 % de RAM en build previo; medición de margen pendiente", "BLOQUEADO"],
        ["E2E crítico (chat, comercio, Chatwoot, PrestaShop, GHL, Portal, restore)", "Sólo chat→lead→presupuesto reproducible en vivo (sin Chatwoot)", "BLOQUEADO"],
        ["Seguridad (security baseline)", "FAILED — RBAC, RAG egress, egress real, supply chain, licencias pendientes", "BLOQUEADO"],
    ]
    story.append(make_table(rows, [5 * cm, 7 * cm, 5 * cm]))
    story.append(Spacer(1, 0.4 * cm))

    story.append(p("1.4 Mensaje clave para la dirección", styles["h2"]))
    story.append(
        p(
            "El proyecto <b>no puede venderse ni operarse como producción</b> hoy. "
            "El bloque crítico P0 está corregido en la rama <font face='Courier'>production-remediation</font> "
            "con cobertura de pruebas real, pero quedan nueve P1 que solo se cierran "
            "con runtime vivo, sandboxes autorizadas y un ciclo de release. La decisión "
            "se mantiene en <b>NOT PRODUCTION READY — CRITICAL RISK</b> y solo puede "
            "cambiarse evaluando una release candidata identificada por versión y hash.",
            styles["body"],
        )
    )
    story.append(PageBreak())
    return story


def section_2_phases(styles) -> list:
    story = []
    story.append(p("2. Estado por fases (0–29)", styles["h1"]))
    story.append(
        p(
            "El plan maestro ordena 30 fases obligatorias más una release. Cada fila "
            "resume lo verificado en el momento de redactar este informe; los "
            "documentos autoritativos (<font face='Courier'>TASKS.md</font>, "
            "<font face='Courier'>STATUS.md</font>, <font face='Courier'>docs/PRODUCTION_READINESS.md</font>) "
            "deben consultarse para el detalle.",
            styles["body"],
        )
    )

    rows = [["Fase", "Título", "Estado", "Notas"]]
    rows += [
        ["0", "Baseline", "VERIFIED", "docs/baseline/ completo; topología, dependencias y propiedad de datos."],
        ["1", "Reproducción de defectos", "VERIFIED", "19 tests rojos; 32 defectos contrastados; 5 nuevos tras revisión adversarial."],
        ["2", "Corrección P0 / P1", "IN PROGRESS", "6 P0 VERIFIED, 17 P1 VERIFIED (incluidos D-012, D-021, D-035, D-010, D-020, D-017, D-028, D-029, D-026/D-027, D-030, D-015/D-016, lote 1/lote 2 FlowWink); 9 P1 restantes runtime/bloqueados."],
        ["3", "Arquitectura de producción", "IN PROGRESS", "Perfil core verificado en runtime (proxy SETUID, límites, smoke por 9000); perfil full y E2E pendientes."],
        ["4–5", "Framework de agentes + IA", "IN PROGRESS", "ToolExecutor deny-by-default VERIFIED (D-012); `agent_ai.docs_chat` extractivo VERIFIED; cancelación del runner y costes reales aún abiertos."],
        ["6", "Chat y atención", "PARTIAL", "Webhook Chatwoot degrada a canal interno sin token; E2E chat→lead→presupuesto reproducible sin Chatwoot."],
        ["7", "Catálogo", "PARTIAL", "Contratos P0 cerrados; D-033/D-034 (paginación >500 y `show_price`/`available_for_order`) siguen TODO."],
        ["8", "CRM y leads", "PARTIAL", "LocalCRM funcional; GHL con outbox/reconciliación (D-010 VERIFIED); contrato live pendiente (B-004)."],
        ["9–11", "Presupuestos / Pedidos / Facturación", "PARTIAL", "Borradores y confirmaciones con token/hash/caducidad; idempotencia de reservas; emisión automática desactivada por defecto; falta E2E con proveedor real."],
        ["12", "Wiki", "PARTIAL", "Modelo y CRUD presentes; falta evaluación de borradores, aprobación y sandbox de publicación."],
        ["13", "RAG", "PARTIAL", "Clasificación+DLP+ACL deny-by-default + prompt-injection defense VERIFIED (D-020); sandbox del proveedor real pendiente (B-006)."],
        ["14–15", "SEO + SEO continuo", "TODO", "Fase SEO diferida (Ruta A)."],
        ["16", "Landing pages", "TODO", "Sin implementar."],
        ["17", "Automatizaciones", "PARTIAL", "Lote 1 FlowWink sin Supabase (router email local, quote-expiry, dunning, generate-invoice-pdf, send-webhook HMAC, sweep) VERIFIED."],
        ["18", "Aprobaciones", "PARTIAL", "Motor presente con CAS; carrera read-then-write aún abierta (D-011)."],
        ["19", "Portal", "PARTIAL", "Secciones reales y runner vitest verde; E2E visual/a11y en viewports pendientes."],
        ["20", "Auth/RBAC", "PARTIAL", "Auth bearer VERIFIED; matriz completa de rutas/recursos/tenants y service accounts aún no."],
        ["21", "Seguridad", "FAILED", "Threat model documentado; P0 seguridad (datos/transacción) cerrados; quedan P1 (D-006, D-013, D-014, D-018, D-023)."],
        ["22", "Observabilidad", "PARTIAL", "Middleware JSON correlacionado, redacción y métricas Prometheus VERIFIED (D-028); falta OTel/scrape y SLO formales."],
        ["23", "Docker / Infra", "IN PROGRESS", "Perfil core levantado y limits aplicados; perfil full y soak no ejecutados."],
        ["24", "Backup / DR", "IN PROGRESS", "Restauración REAL verificada (SQLite + PostgreSQL efímero) en 6b34200; RPO/RTO y restore en instalación vacía pendientes."],
        ["25", "CI/CD", "TODO", "Pipeline autoritativo no existe; gates de quality_ruff sí."],
        ["26", "Tests", "IN PROGRESS", "245 verde; suite P1 runtime, E2E, RAG exfil a escala y seguridad aún pendientes."],
        ["27", "Rendimiento", "BLOCKED", "Carga bloqueada por RAM; informe F-027 con cuello de botella conocido."],
        ["28", "Licencias", "PARTIAL", "Matriz Python propia VERIFIED (D-023); rutas EE vendor marcadas \"requiere revisión legal\" (B-008)."],
        ["29", "Documentación", "PARTIAL", "README reescrito y SUPERSEDED en informes históricos; lint doc/links automatizado pendiente."],
        ["Release", "Release final", "BLOCKED", "Sin candidata reproducible; release/production-candidate/ vacío."],
    ]
    story.append(make_table(rows, [1.5 * cm, 4 * cm, 2.5 * cm, 9 * cm]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(
        p(
            "<b>Lectura:</b> las fases 0–2 están prácticamente cerradas en la rama "
            "(salvo los P1 runtime). El resto depende de tres palancas: "
            "(a) cerrar runtime contra sandboxes autorizadas, "
            "(b) ejecutar el ciclo de release con imágenes por digest, y "
            "(c) conseguir margen real de RAM para build/soak.",
            styles["body"],
        )
    )
    story.append(PageBreak())
    return story


def section_3_failures(styles) -> list:
    story = []
    story.append(p("3. Lo que falla — defectos P0/P1/P2 abiertos", styles["h1"]))
    story.append(
        p(
            "Listado vivo de defectos que aún no están <font face='Courier'>VERIFIED</font>. "
            "Los seis P0 originales están cerrados en rama; los P0 que reabrirían la "
            "decisión están cubiertos por los stop-ship vigentes.",
            styles["body"],
        )
    )

    story.append(p("3.1 P1 de runtime / bloqueados por sandbox", styles["h2"]))
    rows = [
        ["ID", "Componente", "Problema", "Estado"],
        ["P1-001 (D-006)", "Red / Egress", "Bridge sin ruta de salida; integraciones externas y Ollama inaccesibles (errno 101)", "TODO — requiere red egress + allowlist"],
        ["P1-002 (D-007)", "Chatwoot", "PID stale en reinicio; loop de arranque y crash del servicio", "TODO — depende de P1-001 y runtime Chatwoot"],
        ["P1-003 (D-008)", "Proxy", "Nginx master sin workers por capabilities (sin SETUID)", "FIXED rama (cap_add) — verificación live pendiente"],
        ["P1-005 (D-013)", "Activepieces", "2xx sin ID produce éxito `exec-*` ficticio", "TODO — contrato estricto"],
        ["P1-006 (D-011)", "Aprobaciones", "Race read-then-write sin CAS/lock; approve y reject pueden ganar ambos", "TODO — CAS o versionado"],
        ["P1-007 (D-014)", "Costes IA", "Coste siempre 0; presupuesto IA no corta ejecución", "TODO — tarifario + usage real"],
        ["P1-008 (D-015)", "DR / Backup", "Restore real no ejecutado en instalación vacía con flujos completos", "IN PROGRESS — restauración SQLite y PG efímero (6b34200) verificada; RPO/RTO en candidata pendientes"],
        ["P1-009 (D-016)", "Release", "Update/rollback sin trazar; checkout global; falta candidata por digest", "TODO — pipeline con digests e imágenes inmutables"],
        ["P1-013 (D-033)", "PrestaShop", "Paginación fija en adaptadores (>500 reglas truncadas)", "TODO — depende de sandbox"],
        ["P1-014 (D-034)", "PrestaShop", "`show_price`/`available_for_order` no se aplican (precio 999 oculto expuesto)", "TODO — depende de sandbox"],
        ["P1-016 (D-036)", "Importación", "Retry duplica tarifas; auditoría no es transaccional", "TODO — Idempotency-Key + dato+audit/outbox transaccional"],
    ]
    story.append(make_table(rows, [1.6 * cm, 2.6 * cm, 8.2 * cm, 4.6 * cm]))
    story.append(Spacer(1, 0.4 * cm))

    story.append(p("3.2 Otros P1 / P2 relevantes ya cerrados pero con residuales", styles["h2"]))
    rows = [
        ["Defecto", "Componente", "Cierre actual", "Residual / bloqueo"],
        ["D-010", "GHL / webhooks", "VERIFIED — reconciliación previa al efecto en outbox y `/integrations/ghl/leads`", "Contrato live del endpoint de búsqueda pendiente de sandbox GHL (B-004)"],
        ["D-012", "Tool policy", "VERIFIED — `ToolExecutor` deny-by-default, allowlist por agente, herramientas financieras prohibidas", "Cancelación/kill switch del runner (F04-05)"],
        ["D-017", "Dependencias", "VERIFIED — Pillow 12.x, pypdf 6.x, Vite ^7, `scripts/audit_dependencies.py` con pip-audit + npm audit", "Rotación y SBOM por release (Fase 28)"],
        ["D-019", "Chatwoot handoff", "Verificado en rama con contratos; runtime vivo y sandbox pendientes", "Inbox Chatwoot configurado (B-005)"],
        ["D-020", "RAG", "VERIFIED — clasificación + DLP + ACL deny-by-default + anti prompt-injection", "Sandbox del proveedor RAG real (B-006) y dataset exfil a escala"],
        ["D-021", "Resiliencia", "VERIFIED — circuit breakers, outbox durable, DLQ, captura GHL reencolada", "Pruebas de sustitución live y contrato de degradación"],
        ["D-022", "Validación estricta", "VERIFIED — `validate_runtime_security` rechaza SQLite/CORS/DEBUG/secretos", "Smoke en arranque production completo"],
        ["D-023", "Licencias", "PARTIAL — `LICENSE`, `THIRD_PARTY_NOTICES.md`, `docs/LICENSE_MATRIX.md`", "Revisión legal de vendor EE (B-008)"],
        ["D-026/D-027", "Portal/docs", "VERIFIED — README y banners SUPERSEDED; anchors corregidos; vitest runner", "E2E visual en viewports"],
        ["D-028", "Observabilidad", "VERIFIED — logs JSON correlacionados, redacción, métricas, alertas in-memory", "OTel/Prometheus scrape y SLO formales"],
        ["D-029", "Lifecycle", "VERIFIED — export, erase, legal hold, modelo `InstallationLifecycle`", "Política de retención revisada por legal"],
        ["D-030", "Quality gates", "VERIFIED — `scripts/quality_gates.py` con trinquete y baseline visible", "CI formal + modularización por dominio"],
        ["D-035", "Webhook crash recovery", "VERIFIED — checkpoint del resultado tras efecto externo + `_resume_webhook_from_checkpoint`", "Idempotencia del proveedor GHL (cerrada vía D-010)"],
    ]
    story.append(make_table(rows, [1.6 * cm, 2.4 * cm, 7.0 * cm, 6.0 * cm]))
    story.append(Spacer(1, 0.4 * cm))

    story.append(p("3.3 ¿Por qué no se cierra todo en código?", styles["h2"]))
    story.append(
        p(
            "Porque la auditoría técnica y las reglas innegociables de producción "
            "(ver <font face='Courier'>AGENTS.md</font>) prohíben declarar VERIFIED "
            "sólo con código, compilación, health verde o mocks. Cada criterio exige "
            "prueba real y reproducible contra la candidata evaluada. Los defectos "
            "restantes requieren, en todos los casos, alguno de los siguientes "
            "elementos externos o de runtime:",
            styles["body"],
        )
    )
    for t in [
        "Sandbox de PrestaShop con datos ficticios para D-033/D-034 y golden cases de precio/IVA.",
        "Subcuenta sandbox de GHL para fault injection en leads, oportunidades y notas (D-010 live).",
        "Inbox Chatwoot configurado y runtime estable para handoff y B-005.",
        "Proveedor LLM autorizado o claves sandbox para tool calling y costes reales (D-014, F04-05).",
        "Host dimensionado para build `--no-cache --pull` y soak del perfil full.",
        "Aprobación legal para redistribución del binario y rutas EE de vendor (B-008).",
    ]:
        story.append(bullet(t, styles))
    story.append(PageBreak())
    return story


def section_4_verified(styles) -> list:
    story = []
    story.append(p("4. Lo que ya está corregido y verificado", styles["h1"]))
    story.append(
        p(
            "Lista no exhaustiva de los cierres VERIFIED en la rama "
            "<font face='Courier'>production-remediation</font>, con su commit de "
            "evidencia. La fuente de verdad es <font face='Courier'>STATUS.md</font> "
            "y <font face='Courier'>docs/PRODUCTION_READINESS.md</font>.",
            styles["body"],
        )
    )

    rows = [
        ["ID", "Componente", "Solución", "Commit"],
        ["P0-001 / D-001", "Catálogo demo", "Whitelist de procedencia + flags fail-closed; seed opt-in", "de236e9"],
        ["P0-002 / D-002", "Confirmación", "State machine con token HMAC, hash, caducidad, actor, replay; concurrency PostgreSQL", "de236e9"],
        ["P0-003 / D-003", "Pricing/fiscalidad", "Servicio Decimal con snapshot de autoridad; 20 contratos PrestaShop", "de236e9"],
        ["P0-004 / D-004", "Stock/reservas", "Reserva idempotente, release/expiración, oversell PostgreSQL concurrente", "de236e9"],
        ["P0-005 / D-005", "Migraciones", "Alembic explícito; downgrade/reupgrade verificados; reserva activa", "de236e9"],
        ["P0-006 / D-006", "Aislamiento", "14 modelos tenant-owned; 12 FKs compuestas `DEFERRABLE INITIALLY DEFERRED`; username por instalación", "de236e9"],
        ["D-032", "QA hermético", "Valores production-like explícitos; corpus 159 verde en ambos órdenes", "4afd0c7"],
        ["D-012 / T-005", "Tool policy", "`ToolExecutor` deny-by-default, allowlist, financiera prohibida, auditoría", "4d97449"],
        ["D-021 / T-006", "Resiliencia", "Circuit breakers, outbox durable con DLQ, captura GHL reencolada", "3733bad"],
        ["D-035 / T-007", "Webhook crash recovery", "Checkpoint del resultado tras efecto externo; resume en takeover", "5a3edf8"],
        ["D-010 / T-008", "GHL reconciliación", "Búsqueda previa al efecto (referencias + notas); DLQ para leads sin referencia", "ce2723c"],
        ["D-020 / T-009", "RAG clasificación", "public/internal/confidential/restricted + ACL deny-by-default + DLP determinista", "0541650"],
        ["D-017 / T-010", "Dependencias", "Pillow 12.x, pypdf 6.x, Vite ^7; `audit_dependencies.py`", "7fb4f45"],
        ["D-028 / T-011", "Observabilidad", "Middleware JSON correlacionado; métricas Prometheus; alertas in-memory", "af53b8b"],
        ["D-029 / T-012", "Lifecycle", "`LifecycleService` con export/erase/legal hold; modelo `InstallationLifecycle`", "ff0eed8"],
        ["D-026/D-027 / T-013", "Portal + docs", "README reescrito, banners SUPERSEDED, secciones reales, vitest+axe runner", "33d77c1"],
        ["D-030 / T-014", "Quality gates", "`quality_gates.py` con trinquete y baseline visible", "ca73a6c"],
        ["D-015/D-016", "Backup / restore / rollback", "`backup.py` con manifiesto y sha256; restauración real en SQLite y PostgreSQL efímero", "6b34200"],
        ["T-015 (Lote 1)", "Automatizaciones FlowWink", "router email local, quote-expiry, dunning, generate-invoice-pdf, send-webhook HMAC, sweep", "bf647cf"],
        ["T-017 (Lote 2)", "Agentes/IA FlowWink", "`docs_chat` extractivo con citas, abstención por ACL, sin LLM real", "59558a1"],
        ["D-009 (preflight)", "Puertos", "Preflight atómico en `provision-client.{sh,ps1}`", "19e7f71"],
        ["D-022", "Validación estricta", "`validate_runtime_security` rechaza SQLite/CORS/DEBUG/secretos/mocks/demo", "6c689da"],
        ["D-008/D-025", "Runtime infra", "Proxy SETUID, upstreams opcionales con resolución perezosa, `deploy.resources` por servicio", "f6137e0"],
        ["Ruta A — Chat sin Chatwoot", "Webhook degrada a canal interno auditado; E2E chat→lead→presupuesto reproducible", "c2f4b84"],
        ["Mejora catalog_overview", "Chat cae a resumen de catálogo PrestaShop en preguntas genéricas", "post c2f4b84"],
    ]
    story.append(make_table(rows, [2.4 * cm, 2.8 * cm, 8.6 * cm, 2.2 * cm]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(p("4.1 Cobertura de pruebas", styles["h2"]))
    rows = [
        ["Métrica", "Valor"],
        ["Corpus combinado verde", "245 / 245 en ambos órdenes de colección"],
        ["Reproducciones rojas conservadas como evidencia histórica", "19 tests"],
        ["Verificador PostgreSQL efímero", "Concurrencia P0, adopción histórica, downgrade/reupgrade, modo -O"],
        ["Migraciones herméticas", "23 verde"],
        ["Portal (vitest + testing-library + vitest-axe)", "5 verde"],
        ["E2E reproducible sin externos", "scripts/e2e_core_chat_to_quote.py verde (cuota 136,00)"],
        ["Smoke por proxy en runtime", "200 OK portal / api / flowwink"],
    ]
    story.append(make_table(rows, [10.5 * cm, 6.5 * cm]))
    story.append(PageBreak())
    return story


def section_5_pending_work(styles) -> list:
    story = []
    story.append(p("5. Lo que falta para completarlo (trabajo pendiente)", styles["h1"]))
    story.append(
        p(
            "Trabajo que el equipo autónomo todavía no puede cerrar sin colaboración "
            "del propietario o sin recursos externos. La numeración corresponde a las "
            "tareas abiertas registradas en <font face='Courier'>TASKS.md</font> y a "
            "los defectos pendientes de <font face='Courier'>docs/audit/18_DEFECT_REGISTER.md</font>.",
            styles["body"],
        )
    )

    story.append(p("5.1 P1 / Wave 2 (runtime y sandboxes)", styles["h2"]))
    for t in [
        "P1-001 (D-006) Egress: red egress separada + allowlist DNS/IP; verificación de conectividad por destino.",
        "P1-002 (D-007) Chatwoot: entrypoint que valide/elimine PID stale; graceful shutdown; soak 10 reinicios.",
        "P1-003 (D-008) Proxy: smoke runtime con `docker inspect` + `setuid EPERM` ausente tras reboot.",
        "P1-005 (D-013) Activepieces: exigir `execution_id` real o fallar; contrato y test de 2xx sin ID.",
        "P1-006 (D-011) Aprobaciones: CAS condicional o versionado; concurrency test con dos transacciones ganadoras.",
        "P1-007 (D-014) Costes IA: tarifario versionado, usage real contra el proveedor, hard limit y eval de presupuesto.",
        "P1-008 (D-015) Restore end-to-end en instalación vacía con flujos completos + medición RPO/RTO.",
        "P1-009 (D-016) Release: imágenes inmutables por digest; rollback aplicado a una release candidate.",
        "P1-013 (D-033) PrestaShop >500 reglas: paginación a EOF y rechazo de snapshots incompletos.",
        "P1-014 (D-034) PrestaShop visibilidad: aplicar `show_price`/`available_for_order` en adapter/servicio/chat.",
        "P1-016 (D-036) Importación: Idempotency-Key + dato+audit/outbox transaccional; fault injection con replay.",
    ]:
        story.append(bullet(t, styles))

    story.append(p("5.2 Fases todavía sin cerrar", styles["h2"]))
    for t in [
        "F04-05 — Cancelación del runner, kill switch de agente y costes LLM reales.",
        "F06-11 — E2E local de chat/CRM/catálogo/presupuestos/pedidos/facturación contra proveedor local.",
        "F12-18 — Wiki, SEO, landing pages y engine de automatizaciones adicionales; aprobación obligatoria para publicación.",
        "F19-20 — E2E visual del portal en viewports y matriz completa de RBAC en backend.",
        "F22 — OTel/Prometheus scrape y SLO formales.",
        "F23 — Perfil full/production estable con reinicios repetidos desde volúmenes nuevos.",
        "F24 — Restore completo + RPO/RTO medidos en la release.",
        "F25 — Pipeline autoritativo con gates, digests, SBOM y release notes.",
        "F26 — Suite de QA completa: contract/E2E/RAG exfil a escala real.",
        "F27 — Rendimiento: capacity test para 1/5/10/25/50 instalaciones.",
        "F28 — SBOM y revisión legal/comercial de la release.",
        "F29 — Lint doc/link/claims automatizado contra la candidata.",
    ]:
        story.append(bullet(t, styles))

    story.append(p("5.3 Operaciones y gobierno pendientes", styles["h2"]))
    for t in [
        "Política de retención de datos revisada por legal (B-008).",
        "Decisión sobre redistribución del binario y rutas EE del vendor (B-008).",
        "Decisión sobre uso de sandbox de PrestaShop y credenciales reales (B-003).",
        "Subcuenta sandbox de GHL (B-004) para cerrar D-010 live.",
        "Proveedor LLM autorizado o claves sandbox (B-006) para tool calling y costes.",
        "Aprovisionamiento de Chatwoot con inbox y widget (B-005).",
        "Host dimensionado para build limpio + soak del perfil full (B-001).",
        "Definición y aprobación de la release candidata: tag SemVer, digests, SBOM y release notes.",
    ]:
        story.append(bullet(t, styles))
    story.append(PageBreak())
    return story


def section_6_how_to_fix(styles) -> list:
    story = []
    story.append(p("6. Cómo solucionarlo (plan técnico)", styles["h1"]))
    story.append(
        p(
            "Plan operativo para mover la decisión a PRODUCTION READY WITH "
            "DOCUMENTED LIMITATIONS. Se organiza en tres ejes paralelos: "
            "(A) cerrar runtime, (B) cerrar release, (C) cerrar gobierno.",
            styles["body"],
        )
    )

    story.append(p("6.1 Eje A — Cerrar runtime y sandboxes", styles["h2"]))
    rows = [
        ["#", "Acción", "Entregable", "Criterio de cierre"],
        ["A1", "Habilitar egress por defecto y allowlist por dominio/IP", "Red `egress` en compose, política DNS, smoke a destinos autorizados", "DNS/SSRF/connectivity verde"],
        ["A2", "Estabilizar Chatwoot", "Entrypoint que sanea `tmp/pids` y graceful shutdown", "10 reboots/recreates sanos"],
        ["A3", "Smoke runtime del proxy y límites", "`docker inspect`, `setuid EPERM` ausente, `deploy.resources` aplicado", "Worker count >0 y `health` 200 tras reboot"],
        ["A4", "Contrato Activepieces estricto", "Adapter exige `execution_id` o falla con error explícito", "2xx sin ID → error; test verde"],
        ["A5", "CAS en aprobaciones", "Transición condicional por versión + lock", "Approve+Reject concurrentes ⇒ un ganador"],
        ["A6", "Costes LLM reales", "Tarifario versionado, usage real, hard limit", "Presupuesto corta ejecución"],
        ["A7", "Restore end-to-end en instalación vacía", "Script + manifiesto + smoke E2E", "RPO/RTO medidos y firma verificada"],
        ["A8", "PrestaShop paginación y visibilidad", "Adapter EOF + flags `show_price`/`available_for_order` aplicados", "Regla 501 contribuye; precio 999 no expuesto"],
        ["A9", "Importación idempotente", "Idempotency-Key + dato+audit/outbox transaccional", "Retry con respuesta perdida ⇒ una entidad"],
    ]
    story.append(make_table(rows, [1 * cm, 5.4 * cm, 6 * cm, 4.6 * cm]))

    story.append(p("6.2 Eje B — Cerrar release", styles["h2"]))
    rows = [
        ["#", "Acción", "Entregable", "Criterio de cierre"],
        ["B1", "Definir release candidate", "Tag SemVer, digests inmutables, SBOM CycloneDX, checksums", "release/production-candidate/ completo"],
        ["B2", "Pipeline CI/CD", "Lint + typecheck + tests + pip-audit + npm audit + image scan + smoke", "Pipeline verde y reproducible"],
        ["B3", "Perfiles endurecidos", "core, chat, automation, full, dev, test, staging, production", "Arranque repetido del perfil production con smoke"],
        ["B4", "Rollback probado", "Imagen previa + Alembic compatible + script", "Rollback aplicado sobre release versionada"],
        ["B5", "Build limpio reproducible", "Build `--no-cache --pull` en host dimensionado", "Tiempos, hashes y smoke firmados"],
    ]
    story.append(make_table(rows, [1 * cm, 5.4 * cm, 6 * cm, 4.6 * cm]))

    story.append(p("6.3 Eje C — Cerrar gobierno y producto", styles["h2"]))
    rows = [
        ["#", "Acción", "Entregable", "Criterio de cierre"],
        ["C1", "Portal E2E visual y a11y", "Playwright en viewports light/dark; axe", "Capturas y asserts por sección"],
        ["C2", "RBAC completo", "Matriz rutas/recursos/tenants + service accounts", "Tests por rol sensible"],
        ["C3", "Licencias y SBOM", "Matriz final, notices, revisión legal", "Aprobación legal de la release"],
        ["C4", "OTel / Prometheus / SLO", "Collector, dashboards, alertas con umbral", "Fault injection dispara alerta y SLO mide"],
        ["C5", "Onboarding / manuales", "ADMIN, USER, TROUBLESHOOTING", "Instalación nueva < proceso documentado >"],
        ["C6", "Política de retención revisada", "DPA + borrado + legal hold", "Aprobación por DPO/legal"],
    ]
    story.append(make_table(rows, [1 * cm, 5.4 * cm, 6 * cm, 4.6 * cm]))

    story.append(Spacer(1, 0.4 * cm))
    story.append(p("6.4 Secuencia propuesta (8 semanas)", styles["h2"]))
    for t in [
        "Semana 1: A1, A2, A3, B1, B2 — desbloquean runtime y release.",
        "Semana 2: A4, A5, A6, B3 — cierran integraciones críticas.",
        "Semana 3: A7, A8, A9, B4 — cierran DR, PrestaShop e idempotencia.",
        "Semana 4: B5, C1, C2 — build reproducible y portal/RBAC.",
        "Semana 5: C3, C4 — licencias y observabilidad operativa.",
        "Semana 6: C5, C6 — onboarding, manuales y política de retención.",
        "Semana 7: Soak perfil full, restore medido, simulacro de incidente.",
        "Semana 8: Aceptación de release candidate y emisión de la decisión final.",
    ]:
        story.append(bullet(t, styles))
    story.append(PageBreak())
    return story


def section_7_blockers(styles) -> list:
    story = []
    story.append(p("7. Bloqueos externos y dependencias", styles["h1"]))
    story.append(
        p(
            "Los bloqueos se documentan en <font face='Courier'>BLOCKERS.md</font>. "
            "Ninguno autoriza mocks de producción ni respuestas sintéticas; cada "
            "adaptador debe ofrecer error explícito y permitir continuar con un "
            "proveedor local.",
            styles["body"],
        )
    )
    rows = [
        ["ID", "Área", "Bloqueo", "Trabajo que continúa mientras tanto"],
        ["B-001", "Recursos", "Host al 87,7 % de RAM en baseline; build previo >95 %; margen real pendiente", "Código, tests aislados, compose y docs"],
        ["B-002", "Git/procedencia", "Entrega original sin `.git` ni metadata vendor", "Git local y commits nuevos"],
        ["B-003", "PrestaShop", "Sin sandbox/credenciales autorizadas ni versión declarada", "Contratos P0 verdes; fail-closed; D-033/D-034"],
        ["B-004", "GHL", "Sin subcuenta sandbox/credenciales", "Local CRM, outbox y contratos"],
        ["B-005", "Chatwoot", "Sin inbox/widget configurado; runtime roto", "Chat interno y contract tests"],
        ["B-006", "IA externa", "Sin proveedor/modelo autorizado y sin egress", "Provider local real, schemas y evals"],
        ["B-007", "DR", "No existe restore completo reproducido en instalación vacía con flujos", "Mejorar scripts, manifiestos y tests estáticos"],
        ["B-008", "Legal", "Código propio sin licencia raíz y rutas EE presentes en vendor", "SBOM, notices y matriz técnica"],
    ]
    story.append(make_table(rows, [1.5 * cm, 2.4 * cm, 6.2 * cm, 6.9 * cm]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(
        p(
            "<b>Mitigación B-001</b> (2026-08-03): se detuvieron los compose projects "
            "<font face='Courier'>agent-platform</font>, <font face='Courier'>agent-piloto-rc1</font> y "
            "<font face='Courier'>agent-cliente-demo-es-staging</font>; volúmenes intactos y "
            "puerto 9000 liberado. Pendiente medir margen real tras liberar la VM Docker.",
            styles["body"],
        )
    )
    story.append(PageBreak())
    return story


def section_8_production_criteria(styles) -> list:
    story = []
    story.append(p("8. Lo que falta para producción (30 criterios PR-)", styles["h1"]))
    story.append(
        p(
            "La matriz de 30 criterios (<font face='Courier'>docs/PRODUCTION_READINESS.md</font>) "
            "marca todos los criterios como <font face='Courier'>BLOCKED</font>. La "
            "decisión no se promueve a PRODUCTION READY hasta que todos pasen a "
            "<font face='Courier'>VERIFIED</font> con evidencia actual, reproducible y "
            "contra la candidata identificada por versión y hash.",
            styles["body"],
        )
    )

    rows = [
        ["ID", "Criterio", "Estado", "Qué falta"],
        ["PR-01", "Cero defectos P0 abiertos", "BLOCKED", "Candidata y no regresión P0"],
        ["PR-02", "P1 críticos del núcleo corregidos", "BLOCKED", "Cerrar 9 P1 runtime"],
        ["PR-03", "Sin mocks en producción", "BLOCKED", "Build/arranque production sin fallback sintético"],
        ["PR-04", "Sin datos demo visibles", "BLOCKED", "Revalidar rutas cliente en candidata"],
        ["PR-05", "Aislamiento entre clientes probado", "BLOCKED", "Archivos, RAG y E2E completo"],
        ["PR-06", "Confirmaciones seguras", "BLOCKED", "Chat→quote→confirmación visible + fault injection live (B-004)"],
        ["PR-07", "Migraciones no destructivas", "BLOCKED", "Rollback release con backup/restore"],
        ["PR-08", "Cálculos deterministas", "BLOCKED", "Sandbox autorizado + golden cases"],
        ["PR-09", "Operaciones idempotentes", "BLOCKED", "Activepieces e importación con fault injection"],
        ["PR-10", "Permisos efectivos en backend", "BLOCKED", "Matriz RBAC completa"],
        ["PR-11", "Stack production arrancando limpio", "BLOCKED", "Perfil full/production desde volúmenes nuevos"],
        ["PR-12", "Servicios esenciales funcionales", "BLOCKED", "Smoke E2E del perfil full con egress"],
        ["PR-13", "Tests críticos aprobados", "BLOCKED", "Suite P1 runtime + E2E candidata"],
        ["PR-14", "E2E principales aprobados", "BLOCKED", "E2E chat, comercio, Chatwoot, PrestaShop, GHL, Portal, restore"],
        ["PR-15", "Backup restaurado", "BLOCKED", "RPO/RTO medidos en instalación vacía"],
        ["PR-16", "Rollback probado", "BLOCKED", "Aplicación + esquema en release versionada"],
        ["PR-17", "Agentes limitados a herramientas autorizadas", "BLOCKED", "Cancelación del runner (F04-05)"],
        ["PR-18", "Facturación automática desactivada", "BLOCKED", "Production fail-closed + E2E"],
        ["PR-19", "Publicaciones con aprobación", "BLOCKED", "Política común + E2E aislado"],
        ["PR-20", "RAG aislado y con citas", "BLOCKED", "Sandbox RAG real (B-006) + exfil a escala"],
        ["PR-21", "Logs y métricas operativos", "BLOCKED", "OTel/Prometheus scrape + SLO"],
        ["PR-22", "Sin secretos en repositorio", "BLOCKED", "Escaneo de historial y artefacto"],
        ["PR-23", "Licencias revisadas", "BLOCKED", "Revisión legal/comercial"],
        ["PR-24", "Documentación coherente", "BLOCKED", "Lint doc/links automatizado"],
        ["PR-25", "Instalación limpia reproducible", "BLOCKED", "Build desde host dimensionado"],
        ["PR-26", "Release versionada", "BLOCKED", "Tag, digests, checksums, SBOM, release notes"],
        ["PR-27", "Sistema funcional sin PrestaShop/GHL", "BLOCKED", "Proveedores locales + E2E interno"],
        ["PR-28", "Proveedores externos desacoplados", "BLOCKED", "Tests contractuales de sustitución"],
        ["PR-29", "Portal probado visualmente", "BLOCKED", "E2E visual/funcional + a11y"],
        ["PR-30", "Límites y alertas configurados", "BLOCKED", "Soak con carga del perfil full"],
    ]
    story.append(make_table(rows, [1.5 * cm, 5 * cm, 2 * cm, 8.5 * cm]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(
        p(
            "<b>Resultado:</b> 0/30 VERIFIED. Esta es la causa directa de la decisión "
            "<b>NOT PRODUCTION READY — CRITICAL RISK</b>. Cambiar la decisión exige "
            "una candidata identificada por versión y hash y evidencia actual contra "
            "cada fila.",
            styles["body"],
        )
    )
    story.append(PageBreak())
    return story


def section_9_risks(styles) -> list:
    story = []
    story.append(p("9. Riesgos críticos y residuales", styles["h1"]))
    story.append(
        p(
            "Resumen del registro de riesgos (<font face='Courier'>docs/audit/19_RISK_REGISTER.md</font>). "
            "Tres riesgos están clasificados como <b>stop-ship</b>.",
            styles["body"],
        )
    )
    rows = [
        ["ID", "Riesgo", "Nivel", "Mitigación"],
        ["R-01", "Oferta/pedido con datos demo o precio/stock erróneo", "Crítico", "Gating de procedencia + autoridad PrestaShop"],
        ["R-02", "Pedido sin consentimiento por parser textual", "Crítico", "State machine + confirmación explícita"],
        ["R-04", "Pérdida / no recuperación de datos", "Crítico", "DR consistente + restore ensayado"],
        ["R-03", "Integraciones principales inaccesibles", "Alto", "Egress allowlist + sandboxes"],
        ["R-05", "Duplicados GHL/transacciones por retry", "Alto", "Outbox / idempotency / reconcile"],
        ["R-06", "Agotamiento de host por vendor/loops/build", "Alto", "Límites, aislar hosts, retirar vendor"],
        ["R-07", "Exposición documental RAG", "Alto", "Deny-by-default / DLP / evals"],
        ["R-08", "Coste LLM incontrolado", "Alto", "Hard budgets / telemetría / kill switch"],
        ["R-09", "Incidentes invisibles", "Alto", "Observabilidad / SLO / runbook"],
        ["R-10", "Licencia EE / propiedad intelectual", "Alto", "Legal, exclusión y SBOM"],
        ["R-11", "CVE en parser/upload/supply chain", "Alto", "Pin / update / scan / sign"],
        ["R-12", "Actualización rompe todas las instancias", "Alto", "Imágenes inmutables por cliente"],
        ["R-13", "Acceso cruzado por misconfiguración", "Alto", "Preflight IDs, guards y test de aislamiento"],
        ["R-14", "Producto vendido por encima de capacidad", "Alto", "Catálogo contractual y acceptance matrix"],
        ["R-15", "Coste operativo no escalable", "Alto", "Simplificar MVP y control plane gradual"],
        ["R-16", "Privacidad / retención incumplida", "Alto", "Data lifecycle y asesoría legal"],
    ]
    story.append(make_table(rows, [1.2 * cm, 6.5 * cm, 1.8 * cm, 7.5 * cm]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(
        p(
            "Ningún riesgo se acepta por defecto; la aceptación residual exige "
            "responsable y fecha. Los riesgos R-01/R-02/R-04 son <b>stop-ship</b>.",
            styles["body"],
        )
    )
    story.append(PageBreak())
    return story


def section_10_roadmap(styles) -> list:
    story = []
    story.append(p("10. Roadmap 30/60/90 y release candidata", styles["h1"]))
    story.append(p("10.1 Días 0–30: MVP mínimo", styles["h2"]))
    rows = [
        ["Semana", "Entregable", "Exit gate parcial"],
        ["1", "D-001/002/005/006/007/008/009/022/025 + dependency triage", "Sin demo expuesto, stack estable tras reboot"],
        ["2", "Ownership, state machine, price/stock snapshot, contratos sandbox", "Confirmación segura con token; golden cases"],
        ["3", "GHL outbox/idempotencia, Chatwoot handoff, suite PostgreSQL/concurrencia", "Sin duplicados en retry; cero oversell"],
        ["4", "E2E Ofideep, backup+restore aislado, telemetría/alertas mínima, portal recortado", "Restore medido; alertas en fault injection"],
    ]
    story.append(make_table(rows, [2 * cm, 8 * cm, 7 * cm]))
    story.append(Spacer(1, 0.3 * cm))

    story.append(p("10.2 Días 31–60: producto repetible y operable", styles["h2"]))
    rows = [
        ["Bloque", "Entregable", "Exit gate parcial"],
        ["CI/release", "Quality/security gates, locks/digests/SBOM, releases firmadas", "Pipeline reproducible"],
        ["Operación", "Provision/update/rollback por cliente sin checkout global", "Rollback probado por release"],
        ["Multi-instancia", "Dos instalaciones: aislamiento negativo, backups separados, export/delete", "Aislamiento cruzado verificado"],
        ["Observabilidad", "SLO, runbooks, alertas por fault injection", "Alertas verificables"],
        ["RAG", "Corpus ficticio, ACL, DLP y evals de exfil", "Sin fuga"],
        ["UX", "Playwright light/dark + viewports + axe", "E2E accesible"],
        ["Legal", "Licencia propia, NOTICE, DPA/retención", "Aprobación legal"],
    ]
    story.append(make_table(rows, [2.5 * cm, 8 * cm, 6.5 * cm]))
    story.append(Spacer(1, 0.3 * cm))

    story.append(p("10.3 Días 61–90: piloto controlado", styles["h2"]))
    rows = [
        ["Bloque", "Entregable"],
        ["Capacidad", "Capacity test seguro y modelo de coste por cliente"],
        ["Operación", "Runbook de go-live/rollback, ventana, backups, soporte y escalado"],
        ["KPI", "Conversión, handoff, error, abstención, coste; sin centralizar contenido privado"],
        ["Onboarding", "Formación de operación/cliente y materiales"],
        ["Riesgos", "Revisión seguridad/legal y aceptación de riesgos residuales"],
        ["Simulacro", "Incidente + restore"],
    ]
    story.append(make_table(rows, [3 * cm, 14 * cm]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(
        p(
            "<b>Exit gate día 90:</b> GO WITH CONDITIONS — CONTROLLED PILOT solo si: "
            "(1) sin datos demo/precio/stock inventado, (2) sin pedido/factura no "
            "consentida, (3) PrestaShop/GHL/Chatwoot verificados E2E, (4) backup "
            "restaurado, (5) Auth/RBAC/aislamiento y security baseline pasan, "
            "(6) alertas/kill switches operativos y (7) legal/licencias/privacidad "
            "aprobados.",
            styles["body"],
        )
    )
    story.append(PageBreak())
    return story


def section_11_recommendations(styles) -> list:
    story = []
    story.append(p("11. Recomendaciones finales", styles["h1"]))
    story.append(p("11.1 Decisión de gestión", styles["h2"]))
    for t in [
        "Mantener la decisión NOT PRODUCTION READY — CRITICAL RISK hasta cerrar los 9 P1 de runtime y verificar 30/30 criterios.",
        "No iniciar piloto de cliente ni facturar hasta que la release candidata supere el exit gate del día 90.",
        "Publicar este informe como fuente única de comunicación con stakeholders; marcar SUPERSEDED cualquier informe previo.",
    ]:
        story.append(bullet(t, styles))

    story.append(p("11.2 Decisión técnica", styles["h2"]))
    for t in [
        "Asignar 1 backend senior/arquitecto + 1 DevOps/SRE + 1 QA automation + 0,5 frontend/UX según el plan 30/60/90.",
        "Priorizar A1–A9 (runtime) sobre nuevas funcionalidades; cualquier avance posterior sin runtime verde es deuda.",
        "No añadir más defectos P0/P1 sin evidencia reproducible; exigir test rojo antes de FIXED.",
        "Endurecer CI con quality gates (D-030) y auditor de dependencias (D-017) en cada PR.",
        "Mantener el desglose por defecto `Ruta A — candidata core con limitaciones documentadas`; no introducir Kubernetes salvo necesidad demostrada.",
    ]:
        story.append(bullet(t, styles))

    story.append(p("11.3 Decisión operativa", styles["h2"]))
    for t in [
        "Solicitar formalmente las sandboxes externas (PrestaShop, GHL, Chatwoot, IA) y un host dimensionado para build/soak.",
        "Activar B-008 (revisión legal) en cuanto se cierre la candidata para evitar bloqueo tardío.",
        "Definir el calendario de capacity test para 1/5/10/25/50 instalaciones cuando esté liberado el perfil full.",
        "Documentar runbooks de incidente, restore y rollback antes del primer piloto.",
    ]:
        story.append(bullet(t, styles))

    story.append(p("11.4 Decisión de comunicación", styles["h2"]))
    for t in [
        "Comunicar a ventas y preventa: la plataforma no se vende hasta nuevo aviso.",
        "Comunicar a soporte: la base de conocimiento interna se mantiene con SUPERSEDED; las instrucciones vivas están en docs/PRODUCTION_READINESS.md.",
        "Establecer cadencia semanal de revisión de STATUS.md y TASKS.md hasta el cierre de la Wave 2.",
    ]:
        story.append(bullet(t, styles))
    story.append(PageBreak())
    return story


def section_12_annex(styles) -> list:
    story = []
    story.append(p("12. Anexos: artefactos y referencias", styles["h1"]))

    story.append(p("12.1 Documentos autoritativos", styles["h2"]))
    for t in [
        "AGENTS.md — misión maestra y reglas innegociables de producción.",
        "TASKS.md — tareas con fase, prioridad, evidencia, commit y dependencias.",
        "STATUS.md — estado verificable del proyecto, fase activa, corpus y commits.",
        "DECISIONS.md — decisiones D-001 a D-035 (Ruta A, scope, dependencias).",
        "BLOCKERS.md — bloqueos B-001 a B-008 y trabajo que continúa.",
        "CHANGELOG.md — bitácora de cambios de la remediación.",
        "docs/PRODUCTION_READINESS.md — única fuente de la decisión de readiness.",
        "docs/PRODUCTION_REMEDIATION_PLAN.md — plan completo de remediación.",
        "docs/TEST_EVIDENCE.md — evidencia de pruebas.",
        "docs/KNOWN_LIMITATIONS.md — limitaciones conocidas.",
        "docs/ARCHITECTURE.md y docs/SECURITY.md — arquitectura y seguridad.",
        "docs/baseline/, docs/remediation/, docs/audit/ — baseline, reproducción y auditoría técnica.",
        "docs/LICENSE_MATRIX.md, THIRD_PARTY_NOTICES.md, LICENSE — licencia y notices.",
    ]:
        story.append(bullet(t, styles))

    story.append(p("12.2 Scripts operativos", styles["h2"]))
    for t in [
        "scripts/provision-client.{sh,ps1} — aprovisiona una instalación cliente (incluye preflight atómico de puertos).",
        "scripts/rollback-client.{sh,ps1} — rollback por cliente.",
        "scripts/update-client.{sh,ps1} — actualiza por cliente.",
        "scripts/backup-restore-integral.{sh,ps1} — backup/restore integral.",
        "scripts/check-health.{sh,ps1} — comprobación de salud.",
        "scripts/quality_gates.py — tres puertas de calidad (hard/clean/ratchet).",
        "scripts/audit_dependencies.py — pip-audit + npm audit.",
        "scripts/e2e_core_chat_to_quote.py — E2E reproducible del flujo chat→presupuesto.",
        "scripts/configure-chatwoot-webhook.py — configura el webhook de Chatwoot.",
        "scripts/setup-agents-and-workflows.py — siembra agentes y workflows.",
        "scripts/render_status_report.py — renderizador del STATUS.",
    ]:
        story.append(bullet(t, styles))

    story.append(p("12.3 Métricas de evidencia", styles["h2"]))
    rows = [
        ["Métrica", "Valor"],
        ["Commits de remediación", "≥35 en la rama production-remediation"],
        ["Corpus combinado de tests", "245 / 245 verde en ambos órdenes"],
        ["Reproducciones rojas conservadas", "19 tests"],
        ["Migraciones herméticas", "23 verde"],
        ["Portal vitest + axe", "5 verde"],
        ["P0 verificados", "6 / 6"],
        ["P1 verificados (Wave 1)", "20 / 29 (los 9 restantes son runtime)"],
        ["P2 verificados", "5 / 5"],
        ["Criterios PR- VERIFIED", "0 / 30"],
        ["Sandboxes externas", "Ninguna autorizada"],
    ]
    story.append(make_table(rows, [8 * cm, 9 * cm]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(p("12.4 Aviso final", styles["h2"]))
    story.append(
        p(
            "Cualquier documento previo a este informe queda <b>SUPERSEDED</b> para "
            "decisiones actuales. La única fuente válida para promover la decisión "
            "es la evaluación de una release candidata identificada por versión y "
            "hash contra los 30 criterios PR-, con evidencia actual y reproducible.",
            styles["body"],
        )
    )
    story.append(Spacer(1, 0.4 * cm))
    story.append(
        p(
            "<i>Generado el 2026-08-09 por ZCode (flujo autónomo de remediación) a "
            "partir de los registros autoritativos del workspace. Cualquier "
            "contradicción posterior debe actualizar este documento y registrar el "
            "cambio en CHANGELOG.md.</i>",
            styles["caption"],
        )
    )
    return story


# ----------------------------- Main --------------------------------------- #


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    styles = build_styles()
    doc = StatusDoc(str(OUTPUT_PDF))
    story: list = []
    story.extend(build_cover(styles))
    story.extend(build_toc(styles))
    story.extend(section_1_executive_summary(styles))
    story.extend(section_2_phases(styles))
    story.extend(section_3_failures(styles))
    story.extend(section_4_verified(styles))
    story.extend(section_5_pending_work(styles))
    story.extend(section_6_how_to_fix(styles))
    story.extend(section_7_blockers(styles))
    story.extend(section_8_production_criteria(styles))
    story.extend(section_9_risks(styles))
    story.extend(section_10_roadmap(styles))
    story.extend(section_11_recommendations(styles))
    story.extend(section_12_annex(styles))
    doc.build(story)
    print(f"PDF generated at: {OUTPUT_PDF}")
    print(f"Size: {OUTPUT_PDF.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())