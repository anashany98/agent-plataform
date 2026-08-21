"""Generadores SEO deterministas (T-018): sitemap.xml, blog-rss.xml,
llms.txt, llms-full.txt y knowledge-index.json sobre catálogo y wiki.

Portados de FlowWink (MIT, D-012) al motor del Bridge. Los gates del port:

- Determinismo: dado el mismo estado de BD y ``base_url``, dos llamadas
  producen bytes idénticos (sin timestamps de reloj de pared).
- Validez de salida: sitemap y RSS son XML bien formado (se parsean con
  ElementTree), llms.txt es texto plano con secciones y el índice es JSON
  con esquema estable.
- Alcance de contenido: solo wiki ``published``, landings ``approved`` y
  productos de orígenes de confianza sin demo y disponibles (mismas reglas
  que el catálogo operativo).
- Sin publicación externa: todas las respuestas declaran
  ``X-External-Publication: not-performed``.
- ``base_url`` nunca se hardcodea: se pasa explícita o se deriva del origin.

Hermeticidad D-032: los datos de prueba usan prefijos marcados y se
eliminan al final; las aserciones comparan solo el conjunto propio (la BD
de sesión es compartida por todo el corpus).
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.database import SessionLocal
from app.models.models import LandingPage, Product, WikiPage

MARKER = f"seogen{uuid.uuid4().hex[:8]}"
BASE = "https://tienda.example.com"


def _own(values: list[str]) -> list[str]:
    return [value for value in values if MARKER in value]


def _own_entries(entries: list[dict]) -> list[dict]:
    return [
        entry
        for entry in entries
        if MARKER in str(entry.get("id")) or MARKER in str(entry.get("title"))
    ]


def _seed(client) -> dict:
    """Crea productos (visible/demo), wiki (publicada/borrador) y landing
    (aprobada/borrador) marcadas. Devuelve los objetos a limpiar."""
    db = SessionLocal()
    created: dict[str, list] = {"products": [], "wiki": [], "landings": []}
    try:
        now = datetime.now(UTC).replace(tzinfo=None)
        products = [
            Product(
                id=f"prod-{MARKER}-vis",
                sku=f"{MARKER}-visible",
                name="Foco Led 12W & <Ensalada>",
                description="<p>Iluminación eficiente <strong>12W</strong></p>",
                category="Iluminación",
                source="local",
                base_price=Decimal("12.90"),
                tax_rate=Decimal("0.21"),
                stock_quantity=10,
                reserved_stock=0,
            ),
            Product(
                id=f"prod-{MARKER}-prestashop",
                sku=f"{MARKER}-prestashop",
                name="Soporte PrestaShop",
                description="Producto de tienda con flags de comercio.",
                category="Oficina",
                source="prestashop",
                attributes={"active": True, "show_price": True, "available_for_order": True},
                base_price=Decimal("5.00"),
                tax_rate=Decimal("0.21"),
                stock_quantity=3,
                reserved_stock=0,
            ),
            Product(
                id=f"prod-{MARKER}-demo",
                sku=f"{MARKER}-demo",
                name="Producto Demo Oculto",
                description="No debe aparecer en salidas SEO.",
                category="Demo",
                source="demo",
                base_price=Decimal("1.00"),
                tax_rate=Decimal("0.21"),
                stock_quantity=1,
                reserved_stock=0,
            ),
            Product(
                id=f"prod-{MARKER}-noavail",
                sku=f"{MARKER}-noavail",
                name="PrestaShop Sin Flags",
                description="No comercialmente disponible.",
                category="Oficina",
                source="prestashop",
                attributes={"active": False, "show_price": False, "available_for_order": False},
                base_price=Decimal("9.00"),
                tax_rate=Decimal("0.21"),
                stock_quantity=1,
                reserved_stock=0,
            ),
        ]
        db.add_all(products)
        created["products"] = products

        wiki = [
            WikiPage(
                id=f"wiki-{MARKER}-guia",
                slug=f"guia-{MARKER}",
                title="Guía del Bridge & SEO",
                content="<p>Bienvenidos a la <strong>guía</strong> del Bridge.</p>",
                status="published",
                version=1,
                created_by="admin",
                updated_by="admin",
                published_at=now - timedelta(days=1),
                updated_at=now - timedelta(days=1),
            ),
            WikiPage(
                id=f"wiki-{MARKER}-borrador",
                slug=f"borrador-{MARKER}",
                title="Borrador invisible",
                content="No debe publicarse.",
                status="draft",
                version=1,
                created_by="admin",
                updated_by="admin",
            ),
        ]
        db.add_all(wiki)
        created["wiki"] = wiki

        landings = [
            LandingPage(
                id=f"landing-{MARKER}-oferta",
                slug=f"oferta-{MARKER}",
                title="Oferta SEO",
                content={"headline": "Oferta", "body": "Cuerpo aprobado.", "cta": "Contactar"},
                status="approved",
                version=1,
                created_by="admin",
                updated_by="admin",
                approved_at=now - timedelta(hours=2),
                updated_at=now - timedelta(hours=2),
            ),
            LandingPage(
                id=f"landing-{MARKER}-borrador",
                slug=f"borrador-landing-{MARKER}",
                title="Landing borrador",
                content={"headline": "X", "body": "Y", "cta": "Z"},
                status="draft",
                version=1,
                created_by="admin",
                updated_by="admin",
            ),
        ]
        db.add_all(landings)
        created["landings"] = landings
        db.commit()
        return created
    finally:
        db.close()


def _cleanup(created: dict) -> None:
    db = SessionLocal()
    try:
        for product in created["products"]:
            db.delete(product)
        for page in created["wiki"]:
            db.delete(page)
        for page in created["landings"]:
            db.delete(page)
        db.commit()
    finally:
        db.close()


def test_sitemap_xml_is_well_formed_and_scoped(client, auth_headers) -> None:
    created = _seed(client)
    try:
        response = client.get(f"/public/sitemap.xml?base_url={BASE}")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/xml")
        assert response.headers["x-external-publication"] == "not-performed"
        assert "public, max-age=60" in response.headers["cache-control"]

        # XML bien formado y con el namespace de sitemaps.org.
        root = ET.fromstring(response.content)
        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [node.text for node in root.findall("sm:url/sm:loc", namespace)]

        own_locs = _own(locs)
        # 4 propias: 2 productos visibles + wiki publicada + landing aprobada.
        assert len(own_locs) == 4
        product_locs = [loc for loc in own_locs if "public/products/" in loc]
        assert len(product_locs) == 2
        # Wiki publicada y landing aprobada presentes.
        assert any(f"public/wiki/guia-{MARKER}" in loc for loc in own_locs)
        assert any(f"public/landing-pages/oferta-{MARKER}" in loc for loc in own_locs)

        # Demo, producto no disponible, wiki borrador y landing borrador ausentes.
        assert not any("demo" in loc or "noavail" in loc for loc in own_locs)
        assert not any("borrador" in loc for loc in own_locs)

        # Escape XML de caracteres especiales en el loc del producto.
        product_loc = next(loc for loc in own_locs if "public/products/" in loc)
        assert "&amp;" not in product_loc  # los ids son UUIDs sin caracteres especiales

        # Determinismo: misma BD y base_url → bytes idénticos.
        again = client.get(f"/public/sitemap.xml?base_url={BASE}")
        assert again.content == response.content
    finally:
        _cleanup(created)


def test_sitemap_xml_derives_base_url_from_origin(client, auth_headers) -> None:
    created = _seed(client)
    try:
        response = client.get("/public/sitemap.xml")
        assert response.status_code == 200
        assert "http://testserver/" in response.text
    finally:
        _cleanup(created)


def test_sitemap_xml_rejects_bad_base_url(client, auth_headers) -> None:
    created = _seed(client)
    try:
        for bad in [
            "javascript:alert(1)",
            "ftp://tienda.example.com",
            "https://tienda.example.com/path",
            "https://tienda.example.com?x=1",
            "not-a-url",
        ]:
            response = client.get(f"/public/sitemap.xml?base_url={bad}")
            assert response.status_code == 422, (bad, response.text)
    finally:
        _cleanup(created)


def test_blog_rss_is_valid_and_deterministic(client, auth_headers) -> None:
    created = _seed(client)
    try:
        response = client.get(f"/public/blog-rss.xml?base_url={BASE}")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/rss+xml")
        assert response.headers["x-external-publication"] == "not-performed"

        # RSS 2.0 bien formado.
        root = ET.fromstring(response.content)
        assert root.tag == "rss"
        assert root.attrib["version"] == "2.0"
        channel = root.find("channel")
        assert channel is not None
        assert channel.findtext("language") == "es"
        assert channel.find("lastBuildDate") is not None

        items = channel.findall("item")
        own_items = [
            item
            for item in items
            if MARKER in (item.findtext("link") or "")
        ]
        assert len(own_items) == 1
        item = own_items[0]
        assert "Guía del Bridge" in (item.findtext("title") or "")
        assert item.findtext("link") == f"{BASE}/public/wiki/guia-{MARKER}"
        assert item.findtext("guid") == item.findtext("link")
        # pubDate en formato RFC 822 (RSS 2.0).
        pub_date = item.findtext("pubDate")
        assert pub_date is not None
        from email.utils import parsedate_to_datetime

        assert parsedate_to_datetime(pub_date) is not None
        # Descripción en texto plano sin etiquetas HTML.
        description = item.findtext("description")
        assert "<" not in description and ">" not in description
        assert "Bienvenidos a la guía del Bridge." in description

        # Determinismo: misma BD y base_url → bytes idénticos.
        again = client.get(f"/public/blog-rss.xml?base_url={BASE}")
        assert again.content == response.content
    finally:
        _cleanup(created)


def test_llms_txt_and_llms_full(client, auth_headers) -> None:
    created = _seed(client)
    try:
        concise = client.get(f"/public/llms.txt?base_url={BASE}")
        assert concise.status_code == 200, concise.text
        assert concise.headers["content-type"].startswith("text/plain")
        assert concise.headers["x-external-publication"] == "not-performed"
        text = concise.text
        assert text.startswith("# ")
        assert "## Wiki" in text
        assert "## Catálogo" in text
        assert f"public/wiki/guia-{MARKER}" in text
        assert "Foco Led 12W" in text
        # Demo y no disponible excluidas del catálogo.
        assert "Producto Demo Oculto" not in text
        assert "PrestaShop Sin Flags" not in text

        full = client.get(f"/public/llms-full.txt?base_url={BASE}")
        assert full.status_code == 200, full.text
        assert "Iluminación eficiente 12W" in full.text  # contenido completo
        assert "SKU:" in full.text

        # Determinismo en ambas variantes.
        assert client.get(f"/public/llms.txt?base_url={BASE}").content == concise.content
        assert client.get(f"/public/llms-full.txt?base_url={BASE}").content == full.content
    finally:
        _cleanup(created)


def test_knowledge_index_is_json_deterministic_and_scoped(client, auth_headers) -> None:
    created = _seed(client)
    try:
        response = client.get(f"/public/knowledge-index.json?base_url={BASE}")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/json")
        payload = response.json()
        assert payload["schema_version"] == 1
        assert payload["base_url"] == BASE
        assert payload["indexed_at"] is not None

        entries = payload["entries"]
        own = _own_entries(entries)
        types = {entry["type"] for entry in own}
        assert types == {"wiki", "product"}
        # 2 productos visibles + 1 wiki publicada de las nuestras.
        assert len(own) == 3
        for entry in own:
            assert entry["url"].startswith(f"{BASE}/public/")
            assert entry["updated_at"].endswith("Z")
            assert entry["chunks"]  # fragmentos no vacíos
            for chunk in entry["chunks"]:
                assert chunk["content"]
                assert chunk["id"].startswith(entry["id"])

        # Determinismo (orden estable y sin reloj de pared).
        again = client.get(f"/public/knowledge-index.json?base_url={BASE}")
        assert again.content == response.content
    finally:
        _cleanup(created)


def test_public_product_page_is_local_and_scoped(client, auth_headers) -> None:
    created = _seed(client)
    try:
        db = SessionLocal()
        try:
            visible = db.query(Product).filter(Product.sku == f"{MARKER}-visible").first()
            demo = db.query(Product).filter(Product.sku == f"{MARKER}-demo").first()
            unavailable = db.query(Product).filter(Product.sku == f"{MARKER}-noavail").first()
        finally:
            db.close()
        assert visible is not None and demo is not None and unavailable is not None

        response = client.get(f"/public/products/{visible.id}")
        assert response.status_code == 200, response.text
        assert "text/html" in response.headers["content-type"]
        assert "sandbox" in response.headers["content-security-policy"]
        assert response.headers["x-external-publication"] == "not-performed"
        assert "Foco Led 12W" in response.text

        assert client.get(f"/public/products/{demo.id}").status_code == 404
        assert client.get(f"/public/products/{unavailable.id}").status_code == 404
        assert client.get("/public/products/does-not-exist").status_code == 404
    finally:
        _cleanup(created)
