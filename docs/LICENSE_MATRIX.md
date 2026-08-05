# Matriz de licencias

*Generada/revisada 2026-08-04. Las licencias de dependencias Python se leyeron de
`importlib.metadata` (campo `License`/clasificadores) del entorno de desarrollo.
Las de frontend vienen de los metadatos de npm. Los componentes *vendor* se
leyeron de sus `LICENSE`/docs. **Nada aquí declara redistribución permitida sin
revisión legal** (B-008); las filas marcadas *Requiere revisión legal* necesitan
aprobación antes de cualquier release comercial.*

## Dependencias Python (bridge-api/requirements.txt)

| Paquete | Licencia | Uso | Restricción relevante |
|---|---|---|---|
| fastapi | MIT | API | Ninguna |
| uvicorn | BSD-3 | Servidor ASGI | Ninguna |
| pydantic / pydantic-settings | MIT | Validación | Ninguna |
| email-validator | Unlicense | Validación email | Ninguna |
| python-multipart | Apache-2.0 | Uploads | Ninguna |
| sqlalchemy | MIT | ORM | Ninguna |
| alembic | MIT | Migraciones | Ninguna |
| asyncpg | Apache-2.0 | Driver Postgres | Ninguna |
| psycopg2-binary | LGPL-3 con excepciones | Driver Postgres | Excepción de enlace; uso como driver no obliga a copyleft del resto |
| pgvector | MIT | Vectores | Ninguna |
| redis | MIT | Cliente Redis | Ninguna |
| httpx | BSD-3 | HTTP | Ninguna |
| python-dotenv | BSD-3 | Env | Ninguna |
| prometheus-client | Apache-2.0 | Métricas | Ninguna |
| pypdf | BSD-3 | PDF | Ninguna |
| pypdfium2 | (Apache-2.0 OR BSD-3) + PdfiumThirdParty | OCR/render | Revisar avisos de PDFium |
| pytesseract | Apache-2.0 | OCR | Requiere binario Tesseract (Apache-2.0) |
| Pillow | HPND | Imágenes | Ninguna |
| python-docx | MIT | DOCX | Ninguna |
| openpyxl | MIT | XLSX | Ninguna |
| beautifulsoup4 | MIT | HTML | Ninguna |
| scikit-learn | BSD-3 | TF-IDF local | Ninguna |

## Frontend (portal/package.json)

| Paquete | Licencia | Uso | Restricción |
|---|---|---|---|
| react / react-dom | MIT | UI | Ninguna |
| lucide-react | ISC | Iconos | Ninguna |
| vite / @vitejs/plugin-react | MIT | Build | Ninguna |
| typescript | Apache-2.0 | Tipado | Ninguna |
| tailwindcss / autoprefixer | MIT | Estilos | Ninguna |
| prettier / eslint | MIT | Dev | Ninguna |
| @types/react / @types/react-dom | MIT | Dev | Ninguna |

## Componentes vendor

| Componente | Licencia declarada | Uso | Estado |
|---|---|---|---|
| FlowWink | MIT (LICENSE en `vendor/flowwink`) | SPA/capa de agentes (opcional, fuera del core) | OK comercial con atribución |
| Chatwoot | MIT (Community Edition) + rutas `enterprise/` | Chat (opcional) | **Requiere revisión legal**: las rutas EE pueden exigir licencia comercial si se habilitan |
| Activepieces | MIT (Community Edition) | Automatizaciones (opcional) | **Requiere revisión legal**: confirmar alcance CE y funciones EE antes de distribuir |

## No incluidas / requiere revisión legal (B-008)

- Funciones Enterprise de Chatwoot/Activepieces no habilitadas ni licenciadas.
- Modelos/LLM externos (OpenAI/Anthropic/etc.): sujetos a sus propios términos; el core opera con `ollama`/local sin depender de ellos.
- Fuentes/iconos/assets de terceros no inventariados al detalle: revisar antes de release.
