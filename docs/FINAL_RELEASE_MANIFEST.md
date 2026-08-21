# Borrador — manifiesto documental de release

> **DRAFT / NO ES UN MANIFIESTO EJECUTABLE.** El JSON generado y sus checksums serán la fuente mecánica. Este documento facilita revisión humana y permanece `PENDING` hasta crear la candidata.

## Identidad

| Campo | Valor esperado/final |
|---|---|
| Producto | Agent Platform |
| Versión | PENDING (`0.9.1-<sha12>`) |
| Tag | PENDING |
| `SOURCE_COMMIT` | PENDING SHA completo |
| Árbol limpio | PENDING |
| Fecha build UTC | PENDING |
| Perfil | `production` core |
| Formato manifest JSON | PENDING |
| SHA-256 manifest/bundle | PENDING |

## Servicios core

| Servicio | Imagen/tag | Digest/ID construido | OCI version/revision | Scan/SBOM |
|---|---|---|---|---|
| `tls-proxy` | Nginx 1.30.4 Alpine 3.24 | digest configurado; verificar final | PENDING | PENDING |
| `reverse-proxy` | Nginx 1.30.4 Alpine 3.24 | digest configurado; verificar final | PENDING | PENDING |
| `portal` | `agent-platform-portal:<release>` | PENDING | PENDING | PENDING |
| `bridge-api` | `agent-platform-bridge-api:<release>` | PENDING | PENDING | PENDING |
| `bridge-db` | pgvector/pgvector PG15 | digest configurado; verificar final | PENDING | PENDING |
| `bridge-redis` | Redis 7.2.14 Alpine 3.21 BSD-3 | `sha256:dfa18828cbc07b3ae6a95ec7343f6c214fdee2d836197b4be8e9904420762cd8` | N/A, imagen externa | Trivy 0 HIGH/CRITICAL; SBOM final PENDING |

## Runtime/build bases auditadas

| Base | Digest declarado en el árbol | Validación candidata |
|---|---|---|
| Python 3.12.13 slim-bookworm | `sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2` | PENDING |
| Node 24.18.0 alpine3.24 | `sha256:a0b9bf06e4e6193cf7a0f58816cc935ff8c2a908f81e6f1a95432d679c54fbfd` | PENDING |
| Nginx 1.30.4 alpine3.24 | `sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46` | PENDING |
| Bridge PG15 | `sha256:a20a57d7aa5217a6af0a391ccf69f4a8512406d6c14be08132f801468cc3cc62` | PENDING |
| Redis 7.2.14 Alpine 3.21 | `sha256:dfa18828cbc07b3ae6a95ec7343f6c214fdee2d836197b4be8e9904420762cd8` | VERIFIED: runtime 7.2.14; Trivy 0 HIGH/CRITICAL |

## Esquema y compatibilidad

| Elemento | Valor |
|---|---|
| Alembic head | `0013` |
| Backup format | 4 |
| Restore mínimo compatible | PENDING |
| Versión anterior soportada para update | PENDING |
| Release de rollback | PENDING |

## Artefactos del bundle

- [ ] código fuente exacto sin `.git`, cachés, datos, logs ni secretos;
- [ ] `.env.example` y configuración production;
- [ ] Compose/migraciones/scripts/tests;
- [ ] documentación operativa y decisión final;
- [ ] SBOM por imagen y bundle;
- [ ] third-party notices/licencias reconciliados;
- [ ] checksums y firmas;
- [ ] release notes, instalación, update, rollback y DR;
- [ ] evidencia final referenciada, sin datos reales.

## Gates vinculados

| Gate | Resultado/evidencia |
|---|---|
| Preflight release | PENDING |
| Build reproducible | PENDING |
| Trivy | PARTIAL: Redis PASS; resto PENDING |
| Secret scan | PENDING |
| Tests/E2E | PENDING |
| Restore/rollback | PENDING |
| Performance/soak | PENDING |
| Aprobación legal | PENDING |
| Firma release owner | PENDING |

Vendors `full` no deben aparecer en el manifest core. Si se crea una edición `full`, necesita manifest, licencia, SBOM, scans y decisión independientes.
