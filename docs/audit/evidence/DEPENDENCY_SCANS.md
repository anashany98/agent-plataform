> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# Evidencia de dependencias

## Python

`pip-audit -r bridge-api/requirements.txt`:

```text
exit=1; dependencies=53; vulnerable_dependencies=2; advisory identifiers=60
pypdf 5.9.0
Pillow 11.3.0
```

El número de IDs contiene advisories agregados/duplicados; consultar el JSON de un scan futuro antes de asignar CVSS.

## npm

`npm audit --json`:

```text
total=2; critical=0; high=1; moderate=1; low=0
vite: high, direct
esbuild: moderate, transitive
```

El fix propuesto por npm requiere Vite 8.2.0 (salto mayor).

## Imágenes

Docker Scout está disponible, pero el scan quedó BLOCKED al superar el host 90 % de RAM. No se inventa resultado.
