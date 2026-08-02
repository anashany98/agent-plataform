from __future__ import annotations

import base64
import hashlib
import html
import math
import re
import shutil
import textwrap
import unicodedata
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    HRFlowable,
    Image,
    LongTable,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs"
SOURCE_MD = DOCS / "PROJECT_TECHNICAL_AUDIT.md"
OUTPUT_HTML = DOCS / "PROJECT_TECHNICAL_AUDIT.html"
OUTPUT_PDF = DOCS / "PROJECT_TECHNICAL_AUDIT.pdf"
AUDIT_DIR = DOCS / "audit"
DIAGRAM_DIR = AUDIT_DIR / "diagrams" / "rendered"
RELEASE_DIR = ROOT / "release" / "project-technical-audit"

NAVY = "#14253D"
BLUE = "#2878B5"
TEAL = "#1B8A82"
RED = "#B42318"
ORANGE = "#C7681A"
GREEN = "#217A4A"
INK = "#1D2939"
MUTED = "#667085"
PALE = "#F4F7FA"
LINE = "#D0D5DD"

ALLOWED_STATES = {
    "VERIFIED",
    "PARTIALLY VERIFIED",
    "IMPLEMENTED BUT NOT TESTED",
    "CONFIGURED ONLY",
    "MOCKED",
    "BROKEN",
    "NOT IMPLEMENTED",
    "BLOCKED",
    "NOT APPLICABLE",
}

STATE_CLASS = {
    "VERIFIED": "verified",
    "PARTIALLY VERIFIED": "partial",
    "IMPLEMENTED BUT NOT TESTED": "untested",
    "CONFIGURED ONLY": "configured",
    "MOCKED": "mocked",
    "BROKEN": "broken",
    "NOT IMPLEMENTED": "missing",
    "BLOCKED": "blocked",
    "NOT APPLICABLE": "na",
}


def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size)


PIL_REGULAR = "C:/Windows/Fonts/arial.ttf"
PIL_BOLD = "C:/Windows/Fonts/arialbd.ttf"


def draw_arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str = BLUE, width: int = 5) -> None:
    draw.line([start, end], fill=color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 18
    spread = math.pi / 7
    p1 = (end[0] - length * math.cos(angle - spread), end[1] - length * math.sin(angle - spread))
    p2 = (end[0] - length * math.cos(angle + spread), end[1] - length * math.sin(angle + spread))
    draw.polygon([end, p1, p2], fill=color)


def draw_box(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    title: str,
    subtitle: str = "",
    fill: str = "#FFFFFF",
    outline: str = BLUE,
    title_color: str = NAVY,
) -> None:
    draw.rounded_rectangle(xy, radius=18, fill=fill, outline=outline, width=4)
    x1, y1, x2, y2 = xy
    title_font = load_font(PIL_BOLD, 26)
    body_font = load_font(PIL_REGULAR, 20)
    title_lines = textwrap.wrap(title, width=max(12, int((x2 - x1) / 15))) or [title]
    body_lines = textwrap.wrap(subtitle, width=max(16, int((x2 - x1) / 11))) if subtitle else []
    lines = [(line, title_font, title_color) for line in title_lines] + [(line, body_font, MUTED) for line in body_lines]
    heights = [draw.textbbox((0, 0), line, font=font)[3] for line, font, _ in lines]
    total = sum(heights) + max(0, len(lines) - 1) * 5
    cursor = y1 + ((y2 - y1) - total) / 2
    for (line, font, color), height in zip(lines, heights):
        bbox = draw.textbbox((0, 0), line, font=font)
        width = bbox[2] - bbox[0]
        draw.text((x1 + ((x2 - x1) - width) / 2, cursor), line, font=font, fill=color)
        cursor += height + 5


def diagram_canvas(title: str, size: tuple[int, int]) -> tuple[PILImage.Image, ImageDraw.ImageDraw]:
    image = PILImage.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, size[0] - 8, size[1] - 8), radius=24, fill="white", outline=LINE, width=3)
    draw.text((38, 24), title, font=load_font(PIL_BOLD, 34), fill=NAVY)
    return image, draw


