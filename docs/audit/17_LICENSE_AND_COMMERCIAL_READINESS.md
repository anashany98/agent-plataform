# 17 - Licencias y preparación comercial

## Veredicto

**Preparación comercial: BROKEN. Decisión: NO-GO — CRITICAL RISK.** Es posible construir una oferta con componentes permisivos, pero la entrega actual mezcla código EE, avisos inexactos, código propio sin licencia explícita y un producto técnicamente no operativo.

## Procedencia y licencias

| Elemento | Evidencia | Estado | Riesgo o condición pendiente |
|---|---|---|---|
| Código propio Bridge/Portal/scripts | No existe `LICENSE` raíz | BLOCKED | Titularidad y derechos de venta no formalizados |
| FlowWink | MIT; archivos clave coinciden con commit | PARTIALLY VERIFIED | El runtime requiere Supabase; la procedencia integral no es demostrable sin Git |
| Chatwoot | MIT salvo `enterprise/` | PARTIALLY VERIFIED | `enterprise/` está presente y el build copia el árbol |
| Activepieces | MIT salvo `packages/ee/` y server EE | PARTIALLY VERIFIED | Riesgo si se redistribuye vendor o funcionalidad EE sin suscripción |
| Dependencias Python | Predominio permisivo; sin lock/SBOM completo | PARTIALLY VERIFIED | Inventario y obligaciones incompletos |
| Portal | React/Tailwind MIT; Lucide ISC; resto por lock | PARTIALLY VERIFIED | Deben conservarse avisos y cerrarse el inventario |
| PostgreSQL/pgvector/Redis/Nginx | PostgreSQL/MIT/BSD | PARTIALLY VERIFIED | Deben conservarse avisos y verificarse las imágenes finales |
| Tesseract/OCR | Apache-2.0 y dependencias | PARTIALLY VERIFIED | NOTICE de la imagen por revisar |
| Modelos/embeddings | Nombres configurados, modelos no accesibles | BLOCKED | Licencia, pesos y redistribución no inventariados |
| Assets/fuentes | Sin assets propios; iconos Lucide | PARTIALLY VERIFIED | Inventario final pendiente |

No es asesoramiento jurídico. Se requiere revisión legal antes de vender o redistribuir.

## Discrepancias documentales

- `THIRD_PARTY_NOTICES.md` afirma “Enterprise plugins excluded” para Chatwoot; es falso en el árbol/contexto de build observado.
- Activepieces se describe como MIT sin explicar sus rutas EE presentes.
- Las versiones de FastAPI/SQLAlchemy y otros componentes del notice están obsoletas respecto a requisitos resueltos.
- `VERSIONS.md` declara vendor limpio. Los hashes existen y archivos representativos coinciden, salvo Dockerfile Chatwoot modificado localmente; sin `.git` no puede afirmarse “clean clone”.
- La frase “client-owned” no sustituye un contrato/licencia/copyright notice.

## Qué podría venderse tras remediación

- Servicios profesionales de instalación/integración y lógica propia, sujeto a acreditar titularidad.
- Una distribución que use únicamente partes comunitarias y mantenga copyright/licencias/NOTICE.
- Referencias a imágenes oficiales en vez de redistribuir binarios/vendor cuando sus términos lo aconsejen.
- Configuración/operación de Chatwoot/Activepieces CE sin activar EE, validado por legal y técnicamente.

## Qué no debe prometerse hoy

- Producto listo para cliente, agente con tool calling, catálogo/stock/precio real, GHL/chat e2e, facturación, SEO, alertas, restore, SLA o escalado.
- Funciones Enterprise incluidas gratuitamente.
- Cumplimiento, certificación, RPO/RTO, alta disponibilidad o coste controlado.

## Preparación operativa/comercial

| Área | Estado | Gap |
|---|---|---|
| Instalación | IMPLEMENTED BUT NOT TESTED | Scripts no reproducidos; TLS/puerto/recursos |
| Branding | CONFIGURED ONLY | Portal genérico |
| Onboarding | CONFIGURED ONLY | Plantillas, sin ejecución/aceptación |
| Importadores | PARTIALLY VERIFIED | Solo local; sin escala/export |
| Formación/soporte | CONFIGURED ONLY | Documentos genéricos; sin runbook/SLA |
| Monitorización | NOT IMPLEMENTED | Sin alertas/dashboards |
| Backup/update | BROKEN | Sin restore; Git ausente |
| Privacidad | NOT IMPLEMENTED | Sin DPA, retención, export/borrado |
| Eliminación | NOT IMPLEMENTED | Sin proceso seguro |
| Documentación | BROKEN | Contradicciones y afirmaciones no verificadas |

## Entregables legales/comerciales requeridos

1. Licencia/copyright del código propio y cadena de titularidad.
2. SBOM SPDX/CycloneDX por release, NOTICE corregido y política de OSS.
3. Exclusión técnica/artefacto separado de rutas EE o licencia comercial correspondiente.
4. Inventario de licencias de modelos, embeddings, OCR, imágenes y assets.
5. DPA, política de privacidad/retención, subencargados y residencia.
6. Alcance/SLA explícito, soporte, backup/restore ensayado y criterios de aceptación.

## Archivos revisados, riesgos y pendiente

Licencias vendor, manifests, Docker contexts, notices, onboarding y docs comerciales. SBOM/imagen completo queda BLOCKED por recursos; la decisión legal requiere responsable cualificado.
