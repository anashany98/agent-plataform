# Changelog

Todos los cambios relevantes de la remediación se documentan aquí. El proyecto adopta SemVer cuando exista una primera candidata reproducible.

## [Unreleased]

### Added

- Prompt operativo raíz en `agents.md`.
- Repositorio Git local y rama `production-remediation`.
- Punto de recuperación pre-remediación `ed77056`.
- Registros autoritativos `TASKS.md`, `STATUS.md`, `DECISIONS.md` y `BLOCKERS.md`.
- Baseline, plan de remediación, readiness y evidencia persistente en `docs/`.
- Registro de 32 defectos, registro de riesgos y evidencia reproducible de Fase 1.
- Diecinueve tests rojos de regresión para aislamiento, demo, confirmación, comercio, migración, integraciones y seguridad.

### Changed

- El estado comercial queda fijado en `NOT PRODUCTION READY — CRITICAL RISK` hasta superar todos los gates.
- Los resultados históricos se tratan como evidencia previa, no como verificación actual.
- La Fase 0 queda cerrada con baseline de host/Git/Docker, inventario, dependencias, propiedad de datos y 30 criterios de readiness bloqueados.
- La Fase 1 contrasta 30 defectos heredados y añade D-031/D-032 sin aplicar todavía correcciones de producción.

### Security

- Se comprobó que `.env` permanece ignorado por Git.
- El escaneo de patrones de secretos previo al recovery commit no detectó coincidencias de alta señal en código propio.
