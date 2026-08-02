# Estado del SBOM

**Estado: BLOCKED.**

- Manifiestos disponibles: requirements Python, package-lock npm, vendor manifests, tags de imágenes.
- Docker Scout disponible.
- Generación/scan de imágenes no ejecutado por RAM > 90 % tras build.
- No se entrega un SBOM inventado o incompleto bajo etiqueta SPDX/CycloneDX.

Acción: ejecutar en host limpio, exportar CycloneDX/SPDX por imagen y validar licencias/advisories antes de release comercial.

