"""Generadores SEO deterministas (T-018): sitemap.xml, blog-rss, llms.txt y
knowledge-index sobre el catálogo y la wiki del Bridge.

Portados desde FlowWink (supabase/functions/{sitemap,blog-rss,llms-txt,
knowledge-indexer}, MIT, ver DECISIONS.md D-012) al motor del Bridge sin
Supabase: leen de PostgreSQL/SQLite vía SQLAlchemy y no llaman a ningún
servicio externo.

Determinismo (gate del port): dado el mismo estado de BD y la misma
``base_url``, la salida es byte a byte idéntica — sin timestamps de reloj
de pared, orden estable y escape XML correcto. ``base_url`` nunca se
hardcodea: la recibe el llamador (query param validado) o se deriva del
origin de la petición; si una instalación cambia de dominio, la salida
cambia de forma predecible y solo en los ``loc``.

Alcance de contenido (idéntico al catálogo operativo): solo páginas wiki
``published``, landings ``approved`` y productos de orígenes de confianza
sin demo y comercialmente disponibles. Nada se publica externamente: la
respuesta se sirve localmente con ``X-External-Publication:
not-performed``.
"""

from __future__ import annotations

import datetime
import email.utils
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape

from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import LandingPage, Product, WikiPage
from app.services.deterministic_tools import DeterministicToolsService

# Límites de la especificación (sitemaps.org permite 50.000 URLs por archivo)
# y de saneamiento de salidas públicas (RSS 20 ítems como FlowWink, índices
# acotados para que la respuesta siga siendo operativa con catálogos de
# decenas de miles de filas).
SITEMAP_MAX_URLS = 50_000
RSS_MAX_ITEMS = 20
LLMS_MAX_PRODUCTS = 1_000
KNOWLEDGE_MAX_PRODUCTS = 10_000
KNOWLEDGE_CHUNK_CHARS = 1_500


