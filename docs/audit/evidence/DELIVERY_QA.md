> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# QA del paquete de entrega

**Fecha:** 2026-08-02  
**Resultado:** PARTIALLY VERIFIED

La estructura y los artefactos documentales están verificados. Las capacidades del producto conservan sus estados individuales; este control no cambia ningún `BLOCKED`, `BROKEN` o `NOT IMPLEMENTED` del informe.

## Controles reproducidos

| Control | Resultado |
|---|---|
| Informes obligatorios | 22 informes de fase + Markdown/HTML/PDF presentes |
| Vocabulario de estados | Todas las celdas `Estado` usan uno de los nueve valores permitidos |
| Registro de defectos | 30 filas: 5 P0, 21 P1, 4 P2 y 0 P3 |
| Tabla maestra | IDs continuos M-01 a M-35 |
| HTML | Parser sin error; 50 enlaces, 0 destinos internos rotos |
| Markdown | 12 enlaces en origen y release, 0 destinos internos rotos |
| PDF | 14 páginas A4 apaisadas; texto contiene decisión, sección 35 y M-35 |
| Inspección visual PDF | Portada, índice, texto, diagramas, decisión y tabla maestra revisados tras render Poppler |
| Secretos | Ningún valor no vacío de claves sensibles del `.env` apareció en textos del release |
| PII | Sin coincidencias de email o teléfono español en textos del release |
| Integridad | Cada archivo del paquete queda cubierto por `MANIFEST.sha256` |

## Límites

- Este QA verifica la entrega documental, no reabre el runtime ni supera los bloqueos de RAM.
- Capturas UX dinámicas y SBOM final siguen `BLOCKED`; sus razones están en `SCREENSHOTS_STATUS.md` y `SBOM_STATUS.md`.
- No se atribuye validez comercial ni funcional al PDF, HTML o manifiesto por el mero hecho de que se generen correctamente.
