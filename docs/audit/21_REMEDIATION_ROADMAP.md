# 21 - Roadmap de remediación

## Inmediato - 0 a 7 días

| Pri. | Resultado | Componente | Dep. | Esf. | Riesgo | Responsable | Criterio de aceptación / test |
|---|---|---|---|---|---|---|---|
| P0 | Bloquear demo en cliente | Bridge/DB | Ninguna | S | Bajo | Backend | Test de procedencia en todas las rutas |
| P0 | Evitar confirmación ambigua | Commerce/chat | UX copy | M | Medio | Backend+QA | Matriz negación/confirmación; no pedido sin token |
| P0 | Congelar migración destructiva | Alembic | Backup | S/M | Medio | Backend/DBA | Upgrade conserva fixture; downgrade seguro |
| P1 | Corregir proxy y health | Nginx/Compose | Puerto libre | S | Bajo | DevOps | Workers no root, HTTP/ready tras 10 reinicios |
| P1 | Corregir Chatwoot PID | Chatwoot entrypoint | Imagen | S | Bajo | DevOps | Reboot/recreate repetido sano |
| P1 | Egress allowlisted | Redes | Destinos sandbox | S/M | Medio | DevOps/Security | Solo destinos aprobados accesibles |
| P1 | Perfil staging fail-closed | Config/provision | Secretos ficticios | S | Bajo | DevOps/Security | Arranque rechaza defaults/mocks/demo |
| P1 | Retirar FlowWink/AP del MVP | Compose/docs/UI | Decisión producto | S | Medio | Architect/Product | 1 stack mínimo estable sin rutas rotas |
| P1 | Fijar recursos y puerto preflight | Compose/scripts | Capacity | S | Medio | DevOps | Límites + error explícito con puerto ocupado |
| P1 | Actualizar Pypdf/Pillow/Vite | Dependencies | Compatibilidad | M | Medio | Security/Frontend | Audits sin findings conocidos y tests/build pasan |

## Corto plazo - 2 a 4 semanas

| Pri. | Resultado | Componente | Dep. | Esf. | Riesgo | Responsable | Criterio de aceptación / test |
|---|---|---|---|---|---|---|---|
| P0 | Precio/stock/pedido Presta real | Adapter+commerce | Sandbox/ownership | L | Alto | Backend+QA | Golden contract + concurrencia + e2e |
| P1 | GHL idempotente | Adapter/outbox | Sandbox | M/L | Medio | Backend | Fault injection sin duplicados |
| P1 | Chat completo y handoff | CW/Bridge | CW estable/GHL | L | Medio | Full-stack | Widget→respuesta→asignación visible |
| P1 | Backup/restore probado | Scripts/DB/storage | Host aislado | L | Alto | DevOps/DBA | Restore hashes/conteos y RPO/RTO medidos |
| P1 | Observabilidad mínima | Todos | Stable runtime | L | Medio | SRE | Dashboard + alertas por fallos inyectados |
| P1 | Tests PostgreSQL/contract/e2e | QA | Sandboxes | L | Medio | QA/Backend | Gates obligatorios; no mocks en ruta crítica |
| P2 | Portal recortado/profesional | Portal | Matriz real | M | Bajo | Frontend/UX | Links reales, axe y viewports |
| P2 | Import batch y export | Bridge | Ownership | M/L | Medio | Backend | 10k limitado + export round-trip |
| P1 | Licencia/NOTICE/SBOM | Release | Legal/scanners | M | Medio | Legal+Security | Artefacto sin EE no autorizada |

## Medio plazo - 1 a 3 meses

| Pri. | Resultado | Componente | Dep. | Esf. | Riesgo | Responsable | Criterio de aceptación / test |
|---|---|---|---|---|---|---|---|
| P1 | Releases inmutables por cliente | CI/CD | Registry/Git restaurado | L | Medio | Release Eng | Digest, firma, update/rollback ensayado |
| P1 | Modularizar Bridge | Backend | Tests P0 | L/XL | Medio | Architect/Backend | Dominios separados, mismo contrato |
| P1 | RAG seguro/evaluable | AI/RAG | Corpus/policy | L | Medio | AI+Security | Evals calidad, ACL, exfil y latencia |
| P2 | Onboarding repetible | Scripts/docs | Stack estable | L | Medio | DevOps/CS | Instalación nueva firmada por acceptance |
| P2 | Panel proveedor privacy-safe | Control plane | Métricas | L | Alto | Platform/DPO | Solo metadata agregada; test aislamiento |
| P2 | Capacity/cost model | SRE/FinOps | Telemetría 30d | M | Bajo | FinOps | Coste por cliente y límites medidos |
| P2 | Plantilla Ofideep | Product | MVP e2e | M | Bajo | Product/CS | Scope, datos y prompts versionados |

## Largo plazo - 3 a 12 meses

- HA/replicación/regiones solo tras SLO y demanda.
- Catálogo de integraciones con contratos, scopes y ownership.
- Marketplace/plantillas sectoriales con revisión de seguridad/licencia.
- Internacionalización real y localización fiscal.
- Control plane y automatización operativa; SaaS compartido solo si economía, privacidad y aislamiento lo justifican.

## Estimación agregada

- Piloto controlado: **40–60 persona-días** más disponibilidad de sandboxes/credenciales y revisión legal; aproximadamente 4–8 semanas calendario con equipo paralelo.
- Producto comercial repetible: adicional **3–6 persona-meses**, sin incluir HA/SaaS avanzado.
- Rango, no compromiso: debe recalibrarse tras resolver P0 y medir runtime estable.