class _PlainTextExtractor(HTMLParser):
    """Extrae texto plano de contenido wiki (HTML o texto simple)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._parts)).strip()


def _markdown_label(value: str) -> str:
    """Sanea un título para usarlo como texto de enlace markdown."""
    return value.replace("[", "(").replace("]", ")")


def _plain_text(value: str | None) -> str:
    """Normaliza contenido wiki/producto a texto plano determinista."""
    if not value:
        return ""
    if "<" not in value:
        return re.sub(r"\s+", " ", value).strip()
    extractor = _PlainTextExtractor()
    extractor.feed(value)
    return extractor.text()


def _rfc822(value: datetime.datetime) -> str:
    """Formatea un datetime naive UTC como RFC 822 (RSS 2.0, GMT)."""
    return email.utils.format_datetime(
        value.replace(tzinfo=datetime.timezone.utc),
        usegmt=True,
    )


def _iso_date(value: datetime.datetime | None) -> str:
    return (value or datetime.datetime(1970, 1, 1)).strftime("%Y-%m-%d")


def _iso_utc(value: datetime.datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="seconds") + "Z"


def _chunk_text(text: str, prefix: str) -> list[dict[str, str]]:
    """Trocea texto plano en fragmentos de tamaño fijo (determinista)."""
    if not text:
        return []
    chunks: list[dict[str, str]] = []
    for index in range(0, len(text), KNOWLEDGE_CHUNK_CHARS):
        chunks.append(
            {
                "id": f"{prefix}:{index // KNOWLEDGE_CHUNK_CHARS}",
                "content": text[index : index + KNOWLEDGE_CHUNK_CHARS],
            }
        )
    return chunks


class SeoGeneratorService:
    """Genera representaciones SEO deterministas de catálogo y wiki."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Fuentes de contenido (mismas reglas de visibilidad que el catálogo)
    # ------------------------------------------------------------------

    def _published_wiki_pages(self) -> list[WikiPage]:
        return (
            self.db.query(WikiPage)
            .filter(WikiPage.status == "published")
            .order_by(WikiPage.slug.asc())
            .all()
        )

    def _approved_landing_pages(self) -> list[LandingPage]:
        return (
            self.db.query(LandingPage)
            .filter(LandingPage.status == "approved")
            .order_by(LandingPage.slug.asc())
            .all()
        )

    def _visible_products(self) -> list[Product]:
        rows = (
            self.db.query(Product)
            .filter(DeterministicToolsService._non_demo_product_clause())
            .order_by(Product.id.asc())
            .all()
        )
        return [
            product
            for product in rows
            if DeterministicToolsService._is_product_commercially_available(product)
        ]

    # ------------------------------------------------------------------
    # sitemap.xml
    # ------------------------------------------------------------------

    def sitemap_xml(self, base_url: str) -> str:
        """Sitemap determinista de wiki publicada, landings aprobadas y
        catálogo visible. Orden estable: por slug/id ascendente."""
        entries: list[str] = []
        for page in self._published_wiki_pages():
            loc = f"{base_url}/public/wiki/{page.slug}"
            entries.append(
                "  <url>\n"
                f"    <loc>{xml_escape(loc)}</loc>\n"
                f"    <lastmod>{_iso_date(page.updated_at)}</lastmod>\n"
                "    <changefreq>weekly</changefreq>\n"
                "    <priority>0.8</priority>\n"
                "  </url>"
            )
        for page in self._approved_landing_pages():
            loc = f"{base_url}/public/landing-pages/{page.slug}"
            entries.append(
                "  <url>\n"
                f"    <loc>{xml_escape(loc)}</loc>\n"
                f"    <lastmod>{_iso_date(page.updated_at)}</lastmod>\n"
                "    <changefreq>weekly</changefreq>\n"
                "    <priority>0.8</priority>\n"
                "  </url>"
            )
        for product in self._visible_products()[:SITEMAP_MAX_URLS]:
            loc = f"{base_url}/public/products/{product.id}"
            entries.append(
                "  <url>\n"
                f"    <loc>{xml_escape(loc)}</loc>\n"
                f"    <lastmod>{_iso_date(product.updated_at)}</lastmod>\n"
                "    <changefreq>monthly</changefreq>\n"
                "    <priority>0.6</priority>\n"
                "  </url>"
            )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(entries)
            + "\n</urlset>"
        )

    # ------------------------------------------------------------------
    # blog-rss
    # ------------------------------------------------------------------

    def blog_rss(self, base_url: str) -> str:
        """Feed RSS 2.0 de la wiki publicada (el "blog" del Bridge).

        Determinista: ítems ordenados por ``published_at`` descendente y
        ``lastBuildDate`` derivado de los propios ítems (nunca del reloj de
        pared), igual que FlowWink con su límite de 20 entradas.
        """
        pages = [
            page for page in self._published_wiki_pages() if page.published_at
        ]
        pages.sort(key=lambda page: (page.published_at, page.slug), reverse=True)
        pages = pages[:RSS_MAX_ITEMS]

        site_title = settings.PROJECT_NAME
        channel_title = f"{site_title} — Blog"
        items: list[str] = []
        for page in pages:
            link = f"{base_url}/public/wiki/{page.slug}"
            excerpt = _plain_text(page.content)[:500]
            items.append(
                "    <item>\n"
                f"      <title>{xml_escape(page.title)}</title>\n"
                f"      <link>{xml_escape(link)}</link>\n"
                f'      <guid isPermaLink="true">{xml_escape(link)}</guid>\n'
                f"      <pubDate>{_rfc822(page.published_at)}</pubDate>\n"
                f"      <description>{xml_escape(excerpt)}</description>\n"
                "    </item>"
            )

        if pages:
            last_build = _rfc822(max(page.published_at for page in pages))
        else:
            last_build = _rfc822(datetime.datetime(1970, 1, 1))

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
            "  <channel>\n"
            f"    <title>{xml_escape(channel_title)}</title>\n"
            f"    <link>{xml_escape(base_url)}</link>\n"
            f"    <description>Publicaciones de la wiki de {xml_escape(site_title)}</description>\n"
            "    <language>es</language>\n"
            f"    <lastBuildDate>{last_build}</lastBuildDate>\n"
            + "\n".join(items)
            + "\n  </channel>\n</rss>"
        )

    # ------------------------------------------------------------------
    # llms.txt / llms-full.txt
    # ------------------------------------------------------------------

    def llms_txt(self, base_url: str, *, full: bool = False) -> str:
        """Archivo llms.txt (o llms-full.txt) determinista: wiki + catálogo.

        Formato de la comunidad llmstxt.org: título, descripción corta y
        secciones con enlaces; la variante ``full`` incluye el contenido
        completo en texto plano.
        """
        site_title = settings.PROJECT_NAME
        out: list[str] = [f"# {site_title}", ""]
        if full:
            out.append(
                f"> Conocimiento completo del Bridge (instalación {settings.INSTALLATION_ID})."
            )
        else:
            out.append(
                f"> Catálogo y wiki del Bridge (instalación {settings.INSTALLATION_ID})."
            )
        out.append("")
        out.append("---")
        out.append("")

        wiki = self._published_wiki_pages()
        out.append("## Wiki")
        out.append("")
        for page in wiki:
            if full:
                out.append(f"### {page.title}")
                out.append("")
                out.append(f"URL: {base_url}/public/wiki/{page.slug}")
                out.append("")
                body = _plain_text(page.content)
                if body:
                    out.append(body)
                    out.append("")
            else:
                out.append(
                    f"- [{_markdown_label(page.title)}]({base_url}/public/wiki/{page.slug})"
                )
        out.append("")

        products = self._visible_products()[:LLMS_MAX_PRODUCTS]
        out.append("## Catálogo")
        out.append("")
        for product in products:
            description = _plain_text(product.description)
            if full:
                out.append(f"### {product.name}")
                out.append("")
                out.append(f"URL: {base_url}/public/products/{product.id}")
                out.append("")
                out.append(
                    f"SKU: {product.sku} | Categoría: "
                    f"{product.category or '—'} | Precio: "
                    f"{float(product.base_price):.2f}"
                )
                out.append("")
                if description:
                    out.append(description)
                    out.append("")
            else:
                line = (
                    f"- [{_markdown_label(product.name)}]"
                    f"({base_url}/public/products/{product.id})"
                )
                if description:
                    line += f" — {description[:200]}"
                out.append(line)
        out.append("")
        return "\n".join(out)

    # ------------------------------------------------------------------
    # knowledge-index
    # ------------------------------------------------------------------

    def knowledge_index(self, base_url: str) -> dict[str, Any]:
        """Índice de conocimiento determinista para recuperación (RAG).

        Devuelve entradas de wiki (todas las publicadas) y catálogo (hasta
        ``KNOWLEDGE_MAX_PRODUCTS``), ordenadas por id estable, con contenido
        en texto plano troceado en fragmentos de tamaño fijo (ids
        ``{tipo}:{slug|id}:{n}``). ``indexed_at`` se deriva del dato más
        reciente, nunca del reloj de pared.
        """
        entries: list[dict[str, Any]] = []
        for page in self._published_wiki_pages():
            content = _plain_text(page.content)
            entry_id = f"wiki:{page.slug}"
            entries.append(
                {
                    "id": entry_id,
                    "type": "wiki",
                    "title": page.title,
                    "url": f"{base_url}/public/wiki/{page.slug}",
                    "updated_at": _iso_utc(page.updated_at),
                    "content": content,
                    "chunks": _chunk_text(content, entry_id),
                }
            )
        for product in self._visible_products()[:KNOWLEDGE_MAX_PRODUCTS]:
            content = _plain_text(
                f"{product.name} — {product.description or ''} "
                f"(SKU {product.sku}, categoría {product.category or '—'}, "
                f"precio {float(product.base_price):.2f})"
            )
            entry_id = f"product:{product.id}"
            entries.append(
                {
                    "id": entry_id,
                    "type": "product",
                    "title": product.name,
                    "url": f"{base_url}/public/products/{product.id}",
                    "updated_at": _iso_utc(product.updated_at),
                    "content": content,
                    "chunks": _chunk_text(content, entry_id),
                }
            )
        entries.sort(key=lambda entry: entry["id"])

        timestamps = [
            datetime.datetime.strptime(entry["updated_at"], "%Y-%m-%dT%H:%M:%SZ")
            for entry in entries
            if entry["updated_at"]
        ]
        indexed_at = _iso_utc(max(timestamps)) if timestamps else _iso_utc(None)
        return {
            "schema_version": 1,
            "base_url": base_url,
            "count": len(entries),
            "indexed_at": indexed_at,
            "entries": entries,
        }


def validate_public_base_url(value: str | None, request: Any) -> str:
    """Normaliza la base URL pública: param ``base_url`` validado o origin
    de la petición. Nunca se hardcodea un dominio (regla FlowWink)."""
    if value:
        parsed = urlparse(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.netloc
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError(
                "base_url debe ser una URL absoluta http(s) sin ruta ni query"
            )
        return value.rstrip("/")
    return str(request.base_url).rstrip("/")
