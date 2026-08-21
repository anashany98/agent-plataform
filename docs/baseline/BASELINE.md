# Baseline técnico actual

**Captura:** 2026-08-15, Europe/Madrid

**Workspace:** `C:\Users\Usuario\Desktop\Agent\agent-plataform`

**Rama:** `production-remediation`

**Commit de partida observado:** `e7a123fd0c45`
**Árbol:** con cambios de remediación aún sin integrar; no es una release inmutable.

Este baseline sustituye la captura de otro equipo y otro host del 2 de agosto de 2026. Describe el checkout compartido actual. No se leyeron valores de secretos ni se modificaron contenedores, redes o volúmenes.

## Host y toolchain

| Elemento | Valor observado |
|---|---|
| SO | Windows 11 Pro `10.0.26200` |
| CPU | AMD Ryzen 9 9950X, 16 núcleos/32 hilos |
| RAM | 93,6 GiB totales; 46,2 GiB libres durante la captura |
| Disco `C:` | 16,9 GiB libres durante la captura |
| GPU | AMD Radeon integrada y dos NVIDIA GeForce RTX 4070 detectadas por Windows |
| Git | 2.49.0.windows.1 |
| Docker Engine | 29.5.3, cliente y servidor |
| Docker Compose | v5.1.4 |
| Python host | 3.11.6; la imagen Bridge usa Python 3.12.13 fijado por digest |
| Node host | v22.14.0; la imagen de build del Portal usa Node 24.18.0 fijado por digest |
| npm / pnpm | 10.9.2 / 10.7.0 |
| PostgreSQL observado | 15.18 dentro del contenedor Bridge de desarrollo |
| Redis observado | El stack dev stale usaba 7.4.9; el core remediado fija y verificó runtime Redis 7.2.14 Alpine 3.21 BSD-3 |

La capacidad libre de disco está por debajo del objetivo operativo de 30 GiB y próxima al mínimo de 15 GiB aplicado por el preflight. No se debe ejecutar un prune automático: el daemon aloja proyectos ajenos a esta entrega.

## Estado Docker observado

El proyecto de desarrollo `agent-platform` tiene 14/14 contenedores en estado `healthy`, entre ellos Bridge, Portal, proxy, FlowWink, Chatwoot y Activepieces. Ese runtime lleva datos/configuración previos, publica HTTP en `9000` y Chatwoot en `3003`, y **no certifica la candidata de producción**.

También existen numerosos contenedores, redes y volúmenes de otros proyectos. Debe desplegarse la candidata con un `COMPOSE_PROJECT_NAME`, puertos, redes, volúmenes y archivo `.env.<cliente>` exclusivos.

Puertos relevantes ocupados durante la captura: `1234`, `3001`, `3003`, `3030`, `5432`, `8000`, `9000`, `9001`, `9090`, `9093`, `9464` y `11434`, además de puertos del sistema. No se deben reutilizar sin comprobar el propietario.

## Topología declarada

| Perfil | Servicios esperados | Finalidad | Estado de evidencia |
|---|---:|---|---|
| `core` | 5 | Bridge API, PostgreSQL, Redis, Portal y proxy HTTP ligado a loopback | Configuración verificada; no es el perfil final TLS |
| `production` | 6 | `core` más terminador TLS; Bridge sin red pública ni ruta por defecto | Verificadores estáticos/red PASS; arranque final de candidata PENDING |
| `full` | 14 | Core más FlowWink, Chatwoot y Activepieces | Config válida; vendors no certificados para producción |
| `development` | Override parcial | Desarrollo de Bridge con debug/pilot | No usar para clientes |

El perfil `production` usa proveedores LLM `none`, embeddings `local_tfidf` y correo `local`. Así funciona sin PrestaShop, GHL, Chatwoot, FlowWink, Activepieces ni egress. Las imágenes externas están fijadas por `tag@sha256`; Bridge y Portal se construyen con dependencias lock y etiquetas OCI de versión/revisión.

## Evidencia de calidad disponible

| Control | Resultado recibido | Alcance |
|---|---|---|
| Backend | 384 passed, 9 skipped | Corpus hermético del árbol actual; no sustituye el E2E final de la imagen |
| Migraciones PostgreSQL | Cadena hasta `0013` verificada | Instalación/upgrade/rollback técnico; restore integral final sigue PENDING |
| Quality gates | hard 0, clean 0, ratchet 128 ≤ 243 | Ruff sobre el árbol actual |
| Portal | 25/25 tests, typecheck, formato, build y audit npm PASS | Tests de componente; candidato visual completo PENDING |
| Infra | verificadores de perfiles, preflight, red, proxy, backup-format y vendor pins PASS | Contratos/configuración; no equivale a despliegue release |
| Redis core | 7.2.14 Alpine 3.21 por digest; Trivy 0 HIGH/CRITICAL | Runtime/base externa verificados; no cubre las demás imágenes finales |

## Bloqueos de promoción vigentes

1. Checkout limpio y commit/tag de release aún no disponibles.
2. Imágenes finales de Bridge/Portal y demás bases, escaneo Trivy restante y SBOM final aún no cerrados; Redis sí está verificado.
3. Certificado público válido, DNS y secretos del cliente aún no suministrados.
4. Arranque aislado del perfil `production`, E2E final, restore integral y rollback aún no certificados.
5. Soak/carga y alertas externas aún no verificados.
6. `full` y sus vendors quedan fuera del alcance certificado.

La decisión autoritativa y los 30 gates están en [`../PRODUCTION_READINESS.md`](../PRODUCTION_READINESS.md).
