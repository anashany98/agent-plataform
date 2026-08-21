> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# 04 - Mapa de dependencias

## Grafo operacional

| Origen | Destino | Motivo | Estado | Fallo dominante |
|---|---|---|---|---|
| Usuario | Reverse proxy | Entrada HTTP | BROKEN | Sin publicación efectiva y Nginx sin workers |
| Reverse proxy | Portal/Bridge/vendors | Enrutamiento | BROKEN | Capability `SETUID` ausente |
| Portal | Bridge | Auth, dashboard, costes, aprobaciones | IMPLEMENTED BUT NOT TESTED | Runtime visual sin acceso |
| Bridge | Bridge DB | Persistencia | VERIFIED | Sin migraciones evolutivas seguras |
| Bridge | Bridge Redis | Caché/límites previstos | CONFIGURED ONLY | Uso funcional no demostrado |
| Bridge | PrestaShop | Catálogo real | BROKEN | Credenciales vacías y sin ruta por defecto |
| Bridge | GHL | Lead/oportunidad | BROKEN | Credenciales vacías y sin ruta por defecto |
| Bridge | Chatwoot | Respuesta/handoff | BROKEN | Chatwoot caído, API sin token |
| Chatwoot Worker | Bridge webhook | Mensajes entrantes firmados | IMPLEMENTED BUT NOT TESTED | Sin datos/configuración e2e |
| Bridge | Activepieces | Automatizaciones | BROKEN | API key/flujos ausentes; sin egress |
| Bridge | Ollama/cloud LLM | LLM/embeddings | BROKEN | `Network is unreachable` |
| FlowWink | Supabase | Estado y lógica FlowWink | BROKEN | Variables vacías; no servicio Supabase en Compose |

## Dependencias de build y supply chain

- Python usa rangos, sin lock ni hashes. `pip-audit` resolvió 53 paquetes y encontró vulnerabilidades en `pypdf 5.9.0` y `Pillow 11.3.0`.
- Portal tiene `package-lock.json`; `npm audit` informó 1 alta y 1 moderada (`vite`/`esbuild`).
- Imágenes se fijan por tag, no digest. `ollama/ollama:latest` aparece en override GPU.
- Bases pgvector usan tres líneas PostgreSQL distintas (14/15/16), elevando mantenimiento.
- Activepieces runtime usa imagen oficial; el checkout vendor no participa en ese build.
- Chatwoot y FlowWink se construyen desde vendor. El Dockerfile Chatwoot difiere del commit declarado en el fallback de `.git_sha`.

## Verificación vendor

Los tres hashes declarados existen en GitHub. Tras normalizar finales de línea, 11 de 12 archivos representativos coinciden con los commits declarados: README/licencia/manifiestos y Dockerfiles de FlowWink/Activepieces, y README/licencia/versión de Chatwoot. `vendor/chatwoot/docker/Dockerfile` tiene una modificación local no declarada: sustituye el `git rev-parse` obligatorio por un identificador temporal `local-build-<timestamp>`. Sin `.git` no puede probarse que el resto de cada árbol esté limpio.

## Acoplamiento y sustitución

| Componente | Acoplamiento | Sustitución | Recomendación MVP |
|---|---|---|---|
| Bridge | Alto, núcleo | L/XL | Mantener y modularizar por dominio |
| Portal | Medio, API propia | M | Mantener solo pantallas reales |
| Chatwoot | Medio por REST/webhook | M | Mantener si el widget es requisito |
| Activepieces | Bajo/medio | S/M | Retirar hasta existir automatización real |
| FlowWink | Bajo, hoy aislado | S | Retirar del despliegue MVP |
| Redis Bridge | Bajo | XS/S | Retirar si no se implementa uso distribuido |
| PrestaShop/GHL | Alto para MVP comercial | Contrato externo | Añadir adapters robustos y tests de sandbox |

## Archivos revisados

Manifiestos, locks, Dockerfiles, Compose, adaptadores, imports, vendor focalizado y URLs de commits oficiales.

## Riesgos y pendiente

- SPOF en proxy/Bridge; cadena externa completa sin egress.
- Supply chain no reproducible y avisos de versiones obsoletos.
- SBOM/escaneo de imagen BLOCKED por RAM de host > 90 %.
- Falta matriz de compatibilidad entre versiones de vendor y contratos API.
