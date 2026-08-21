> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Documento histórico; sus estados, rutas o contratos pueden no corresponder al árbol actual. Consulte `docs/PRODUCTION_READINESS.md` y la documentación canónica homónima de 2026-08-15.

# Upstream Update Procedure

## Updating Vendor Repositories
1. Inspect vendor repository status:
   ```bash
   make clone
   ```
2. Pull upstream updates into integration branches inside `vendor/flowwink`, `vendor/chatwoot`, `vendor/activepieces`.
3. Update `VERSIONS.md` with new commits and audit dates.
4. Rebuild images and test:
   ```bash
   make build
   make test
   ```
