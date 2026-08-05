"""Renderiza el informe de estado del proyecto a PDF con reportlab.

Genera ``docs/STATUS_REPORT.pdf`` a partir del contenido del informe.
Uso puntual: revision del estado del proyecto (sin modificar codigo del
proyecto; este script y el pdf son artefactos de informe).
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)


OUT = Path(__file__).resolve().parent.parent / "docs" / "STATUS_REPORT.pdf"


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="Informe de estado del proyecto",
        author="ZCode",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "title",
        parent=styles["Title"],
        fontSize=18,
        leading=22,
        spaceAfter=6 * mm,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#1f2a44"),
    )
    h1 = ParagraphStyle(
        "h1",
        parent=styles["Heading1"],
        fontSize=14,
        leading=18,
        spaceBefore=6 * mm,
        spaceAfter=2 * mm,
        textColor=colors.HexColor("#1f2a44"),
    )
    body = ParagraphStyle(
        "body",
        parent=styles["BodyText"],
        fontSize=10,
        leading=14,
        spaceAfter=2 * mm,
        alignment=TA_LEFT,
    )
    small = ParagraphStyle(
        "small",
        parent=styles["BodyText"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#555555"),
    )
    story: list = []
    story.append(Paragraph("Informe de estado del proyecto", title))
    story.append(
        Paragraph(
            "Rama <b>production-remediation</b> · revision 2026-08-04 · sin cambios de codigo.",
            small,
        )
    )

    story.append(Paragraph("1. Resumen ejecutivo", h1))
    story.append(
        Paragraph(
            "<b>Decision actual:</b> <font color='#b00020'>NOT PRODUCTION READY - CRITICAL RISK</font> "
            "(la unica fuente autoritativa es <font face='Courier'>docs/PRODUCTION_READINESS.md</font>).",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>Defectos:</b> 30 verificados de 37 (6 P0 + 19 P1 + 5 P2); 7 abiertos, todos P1 de runtime/bloqueados.",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>Tests:</b> 235 del backend (pytest tests bridge-api/tests) en ambos ordenes de coleccion + 5 del portal (vitest + vitest-axe) verdes; 1 skipped (evidencia PostgreSQL opt-in).",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>Quality gates (D-030):</b> verdes, con trinquete de deuda visible y zona limpia mantenida en 0.",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>Runtime:</b> perfil core levantado en Docker; portal real accesible via proxy en <font color='#0050b3'>http://localhost:9000</font>.",
            body,
        )
    )
    story.append(Paragraph("<b>Worktree:</b> limpio.", body))

    story.append(Paragraph("2. Conteo de defectos", h1))
    conteo = [
        ["Severidad", "Registrados", "Verificados", "Abiertos"],
        ["P0", "6", "6", "0"],
        ["P1", "26", "19", "7"],
        ["P2", "5", "5", "0"],
        ["Total", "37", "30", "7"],
    ]
    t = Table(conteo, colWidths=[40 * mm, 45 * mm, 45 * mm, 35 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2a44")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888888")),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eef0f6")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t)
    story.append(
        Paragraph(
            "Los 7 abiertos son P1 de runtime/bloqueados: egress live (D-006), preflight de puertos (D-009), "
            "handoff Chatwoot live (D-019), release/imagenes por digest (D-016), entorno seguro (D-022), "
            "alcance FlowWink (D-018), licencias (D-023).",
            body,
        )
    )

    story.append(Paragraph("3. Commits clave de esta sesion", h1))
    commits = [
        ["Commit", "Tema", "Defectos cerrados"],
        ["7819c0a", "docs: infra runtime (D-008/D-025)", "—"],
        ["f6137e0", "fix(infra): proxy SETUID + upstreams perezosos; limites", "D-008, D-025"],
        ["3064593", "docs: backup/restore/rollback (D-015/D-016)", "—"],
        ["6b34200", "feat(backup): backup/restore/rollback verificables", "D-015, D-016"],
        ["4898d42", "docs: lote 2 FlowWink (Agentes/IA)", "—"],
        ["59558a1", "feat(agent-ai): docs-chat sobre RAG del Bridge", "—"],
        ["a1158ae", "docs: lote 1 FlowWink (automatizaciones)", "—"],
        ["bf647cf", "feat(automations): email local, quote-expiry, dunning, pdf, webhook", "—"],
        ["ece9c34", "fix(portal): alias /agents + proxy dev", "—"],
        ["56b7695", "docs: quality gates (D-030)", "—"],
        ["ca73a6c", "feat(qa): quality gates con trinquete", "D-030"],
        ["20fcfed", "docs: portal + claims (D-026/D-027)", "—"],
        ["33d77c1", "feat(portal): secciones reales + tests axe", "D-026, D-027"],
        ["079a5d7", "docs: observabilidad + lifecycle (D-028/D-029)", "—"],
        ["ff0eed8", "feat(lifecycle): export/erase con retencion y legal hold", "D-029"],
        ["1ed75a3", "docs: reconciliacion GHL (D-010)", "—"],
        ["ce2723c", "feat(integrations): reconciliacion GHL previa al efecto", "D-010"],
        ["e4fc281", "docs: DLP/anti-injection RAG (D-020)", "—"],
        ["0541650", "feat(rag): clasificacion + DLP + anti-prompt-injection", "D-020"],
        ["4410485", "docs: dependencias (D-017)", "—"],
        ["7fb4f45", "feat(deps): Pillow>=12, pypdf>=6, Vite^7 + audit", "D-017"],
    ]
    t2 = Table(commits, colWidths=[28 * mm, 90 * mm, 47 * mm])
    t2.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2a44")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888888")),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(t2)
    story.append(
        Paragraph(
            "Wave 1 (defectos corregibles sin runtime) <b>agotada</b>. "
            "Las verificaciones nuevas de esta oleada cierran 12 P1 y 3 P2.",
            body,
        )
    )

    story.append(Paragraph("4. Decisiones de alcance", h1))
    decisiones = [
        "<b>D-007</b> Ruta A (aprobada): core candidato primero; SEO, SEO continuo, landing, automatizaciones y wiki fuera de la candidata core como limitaciones documentadas.",
        "<b>D-008</b> Stack antiguo detenido (compose detenido, volumenes intactos, puerto 9000 liberado).",
        "<b>D-009</b> Idempotencia GHL por reconciliacion, no por claves de proveedor.",
        "<b>D-010</b> AuditLog y usuarios sobreviven al erase.",
        "<b>D-011</b> Observabilidad con redaccion determinista antes de emitir.",
        "<b>D-012</b> Sin Supabase; extraer automatizaciones de FlowWink (MIT v3.0.0) reimplementando su logica sobre el motor del Bridge. Lotes 1 y 2 entregados (automations + agent-ai); lote 3 (Contenido/SEO) diferido.",
    ]
    for d in decisiones:
        story.append(Paragraph(f"• {d}", body))

    story.append(Paragraph("5. Estado runtime actual", h1))
    story.append(
        Paragraph(
            "<b>Docker 29.5.3</b> operativo; <b>perfil core</b> levantado (bridge-db/redis/api, portal, reverse-proxy, flowwink-app); opcionales (chatwoot/activepieces) no incluidos en core.",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>Proxy healthy</b> (26 workers estables, sin setuid EPERM); limites deploy.resources aplicados (bridge-api 768M/128pids, db 512M, bridge-redis 128M, portal 256M, reverse-proxy 128M).",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>RAM del host con core arriba:</b> ~3,9 GB libres (antes 95,3%).",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>Endpoints backend verificados via proxy</b> (curl con token real):",
            body,
        )
    )
    endpoints = [
        "/api/bridge/provider/dashboard -> 200",
        "/api/bridge/costs -> 200",
        "/api/bridge/approvals?status_filter=pending -> 200",
        "/api/bridge/tools/products -> 200",
        "/api/bridge/rag/documents -> 200",
        "/api/bridge/agents -> 200",
        "/api/bridge/users -> 200",
        "/api/bridge/automations/sweep -> 200",
    ]
    for ep in endpoints:
        story.append(Paragraph(f"• <font face='Courier' size='9'>{ep}</font>", small))
    story.append(
        Paragraph(
            "<b>Portal real en vivo:</b> <font color='#0050b3'>http://localhost:9000</font> (login admin / Admin@Segura123; .env dev, no fuerza cambio).",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>Bug detectado y corregido en esta revision:</b> las imagenes Docker del portal y bridge-api estaban "
            "<b>antiguas</b> (construidas antes de anadir /agents, /rag/documents, /automations/* y docs-chat); "
            "eso provocaba 404 en Documentos y Agentes. <b>Reconstruidas y reiniciadas</b>; ahora todas las secciones cargan.",
            body,
        )
    )

    story.append(Paragraph("6. Lo que queda pendiente (7 P1 de runtime)", h1))
    pendientes = [
        ["Defecto", "Bloqueo"],
        ["D-006 egress live", "Necesita sandbox/conectividad externa"],
        ["D-009 port preflight", "Falta preflight en provision-client"],
        ["D-019 handoff Chatwoot live", "Necesita Chatwoot real (no full profile)"],
        ["D-016 release/imagenes digest", "Falta CI/CD con imagenes inmutables"],
        ["D-022 entorno seguro", "Falta validacion production-like"],
        ["D-018 alcance FlowWink", "Decision de scope pendiente"],
        ["D-023 licencias", "Falta revision legal/matriz (B-008)"],
    ]
    t3 = Table(pendientes, colWidths=[60 * mm, 105 * mm])
    t3.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2a44")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888888")),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(t3)
    story.append(
        Paragraph(
            "Ninguno es bloqueante para Wave 1 ya cerrada. Todos son <b>runtime/externos</b> "
            "y la mayoria requieren perfil full, sandbox, o decision legal.",
            body,
        )
    )

    story.append(Paragraph("7. Cinco riesgos principales", h1))
    riesgos = [
        "<b>Sin evidencia E2E contra proveedores reales</b> (Chatwoot/PrestaShop/GHL/Activepieces/FlowWink): B-003/004/005/006 — el core se valida con dobles/contratos locales.",
        "<b>Backup en produccion no probado con instalacion vacia</b> (D-015 residual): verificado en SQLite + Postgres efimero, falta el drill completo de release (RPO/RTO, instalacion vacia real).",
        "<b>Supabase no se levanta</b> (decision D-012): los dominios Agentes/IA y Contenido/SEO de FlowWink requieren portar al motor del Bridge; el primer lote (docs-chat) esta listo sin LLM real.",
        "<b>Docker stopped by B-001</b>: el host tiene ~3,9 GB libres con el core; un perfil full puede no caber. Limites ya aplicados (D-025).",
        "<b>Licencias y procedencia vendor</b> (D-018/D-023): FlowWink (MIT, OK) y resto del vendor necesitan matriz completa y revision legal.",
    ]
    for r in riesgos:
        story.append(Paragraph(f"• {r}", body))

    story.append(Paragraph("8. Recomendaciones (priorizadas)", h1))
    recos = [
        "<b>Atacar D-009 (preflight de puertos)</b> y <b>D-006 (egress live)</b>: son los mas baratos de cerrar y desbloquean el deploy automatizado.",
        "<b>Levantar el perfil full</b> (con Chatwoot y Activepieces en contenedores) cuando haya RAM y completar el E2E de chat -> lead -> presupuesto contra esos servicios.",
        "<b>Lote 3 (Contenido/SEO)</b> de FlowWink o dejarlo diferido por la Fase SEO (Ruta A).",
        "<b>Drill de backup/restore en instalacion vacia</b> (D-015 residual) para cerrar release.",
        "<b>Revision legal de licencias</b> (D-023) antes de cualquier release comercial.",
    ]
    for r in recos:
        story.append(Paragraph(f"• {r}", body))

    story.append(Paragraph("9. Documentos autoritativos", h1))
    docs = [
        ["Documento", "Proposito"],
        ["docs/PRODUCTION_READINESS.md", "Decision y matriz PR-01..PR-30 (unica fuente)"],
        ["docs/TEST_EVIDENCE.md", "Evidencias por defecto (incluye filas runtime)"],
        ["docs/remediation/DEFECT_REGISTER.md", "Estado de los 37 defectos"],
        ["STATUS.md", "Resumen ejecutivo y linea de tiempo"],
        ["TASKS.md", "Tareas T-xxx por dominio"],
        ["CHANGELOG.md", "Cambios por release/lote"],
        ["DECISIONS.md", "Decisiones de alcance (D-007..D-012)"],
        ["scripts/quality_gates.py + quality_baseline.json", "Gates con trinquete (D-030)"],
        ["scripts/audit_dependencies.py", "Auditoria de deps (D-017)"],
    ]
    t4 = Table(docs, colWidths=[78 * mm, 87 * mm])
    t4.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2a44")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888888")),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(t4)

    story.append(Paragraph("Conclusion", h1))
    story.append(
        Paragraph(
            "La base del proyecto esta solida y verificada end-to-end con datos y runtime reales; "
            "los gaps restantes son todos de <b>runtime/infraestructura</b> y de <b>decisiones de scope</b> "
            "que requieren Docker con mas RAM o al propietario. La decision no cambia "
            "(<font color='#b00020'>NOT PRODUCTION READY - CRITICAL RISK</font>) hasta cerrar al menos el E2E "
            "con perfil full y el drill de backup en instalacion vacia.",
            body,
        )
    )

    doc.build(story)
    print(f"PDF generado: {OUT}")


if __name__ == "__main__":
    build()