def build_current_diagram(path: Path) -> None:
    image, draw = diagram_canvas("Arquitectura actual observada", (1600, 650))
    user = (35, 275, 260, 375)
    proxy = (330, 275, 580, 375)
    nodes = {
        "portal": (700, 70, 1010, 145),
        "bridge": (700, 170, 1010, 245),
        "chatwoot": (700, 270, 1010, 345),
        "flowwink": (700, 370, 1010, 445),
        "activepieces": (700, 470, 1010, 545),
    }
    targets = {
        "bridge_db": (1230, 60, 1555, 145),
        "external": (1230, 190, 1555, 290),
        "chatwoot_db": (1230, 340, 1555, 425),
        "activepieces_db": (1230, 490, 1555, 575),
    }
    draw_arrow(draw, (user[2], 325), (proxy[0], 325), RED)
    for box in nodes.values():
        draw_arrow(draw, (proxy[2], 325), (box[0], (box[1] + box[3]) // 2), RED, 4)
    draw_arrow(draw, (nodes["bridge"][2], 207), (targets["bridge_db"][0], 102), ORANGE, 4)
    draw_arrow(draw, (nodes["bridge"][2], 207), (targets["external"][0], 240), RED, 4)
    draw_arrow(draw, (nodes["chatwoot"][2], 307), (targets["chatwoot_db"][0], 382), ORANGE, 4)
    draw_arrow(draw, (nodes["activepieces"][2], 507), (targets["activepieces_db"][0], 532), ORANGE, 4)
    draw_box(draw, user, "Cliente / operador", fill="#EEF6FC")
    draw_box(draw, proxy, "Nginx", "sin workers", fill="#FEE4E2", outline=RED, title_color=RED)
    draw_box(draw, nodes["portal"], "Portal", "build verificado", fill="#EEF6FC")
    draw_box(draw, nodes["bridge"], "Bridge API", "verificación parcial", fill="#FFF4E5", outline=ORANGE)
    draw_box(draw, nodes["chatwoot"], "Chatwoot Web", "restart loop", fill="#FEE4E2", outline=RED, title_color=RED)
    draw_box(draw, nodes["flowwink"], "FlowWink", "shell sin backend", fill="#FEE4E2", outline=RED, title_color=RED)
    draw_box(draw, nodes["activepieces"], "Activepieces", "sin flujos", fill="#FFF4E5", outline=ORANGE)
    draw_box(draw, targets["bridge_db"], "Bridge DB", "100 productos demo", fill="#FFF4E5", outline=ORANGE)
    draw_box(draw, targets["external"], "PrestaShop / GHL / IA", "sin egress ni credenciales", fill="#FEE4E2", outline=RED, title_color=RED)
    draw_box(draw, targets["chatwoot_db"], "Chatwoot DB", "0 filas de negocio", fill="#F4F7FA", outline=MUTED)
    draw_box(draw, targets["activepieces_db"], "Activepieces DB", "0 filas", fill="#F4F7FA", outline=MUTED)
    image.save(path, "PNG", optimize=True)


def build_recommended_diagram(path: Path) -> None:
    image, draw = diagram_canvas("Arquitectura recomendada para piloto controlado", (1600, 620))
    user = (35, 245, 250, 345)
    chat = (315, 245, 575, 345)
    bridge = (650, 215, 960, 375)
    presta = (1050, 70, 1300, 160)
    ghl = (1050, 205, 1300, 295)
    human = (1050, 340, 1300, 430)
    data = (1350, 70, 1565, 160)
    outbox = (1350, 205, 1565, 295)
    obs = (1350, 340, 1565, 430)
    portal = (650, 470, 960, 555)
    draw_arrow(draw, (user[2], 295), (chat[0], 295), TEAL)
    draw_arrow(draw, (chat[2], 295), (bridge[0], 295), TEAL)
    draw_arrow(draw, (bridge[2], 255), (presta[0], 115), TEAL)
    draw_arrow(draw, (bridge[2], 295), (ghl[0], 250), TEAL)
    draw_arrow(draw, (bridge[2], 335), (human[0], 385), TEAL)
    draw_arrow(draw, (presta[2], 115), (data[0], 115), BLUE, 4)
    draw_arrow(draw, (ghl[2], 250), (outbox[0], 250), BLUE, 4)
    draw_arrow(draw, (human[2], 385), (obs[0], 385), BLUE, 4)
    draw_arrow(draw, (805, portal[1]), (805, bridge[3]), BLUE, 4)
    draw_box(draw, user, "Cliente", fill="#E8F7F4", outline=TEAL)
    draw_box(draw, chat, "Chatwoot", "canal + asignación", fill="#E8F7F4", outline=TEAL)
    draw_box(draw, bridge, "Bridge orquestador", "state machine · policy · idempotencia", fill="#E8F7F4", outline=TEAL)
    draw_box(draw, presta, "PrestaShop", "precio y stock oficiales", fill="#EEF6FC", outline=BLUE)
    draw_box(draw, ghl, "GHL", "contacto + oportunidad", fill="#EEF6FC", outline=BLUE)
    draw_box(draw, human, "Equipo humano", "handoff asignado", fill="#EEF6FC", outline=BLUE)
    draw_box(draw, data, "DB / RAG", "snapshots + evidencia", fill="#F4F7FA", outline=MUTED)
    draw_box(draw, outbox, "Outbox / retry", "entrega verificable", fill="#F4F7FA", outline=MUTED)
    draw_box(draw, obs, "Observabilidad", "métricas + alertas", fill="#F4F7FA", outline=MUTED)
    draw_box(draw, portal, "Portal proveedor", "operación y aprobación", fill="#EEF6FC", outline=BLUE)
    image.save(path, "PNG", optimize=True)


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def inline_html(value: str) -> str:
    raw = value.strip()
    if raw in ALLOWED_STATES:
        return f'<span class="state {STATE_CLASS[raw]}">{raw}</span>'
    escaped = html.escape(value, quote=True)
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda match: f'<a href="{match.group(2)}">{match.group(1)}</a>',
        escaped,
    )
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)
    return escaped


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_table_separator(line: str) -> bool:
    cells = split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def markdown_to_html(markdown_text: str, current_diagram: Path, recommended_diagram: Path) -> str:
    lines = markdown_text.splitlines()
    headings = []
    for line in lines:
        match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if match:
            title = re.sub(r"[*`]", "", match.group(2))
            headings.append((len(match.group(1)), title, slugify(title)))

    toc = "".join(
        f'<a class="toc-l{level}" href="#{anchor}">{html.escape(title)}</a>'
        for level, title, anchor in headings
    )
    images = []
    for path in (current_diagram, recommended_diagram):
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        images.append(f"data:image/png;base64,{encoded}")

    body: list[str] = []
    i = 0
    mermaid_index = 0
    while i < len(lines):
        line = lines[i]
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            level = len(heading.group(1))
            title = re.sub(r"[*`]", "", heading.group(2))
            anchor = slugify(title)
            body.append(f'<h{level} id="{anchor}">{inline_html(heading.group(2))}</h{level}>')
            i += 1
            continue
        if line.startswith("```"):
            language = line[3:].strip()
            block: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            if language == "mermaid" and mermaid_index < len(images):
                caption = "Arquitectura actual observada" if mermaid_index == 0 else "Arquitectura recomendada"
                body.append(f'<figure><img src="{images[mermaid_index]}" alt="{caption}"><figcaption>{caption}</figcaption></figure>')
                mermaid_index += 1
            else:
                body.append(f'<pre><code class="language-{html.escape(language)}">{html.escape(chr(10).join(block))}</code></pre>')
            continue
        if re.fullmatch(r"\s*-{3,}\s*", line):
            body.append("<hr>")
            i += 1
            continue
        if line.startswith("|") and i + 1 < len(lines) and is_table_separator(lines[i + 1]):
            header = split_table_row(line)
            rows: list[list[str]] = []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(split_table_row(lines[i]))
                i += 1
            table_class = " master" if len(header) >= 8 else ""
            parts = [f'<div class="table-wrap"><table class="audit-table{table_class}"><thead><tr>']
            parts.extend(f"<th>{inline_html(cell)}</th>" for cell in header)
            parts.append("</tr></thead><tbody>")
            for row in rows:
                parts.append("<tr>")
                parts.extend(f"<td>{inline_html(cell)}</td>" for cell in row)
                parts.append("</tr>")
            parts.append("</tbody></table></div>")
            body.append("".join(parts))
            continue
        quote = re.match(r"^>\s?(.*)$", line)
        if quote:
            quote_lines = []
            while i < len(lines):
                quote_match = re.match(r"^>\s?(.*)$", lines[i])
                if not quote_match:
                    break
                quote_lines.append(quote_match.group(1))
                i += 1
            body.append(f"<blockquote>{inline_html(' '.join(quote_lines))}</blockquote>")
            continue
        bullet = re.match(r"^\s*[-*]\s+(.+)$", line)
        number = re.match(r"^\s*\d+\.\s+(.+)$", line)
        if bullet or number:
            ordered = bool(number)
            items = []
            pattern = r"^\s*\d+\.\s+(.+)$" if ordered else r"^\s*[-*]\s+(.+)$"
            while i < len(lines):
                item = re.match(pattern, lines[i])
                if not item:
                    break
                items.append(item.group(1))
                i += 1
            tag = "ol" if ordered else "ul"
            body.append(f"<{tag}>" + "".join(f"<li>{inline_html(item)}</li>" for item in items) + f"</{tag}>")
            continue
        if not line.strip():
            i += 1
            continue
        paragraph = [line.strip()]
        i += 1
        while i < len(lines):
            candidate = lines[i]
            if not candidate.strip() or re.match(r"^(#{1,3})\s+", candidate) or candidate.startswith("```") or candidate.startswith("|") or candidate.startswith(">") or re.match(r"^\s*([-*]|\d+\.)\s+", candidate):
                break
            paragraph.append(candidate.strip())
            i += 1
        body.append(f"<p>{inline_html(' '.join(paragraph))}</p>")

    css = f"""
    :root {{ --navy:{NAVY}; --blue:{BLUE}; --teal:{TEAL}; --red:{RED}; --ink:{INK}; --muted:{MUTED}; --pale:{PALE}; --line:{LINE}; }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{ margin:0; font-family:Arial,Helvetica,sans-serif; color:var(--ink); background:#eef2f6; line-height:1.55; }}
    .shell {{ display:grid; grid-template-columns:300px minmax(0,1fr); max-width:1600px; margin:auto; background:white; min-height:100vh; box-shadow:0 0 45px rgba(20,37,61,.14); }}
    nav {{ position:sticky; top:0; height:100vh; overflow:auto; padding:30px 24px; background:var(--navy); color:white; }}
    nav .brand {{ font-weight:700; font-size:20px; margin-bottom:6px; }}
    nav .decision {{ color:#fecdca; font-size:12px; letter-spacing:.08em; margin-bottom:22px; }}
    nav a {{ display:block; color:#dbe9f4; text-decoration:none; padding:5px 8px; border-radius:5px; font-size:13px; }}
    nav a:hover {{ background:rgba(255,255,255,.09); color:white; }}
    nav .toc-l1 {{ font-weight:700; }} nav .toc-l3 {{ padding-left:20px; font-size:12px; }}
    main {{ min-width:0; padding:58px clamp(34px,6vw,95px) 90px; }}
    h1 {{ color:var(--navy); font-size:40px; line-height:1.1; margin:0 0 34px; border-bottom:5px solid var(--teal); padding-bottom:22px; }}
    h2 {{ color:var(--navy); font-size:25px; margin:52px 0 18px; padding-top:8px; border-top:1px solid #e4e7ec; }}
    h3 {{ color:var(--blue); font-size:19px; margin-top:30px; }}
    p, li {{ max-width:1050px; }}
    blockquote {{ margin:24px 0; padding:17px 22px; background:#fff1f0; border-left:5px solid var(--red); color:#7a271a; font-weight:700; }}
    code {{ font-family:Consolas,monospace; font-size:.9em; background:#f2f4f7; border:1px solid #e4e7ec; border-radius:4px; padding:1px 4px; }}
    pre {{ overflow:auto; padding:18px; background:#101828; color:#f2f4f7; border-radius:8px; }} pre code {{ background:none; border:0; color:inherit; }}
    a {{ color:#1769a2; }}
    figure {{ margin:26px 0; padding:15px; border:1px solid var(--line); border-radius:10px; background:white; }}
    figure img {{ display:block; width:100%; height:auto; }} figcaption {{ text-align:center; color:var(--muted); font-size:12px; margin-top:8px; }}
    .table-wrap {{ overflow-x:auto; margin:18px 0 30px; border:1px solid var(--line); border-radius:8px; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }} th {{ background:var(--navy); color:white; text-align:left; padding:10px; vertical-align:top; }} td {{ padding:9px 10px; border-bottom:1px solid #e4e7ec; vertical-align:top; }} tr:nth-child(even) td {{ background:#f8fafc; }}
    table.master {{ min-width:1500px; font-size:11px; }} table.master td, table.master th {{ padding:7px; }}
    .state {{ display:inline-block; white-space:nowrap; font-size:10px; font-weight:700; letter-spacing:.03em; padding:3px 6px; border-radius:999px; background:#eaecf0; }}
    .state.verified {{ color:#05603a; background:#d1fadf; }} .state.partial,.state.untested,.state.configured {{ color:#7a2e0e; background:#ffead5; }}
    .state.broken,.state.blocked {{ color:#912018; background:#fee4e2; }} .state.missing,.state.mocked {{ color:#6941c6; background:#f0e7ff; }}
    @media (max-width:900px) {{ .shell {{ display:block; }} nav {{ position:relative; height:auto; }} main {{ padding:35px 22px 60px; }} h1 {{ font-size:31px; }} }}
    @media print {{ @page {{ size:A4 landscape; margin:13mm; }} body {{ background:white; }} .shell {{ display:block; box-shadow:none; }} nav {{ display:none; }} main {{ padding:0; }} h2 {{ break-before:page; }} .table-wrap {{ overflow:visible; border:0; }} table.master {{ min-width:0; font-size:6.5pt; }} figure {{ break-inside:avoid; }} }}
    """
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Auditoría técnica integral — Agent Platform Fixed</title><style>{css}</style></head>
<body><div class="shell"><nav><div class="brand">Auditoría técnica integral</div><div class="decision">NO-GO — CRITICAL RISK</div>{toc}</nav><main>{''.join(body)}</main></div></body></html>
"""


def register_pdf_fonts() -> None:
    pdfmetrics.registerFont(TTFont("Arial", "C:/Windows/Fonts/arial.ttf"))
    pdfmetrics.registerFont(TTFont("Arial-Bold", "C:/Windows/Fonts/arialbd.ttf"))
    pdfmetrics.registerFont(TTFont("Consolas", "C:/Windows/Fonts/consola.ttf"))


def inline_pdf(value: str) -> str:
    escaped = html.escape(value.strip(), quote=False)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<font color="#1769A2"><u>\1</u></font>', escaped)
    escaped = re.sub(r"`([^`]+)`", r'<font name="Consolas" color="#344054">\1</font>', escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", escaped)
    return escaped


def pdf_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle("CoverTitle", parent=base["Title"], fontName="Arial-Bold", fontSize=29, leading=33, textColor=HexColor(NAVY), alignment=TA_LEFT, spaceAfter=12),
        "cover_sub": ParagraphStyle("CoverSub", parent=base["Normal"], fontName="Arial", fontSize=13, leading=19, textColor=HexColor(MUTED), spaceAfter=10),
        "decision": ParagraphStyle("Decision", parent=base["Normal"], fontName="Arial-Bold", fontSize=18, leading=22, textColor=HexColor(RED), alignment=TA_CENTER),
        "metric": ParagraphStyle("Metric", parent=base["Normal"], fontName="Arial-Bold", fontSize=16, leading=19, textColor=HexColor(NAVY), alignment=TA_CENTER),
        "metric_label": ParagraphStyle("MetricLabel", parent=base["Normal"], fontName="Arial", fontSize=8, leading=10, textColor=HexColor(MUTED), alignment=TA_CENTER),
        "h1": ParagraphStyle("H1", parent=base["Heading1"], fontName="Arial-Bold", fontSize=22, leading=26, textColor=HexColor(NAVY), spaceBefore=9, spaceAfter=12),
        "h2": ParagraphStyle("H2", parent=base["Heading2"], fontName="Arial-Bold", fontSize=16, leading=20, textColor=HexColor(NAVY), spaceBefore=13, spaceAfter=8, keepWithNext=True),
        "h3": ParagraphStyle("H3", parent=base["Heading3"], fontName="Arial-Bold", fontSize=12, leading=15, textColor=HexColor(BLUE), spaceBefore=10, spaceAfter=6, keepWithNext=True),
        "body": ParagraphStyle("Body", parent=base["BodyText"], fontName="Arial", fontSize=8.7, leading=12.2, textColor=HexColor(INK), spaceAfter=6),
        "bullet": ParagraphStyle("Bullet", parent=base["BodyText"], fontName="Arial", fontSize=8.5, leading=11.8, leftIndent=12, firstLineIndent=0, bulletFontName="Arial", bulletFontSize=8.5, textColor=HexColor(INK), spaceAfter=3),
        "quote": ParagraphStyle("Quote", parent=base["BodyText"], fontName="Arial-Bold", fontSize=9.3, leading=13, leftIndent=10, rightIndent=10, borderColor=HexColor(RED), borderWidth=1, borderPadding=9, backColor=HexColor("#FFF1F0"), textColor=HexColor("#7A271A"), spaceBefore=7, spaceAfter=9),
        "table_head": ParagraphStyle("TableHead", parent=base["Normal"], fontName="Arial-Bold", fontSize=6.5, leading=8, textColor=colors.white),
        "table_body": ParagraphStyle("TableBody", parent=base["Normal"], fontName="Arial", fontSize=6.3, leading=8.1, textColor=HexColor(INK)),
        "table_tiny": ParagraphStyle("TableTiny", parent=base["Normal"], fontName="Arial", fontSize=5.1, leading=6.5, textColor=HexColor(INK)),
        "toc": ParagraphStyle("TOC", parent=base["Normal"], fontName="Arial", fontSize=8.3, leading=11.3, textColor=HexColor(INK), spaceAfter=3),
        "code": ParagraphStyle("Code", parent=base["Code"], fontName="Consolas", fontSize=6.5, leading=8.2, textColor=HexColor("#F2F4F7"), backColor=HexColor("#101828"), borderPadding=8, spaceBefore=5, spaceAfter=7),
    }


def state_color(state: str) -> str | None:
    if state == "VERIFIED":
        return "#D1FADF"
    if state in {"PARTIALLY VERIFIED", "IMPLEMENTED BUT NOT TESTED", "CONFIGURED ONLY"}:
        return "#FFEAD5"
    if state in {"BROKEN", "BLOCKED"}:
        return "#FEE4E2"
    if state in {"NOT IMPLEMENTED", "MOCKED"}:
        return "#F0E7FF"
    return None


def pdf_table(header: list[str], rows: list[list[str]], styles: dict[str, ParagraphStyle], available_width: float):
    tiny = len(header) >= 8
    body_style = styles["table_tiny"] if tiny else styles["table_body"]
    data = [[Paragraph(inline_pdf(cell), styles["table_head"]) for cell in header]]
    for row in rows:
        padded = row + [""] * (len(header) - len(row))
        data.append([Paragraph(inline_pdf(cell), body_style) for cell in padded[: len(header)]])
    if len(header) >= 8:
        weights = [0.65, 0.85, 1.15, 1.2, 1.35, 1.55, 1.4, 0.75, 0.75, 1.55, 1.75]
        if len(header) != len(weights):
            weights = [1] * len(header)
    else:
        max_lengths = []
        for index in range(len(header)):
            values = [header[index]] + [row[index] if index < len(row) else "" for row in rows]
            max_lengths.append(max(6, min(42, max(len(re.sub(r"[`*]", "", value)) for value in values))))
        weights = max_lengths
    total = sum(weights)
    col_widths = [available_width * weight / total for weight in weights]
    table = LongTable(data, colWidths=col_widths, repeatRows=1, hAlign="LEFT", splitByRow=1)
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), HexColor(NAVY)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, HexColor(LINE)),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.5 if tiny else 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3.5 if tiny else 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, HexColor("#F8FAFC")]),
    ]
    for row_index, row in enumerate(rows, start=1):
        for col_index, value in enumerate(row):
            background = state_color(value.strip())
            if background:
                commands.extend([
                    ("BACKGROUND", (col_index, row_index), (col_index, row_index), HexColor(background)),
                    ("FONTNAME", (col_index, row_index), (col_index, row_index), "Arial-Bold"),
                ])
    table.setStyle(TableStyle(commands))
    return table


class AuditDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs):
        super().__init__(filename, **kwargs)
        self.title = "Auditoría técnica integral — Agent Platform Fixed"


def add_page_header_footer(canvas, doc) -> None:
    canvas.saveState()
    width, height = landscape(A4)
    canvas.setStrokeColor(HexColor(LINE))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, height - 13 * mm, width - 18 * mm, height - 13 * mm)
    canvas.setFont("Arial-Bold", 7.5)
    canvas.setFillColor(HexColor(NAVY))
    canvas.drawString(18 * mm, height - 10 * mm, "AGENT PLATFORM FIXED · AUDITORÍA TÉCNICA INTEGRAL")
    canvas.setFont("Arial", 7)
    canvas.setFillColor(HexColor(MUTED))
    canvas.drawRightString(width - 18 * mm, height - 10 * mm, "2 AGO 2026 · NO-GO — CRITICAL RISK")
    canvas.line(18 * mm, 12 * mm, width - 18 * mm, 12 * mm)
    canvas.drawString(18 * mm, 8 * mm, "Uso interno · Evidencia reproducible y estados conservadores")
    canvas.drawRightString(width - 18 * mm, 8 * mm, f"Página {doc.page}")
    canvas.restoreState()


def add_cover_background(canvas, doc) -> None:
    canvas.saveState()
    width, height = landscape(A4)
    canvas.setFillColor(HexColor(NAVY))
    canvas.rect(0, height - 34 * mm, width, 34 * mm, stroke=0, fill=1)
    canvas.setFillColor(HexColor(TEAL))
    canvas.rect(0, 0, width, 8 * mm, stroke=0, fill=1)
    canvas.setFont("Arial-Bold", 8)
    canvas.setFillColor(colors.white)
    canvas.drawString(18 * mm, height - 19 * mm, "INFORME PRINCIPAL · 2 DE AGOSTO DE 2026")
    canvas.restoreState()


def markdown_to_pdf(markdown_text: str, current_diagram: Path, recommended_diagram: Path, output_path: Path) -> None:
    register_pdf_fonts()
    styles = pdf_styles()
    page_size = landscape(A4)
    left = right = 17 * mm
    top = 18 * mm
    bottom = 16 * mm
    available_width = page_size[0] - left - right
    doc = AuditDocTemplate(
        str(output_path),
        pagesize=page_size,
        leftMargin=left,
        rightMargin=right,
        topMargin=top,
        bottomMargin=bottom,
        title="Auditoría técnica integral — Agent Platform Fixed",
        author="Auditoría técnica",
        subject="Arquitectura, seguridad, QA, DevOps y preparación comercial",
    )
    cover_frame = Frame(left, bottom, available_width, page_size[1] - bottom - top, id="cover-frame", leftPadding=0, rightPadding=0, topPadding=12 * mm, bottomPadding=0)
    body_frame = Frame(left, bottom, available_width, page_size[1] - bottom - top, id="body-frame", leftPadding=0, rightPadding=0, topPadding=2 * mm, bottomPadding=2 * mm)
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[cover_frame], onPage=add_cover_background),
        PageTemplate(id="body", frames=[body_frame], onPage=add_page_header_footer),
    ])

    lines = markdown_text.splitlines()
    headings = []
    for line in lines:
        match = re.match(r"^##\s+(.+)$", line)
        if match:
            headings.append(re.sub(r"[*`]", "", match.group(1)))

    story = [
        Spacer(1, 34 * mm),
        Paragraph("Auditoría técnica integral", styles["cover_title"]),
        Paragraph("Agent Platform Fixed", ParagraphStyle("Project", parent=styles["cover_title"], fontSize=21, leading=25, textColor=HexColor(BLUE))),
        HRFlowable(width="100%", thickness=3, color=HexColor(TEAL), spaceBefore=4, spaceAfter=15),
        Paragraph("Arquitectura · código · DevOps · QA · seguridad · IA/RAG · integraciones · UX · operación · licencias", styles["cover_sub"]),
        Spacer(1, 4 * mm),
        Table([[Paragraph("NO-GO — CRITICAL RISK", styles["decision"]) ]], colWidths=[available_width], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), HexColor("#FEE4E2")),
            ("BOX", (0, 0), (-1, -1), 1.3, HexColor(RED)),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ])),
        Spacer(1, 8 * mm),
    ]
    metrics = [
        ("30", "DEFECTOS"),
        ("5", "P0 / STOP-SHIP"),
        ("31", "TESTS BACKEND"),
        ("67 %", "COBERTURA LOCAL"),
        ("40–60", "PERSONA-DÍAS"),
    ]
    metric_cells = []
    for value, label in metrics:
        metric_cells.append([Paragraph(value, styles["metric"]), Paragraph(label, styles["metric_label"])])
    story.append(Table([metric_cells], colWidths=[available_width / len(metrics)] * len(metrics), style=TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(PALE)),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor(LINE)),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, HexColor(LINE)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ])))
    story.extend([
        Spacer(1, 8 * mm),
        Paragraph("El proyecto no debe exponerse a clientes ni procesar pedidos reales. La evidencia disponible demuestra riesgos de integridad comercial, ausencia de integraciones end-to-end y recuperación no validada.", styles["quote"]),
        NextPageTemplate("body"),
        PageBreak(),
        Paragraph("Contenido", styles["h1"]),
    ])
    toc_cells = []
    midpoint = (len(headings) + 1) // 2
    for index in range(midpoint):
        left_item = headings[index]
        right_item = headings[index + midpoint] if index + midpoint < len(headings) else ""
        toc_cells.append([Paragraph(inline_pdf(left_item), styles["toc"]), Paragraph(inline_pdf(right_item), styles["toc"])])
    story.append(Table(toc_cells, colWidths=[available_width / 2 - 5, available_width / 2 - 5], style=TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.2, HexColor("#EAECF0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])))
    story.append(PageBreak())

    start = next((index for index, line in enumerate(lines) if line.startswith("## 2. ")), 0)
    i = start
    mermaid_index = 0
    while i < len(lines):
        line = lines[i]
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            level = len(heading.group(1))
            clean_heading = re.sub(r"[*`]", "", heading.group(2))
            if level == 2 and clean_heading.startswith("9. Arquitectura recomendada"):
                story.append(NextPageTemplate("body"))
                story.append(PageBreak())
            style = styles["h1"] if level == 1 else styles["h2"] if level == 2 else styles["h3"]
            story.append(CondPageBreak(35 * mm if level <= 2 else 22 * mm))
            story.append(Paragraph(inline_pdf(heading.group(2)), style))
            i += 1
            continue
        if line.startswith("```"):
            language = line[3:].strip()
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            if language == "mermaid" and mermaid_index < 2:
                diagram_path = current_diagram if mermaid_index == 0 else recommended_diagram
                with PILImage.open(diagram_path) as diagram_image:
                    ratio = diagram_image.height / diagram_image.width
                display_width = min(available_width, 245 * mm)
                story.append(Image(str(diagram_path), width=display_width, height=display_width * ratio))
                story.append(Spacer(1, 5))
                mermaid_index += 1
            else:
                code_text = "<br/>".join(html.escape(code_line) for code_line in block)
                story.append(Paragraph(code_text, styles["code"]))
            continue
        if line.startswith("|") and i + 1 < len(lines) and is_table_separator(lines[i + 1]):
            header = split_table_row(line)
            rows = []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(split_table_row(lines[i]))
                i += 1
            story.append(pdf_table(header, rows, styles, available_width))
            story.append(Spacer(1, 8))
            continue
        if re.fullmatch(r"\s*-{3,}\s*", line):
            story.append(HRFlowable(width="100%", thickness=0.7, color=HexColor(LINE), spaceBefore=5, spaceAfter=7))
            i += 1
            continue
        quote = re.match(r"^>\s?(.*)$", line)
        if quote:
            quote_lines = []
            while i < len(lines):
                quote_match = re.match(r"^>\s?(.*)$", lines[i])
                if not quote_match:
                    break
                quote_lines.append(quote_match.group(1))
                i += 1
            story.append(Paragraph(inline_pdf(" ".join(quote_lines)), styles["quote"]))
            continue
        bullet = re.match(r"^\s*[-*]\s+(.+)$", line)
        number = re.match(r"^\s*(\d+)\.\s+(.+)$", line)
        if bullet or number:
            if bullet:
                story.append(Paragraph(inline_pdf(bullet.group(1)), styles["bullet"], bulletText="•"))
            else:
                story.append(Paragraph(inline_pdf(number.group(2)), styles["bullet"], bulletText=f"{number.group(1)}."))
            i += 1
            continue
        if not line.strip():
            i += 1
            continue
        paragraph = [line.strip()]
        i += 1
        while i < len(lines):
            candidate = lines[i]
            if not candidate.strip() or re.match(r"^(#{1,3})\s+", candidate) or candidate.startswith("```") or candidate.startswith("|") or candidate.startswith(">") or re.match(r"^\s*([-*]|\d+\.)\s+", candidate):
                break
            paragraph.append(candidate.strip())
            i += 1
        story.append(Paragraph(inline_pdf(" ".join(paragraph)), styles["body"]))

    doc.build(story)


def validate_source(markdown_text: str) -> None:
    for section in range(1, 36):
        if not re.search(rf"^## {section}\. ", markdown_text, flags=re.MULTILINE):
            raise RuntimeError(f"Falta la sección obligatoria {section}")
    master_ids = re.findall(r"^\| M-(\d{2}) \|", markdown_text, flags=re.MULTILINE)
    if master_ids != [f"{index:02d}" for index in range(1, 36)]:
        raise RuntimeError("La tabla maestra no contiene exactamente M-01..M-35")
    if "NO-GO — CRITICAL RISK" not in markdown_text:
        raise RuntimeError("Falta la decisión final permitida")


def create_release() -> None:
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    for source in (SOURCE_MD, OUTPUT_HTML, OUTPUT_PDF):
        shutil.copy2(source, RELEASE_DIR / source.name)
    release_audit = RELEASE_DIR / "audit"
    shutil.copytree(
        AUDIT_DIR,
        release_audit,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("tools", "__pycache__", "*.pyc"),
    )
    readme = """# Paquete de auditoría técnica

