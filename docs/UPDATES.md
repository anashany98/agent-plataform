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
