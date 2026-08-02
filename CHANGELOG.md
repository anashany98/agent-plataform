# Changelog

Todos los cambios relevantes de la remediación se documentan aquí. El proyecto adopta SemVer cuando exista una primera candidata reproducible.

## [Unreleased]

### Added

- Prompt operativo raíz en `agents.md`.
- Repositorio Git local y rama `production-remediation`.
- Punto de recuperación pre-remediación `ed77056`.
- Registros autoritativos `TASKS.md`, `STATUS.md`, `DECISIONS.md` y `BLOCKERS.md`.
- Baseline, plan de remediación, readiness y evidencia persistente en `docs/`.

### Changed

- El estado comercial queda fijado en `NOT PRODUCTION READY — CRITICAL RISK` hasta superar todos los gates.
- Los resultados históricos se tratan como evidencia previa, no como verificación actual.
- La Fase 0 queda cerrada con baseline de host/Git/Docker, inventario, dependencias, propiedad de datos y 30 criterios de readiness bloqueados.

### Security

- Se comprobó que `.env` permanece ignorado por Git.
- El escaneo de patrones de secretos previo al recovery commit no detectó coincidencias de alta señal en código propio.