Decisión: **NO-GO — CRITICAL RISK**.

Contenido:

- Informe principal en Markdown, HTML y PDF.
- Informes 01–22 de las fases de auditoría.
- Diagramas Mermaid y renderizados.
- Inventario, matriz de capacidades, defectos, riesgos y deuda.
- Roadmap y plan 30/60/90.
- Evidencias de tests, cobertura, análisis estático, logs, build, scans, SBOM y capturas.

`SCREENSHOTS_STATUS.md` y `SBOM_STATUS.md` documentan explícitamente por qué esos artefactos quedaron BLOCKED; no se incluyen pruebas inventadas.
"""
    (RELEASE_DIR / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    manifest_lines = []
    for path in sorted(RELEASE_DIR.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file() or path.name == "MANIFEST.sha256":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        relative = path.relative_to(RELEASE_DIR).as_posix()
        manifest_lines.append(f"{digest}  {relative}")
    (RELEASE_DIR / "MANIFEST.sha256").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    markdown_text = SOURCE_MD.read_text(encoding="utf-8")
    validate_source(markdown_text)
    DIAGRAM_DIR.mkdir(parents=True, exist_ok=True)
    current_diagram = DIAGRAM_DIR / "current_architecture.png"
    recommended_diagram = DIAGRAM_DIR / "recommended_architecture.png"
    build_current_diagram(current_diagram)
    build_recommended_diagram(recommended_diagram)
    OUTPUT_HTML.write_text(markdown_to_html(markdown_text, current_diagram, recommended_diagram), encoding="utf-8", newline="\n")
    markdown_to_pdf(markdown_text, current_diagram, recommended_diagram, OUTPUT_PDF)
    create_release()
    print(f"HTML={OUTPUT_HTML}")
    print(f"PDF={OUTPUT_PDF}")
    print(f"RELEASE={RELEASE_DIR}")


if __name__ == "__main__":
    main()
