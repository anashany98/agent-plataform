# Informe maestro actual — `agent-platform`

**Fecha:** 31/07/2026  
**Estado oficial:** `REMEDIATED CODEBASE — LIVE VALIDATION REQUIRED`

## Resumen

La base de código ha sido corregida tras una auditoría que demostró problemas críticos de autenticación, seguridad de webhooks, asociación de conversaciones, idempotencia, stock, modelos IA, RAG, portal e integraciones. Las correcciones están implementadas y cubiertas por pruebas automatizadas internas.

No se conserva ninguna declaración anterior de “commercial ready” como válida. Esas versiones se encuentran en `docs/archive/unverified-original/`.

## Evidencia interna

- 31 pruebas superadas.
- 67 % cobertura backend.
- Alembic reversible.
- Compilación Python y TypeScript correctas.
- Compose analizado con 14 servicios.
- Sin secretos detectados en código propio.

## Estado por área

| Área | Estado |
|---|---|
| Autenticación y RBAC | Verificado mediante tests |
| Webhooks firmados | Verificado mediante tests |
| Comercio transaccional | Verificado mediante tests |
| Concurrencia de stock | Verificado mediante tests |
| Aprobaciones | Verificado mediante tests |
| Importadores | Verificado parcialmente mediante tests |
| PrestaShop | Adaptador y contratos verificados; API real pendiente |
| GHL | Adaptador y contratos verificados; API real pendiente |
| Chatwoot | Adaptador y firma verificados; widget real pendiente |
| Activepieces | Adaptador verificado; flujo real pendiente |
| LLM | Adaptadores implementados; proveedores reales pendientes |
| RAG | Implementado; PostgreSQL/embeddings reales pendientes |
| Portal | TypeScript verificado; build Docker/navegador pendiente |
| Backup/restore | Scripts corregidos; ejecución Docker pendiente |
| Update/rollback | Scripts corregidos; ejecución real pendiente |
| Producción/piloto | No autorizado todavía |

## Decisión

- **Staging:** GO.
- **Piloto Ofideep:** pendiente del checklist vivo.
- **Producción general:** NO-GO.
