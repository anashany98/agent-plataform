> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Documento histórico; sus estados, rutas o contratos pueden no corresponder al árbol actual. Consulte `docs/PRODUCTION_READINESS.md` y la documentación canónica homónima de 2026-08-15.

# Environment Audit

**Generated Date:** 2026-07-31  
**Platform:** Windows 11 Pro 64-bit  
**RAM Available:** ~32 GB  
**Disk Space:** ~22.1 GB free on C:  

## System Tooling & Versions

- **Git:** 2.52.0
- **Docker:** 29.5.3
- **Docker Compose:** v5.1.4
- **Node.js:** v24.13.0
- **npm:** 11.6.2
- **pnpm:** 10.33.2
- **Python:** 3.11.7

## Occupied Ports Detected
- 80, 443 (Existing Nginx Manager)
- 8000, 8001 (Existing Confeccion Central app instances)
- 8080 (Existing Flowwink standalone container)
- 5432 (Local Postgres manager)
- 6379 (Local Redis manager)
- 16161, 17171 (RRHH Backend / Frontend)
- 54321, 54322, 54323, 54324, 54327 (Supabase studio/kong/db/analytics)

## Container Sandbox Test
- Docker daemon is running cleanly and executed commands without errors.
