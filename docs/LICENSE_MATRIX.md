# Matriz de licencias y uso comercial

**Corte técnico:** 2026-08-15

**Estado legal:** revisión parcial; este documento no concede derechos ni sustituye asesoramiento jurídico.

## Código propio

El archivo raíz `LICENSE` reserva todos los derechos sobre Bridge API, Portal, scripts y documentación salvo autorización escrita. Antes de entregar a un cliente deben constar por contrato: titular, derechos de uso/despliegue, soporte, modificaciones, redistribución, terminación y tratamiento de componentes de terceros.

## Dependencias directas Bridge API

| Dependencia | Licencia declarada/inventariada | Uso | Obligación/riesgo |
|---|---|---|---|
| FastAPI, Pydantic, SQLAlchemy, Alembic, pgvector, Redis client, BeautifulSoup, python-docx | MIT | API, modelos, DB, parsing | conservar notices/licencia |
| Uvicorn, httpx, python-dotenv, pypdf, scikit-learn | BSD-3-Clause | runtime, HTTP, documentos, TF-IDF | conservar copyright, licencia y disclaimer |
| asyncpg, python-multipart, prometheus-client, pytesseract | Apache-2.0 | DB, uploads, métricas, OCR | conservar licencia/NOTICE y avisos de patentes |
| `email-validator` | Unlicense según metadatos previos | validación | conservar procedencia; confirmar lock/SBOM |
| `psycopg2-binary` | LGPL-3 con excepción | driver PostgreSQL | incluir texto y respetar excepción/forma de distribución |
| `pypdfium2` + PDFium | Apache-2.0 o BSD-3 + terceros | render PDF | incorporar avisos de PDFium y terceros del wheel |
| Pillow | HPND | imágenes | conservar licencia |
| openpyxl | MIT | XLSX | conservar notice |

Las versiones exactas deben tomarse de `bridge-api/requirements.lock` y del SBOM final, no de los rangos de `requirements.txt`.

## Portal

| Dependencia/grupo | Licencia observada | Uso | Obligación |
|---|---|---|---|
| React / React DOM, Vite plugin, Tailwind, Autoprefixer, Prettier, ESLint | MIT | UI/build/dev | conservar notices en distribución aplicable |
| TypeScript | Apache-2.0 | compilación | conservar licencia/notice |
| Lucide React | ISC | iconos | conservar copyright y permiso |
| Testing Library, Vitest, jsdom y tipos | según lock/SBOM | desarrollo/test | confirmar inventario completo aunque no entren en runtime |

`package-lock.json` es la fuente de versiones; un SBOM generado desde la imagen debe distinguir dependencias de build de las incluidas en el Nginx final.

## Runtime e imágenes

| Componente | Licencia general conocida/archivo upstream | Estado local |
|---|---|---|
| Python 3.12 slim | PSF + Debian packages | Digest fijado; notices de paquetes apt deben entrar en SBOM |
| Node 24 build stage | Node.js/terceros | Digest fijado; normalmente no queda en imagen runtime, comprobar SBOM |
| Nginx 1.30.4 | BSD-2-Clause + terceros | Digest fijado |
| PostgreSQL/pgvector PG15 | PostgreSQL + MIT y terceros | Digest fijado |
| Redis 7.2.14 Alpine 3.21 | BSD-3-Clause | Digest multiarch `sha256:dfa18828cbc07b3ae6a95ec7343f6c214fdee2d836197b4be8e9904420762cd8`; runtime verificado y Trivy 0 HIGH/CRITICAL |
| Tesseract + idioma español | Apache-2.0 y datos entrenados | instalados por apt snapshot; inventariar datos/modelos |

No derive permiso de redistribución de que una imagen sea pública o esté fijada por digest.

## Vendors opcionales

| Componente | Identidad fijada | Evidencia local | Decisión |
|---|---|---|---|
| FlowWink | commit `0cd4e9b8af0d432c9a942a692d8f1fa4a04ec67b` | `vendor/flowwink/LICENSE` MIT | Potencialmente utilizable con atribución; build/distribución aún requieren revisión del SBOM |
| Chatwoot | commit `b05f22da8df103a349c3e820afcb76acb129692a` | raíz MIT para contenido no restringido; `enterprise/LICENSE` exige suscripción válida y prohíbe usos/distribución fuera de sus términos | Excluir `enterprise/` del artefacto core y obtener aprobación legal antes de `full` |
| Activepieces | imagen `0.86.3` por digest; no hay checkout local en `vendor-lock.json` | licencia efectiva de la imagen/SBOM **no verificada localmente** | Stop-ship legal para `full`; no afirmar MIT/CE sin evidencia del artefacto exacto |

`LICENSE` y `THIRD_PARTY_NOTICES.md` ya describen Activepieces como imagen opcional sin checkout/licencia de artefacto verificada. El core `production` no la incluye; cualquier bundle o perfil `full` todavía requiere SBOM, licencia y revisión legal específicos.

## Servicios y modelos externos

OpenAI, Anthropic, Ollama/modelos descargados, PrestaShop, GoHighLevel, SMTP/API email y cualquier fuente/icono/asset añadido están sujetos a sus términos, DPA, región y licencia propia. No hay modelos LLM ni embeddings externos incorporados al core por defecto (`provider=none`, `local_tfidf`). Cualquier modelo futuro requiere tarjeta/licencia, versión/hash, uso comercial, restricciones de output y política de datos.

## Funciones Enterprise no incluidas/certificadas

- contenido bajo `vendor/chatwoot/enterprise/`;
- funciones de pago/Enterprise de Activepieces;
- SSO/MFA y capacidades SaaS no implementadas en el core;
- publicación externa, crawler SEO, envío fiscal o delivery de email;
- cualquier servicio `full` sin su gate legal y técnico.

## Componentes sustituibles

Catálogo, CRM, embeddings, LLM y email están desacoplados mediante configuración/adaptadores. El reemplazo no elimina obligaciones de licencia ni permite reutilizar datos/modelos sin permiso; exige nuevo SBOM, DPA y pruebas.

## Gate legal de release

- [ ] SBOM final por imagen y bundle, con versiones/hash/licencia.
- [ ] `THIRD_PARTY_NOTICES.md` reconciliado con el SBOM.
- [ ] Licencia de Activepieces exacta verificada o servicio excluido.
- [ ] Directorio Enterprise de Chatwoot excluido o licencia comercial archivada.
- [ ] Notices de PDFium, apt, OCR, fuentes, iconos y assets incluidos.
- [ ] Contrato del código propio aprobado.
- [ ] Excepciones/licencias ambiguas firmadas por Legal.

Hasta completar el checklist, el criterio de licencias permanece `PARTIAL` en [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).
