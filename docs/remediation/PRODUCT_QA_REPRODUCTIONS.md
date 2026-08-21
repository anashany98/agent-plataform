> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# Reproducciones QA de producto — Fase 1

## 1. Control de la ejecución

- **Fecha:** 2 de agosto de 2026, zona horaria `Europe/Madrid`.
- **Workspace:** `agent-platform-fixed`.
- **Rama observada:** `production-remediation`.
- **Commit observado al iniciar:** `4d4a6e9` (`docs: establish production remediation baseline`).
- **Alcance:** D-017, D-026, D-027, D-029 y D-030.
- **Método:** auditorías de dependencias no mutantes, analizadores en modo comprobación y búsquedas estáticas en código propio/documentación activa.
- **Exclusiones:** no se instalaron ni actualizaron dependencias, no se aplicaron fixes, no se arrancó Docker, no se ejecutó eliminación de datos y no se inspeccionaron `node_modules`, `dist`, vendor ni documentación archivada.
- **Integridad:** `bridge-api/requirements.txt` y `portal/package-lock.json` no presentan diff después de las auditorías; el hash del lockfile fue idéntico antes y después de `npm audit`.

Las entradas de una auditoría no equivalen necesariamente a vulnerabilidades raíz distintas: se registran por separado el total mostrado por la herramienta y los identificadores primarios únicos. Ningún hallazgo de este documento se considera corregido.

## 2. Resultado consolidado

| ID | Reproducción | Evidencia actual | Estado |
|---|---|---|---|
| D-017 | Dependencias vulnerables sin fix aplicado | `pip-audit`: 60 entradas/53 IDs primarios únicos en dos paquetes; `npm audit`: una vulnerabilidad high y una moderate | BLOCKED |
| D-026 | Claims documentales contradictorios | Tres documentos activos mantienen claims incompatibles con el readiness autoritativo y no están marcados como superseded | BLOCKED |
| D-027 | Portal incompleto y sin tests | Siete anchors, cinco destinos ausentes; cero archivos de test y ningún script de test | BLOCKED |
| D-029 | Sin exportación, eliminación ni retención por cliente | Cero rutas, archivos de lifecycle o controles de retención encontrados en código propio | BLOCKED |
| D-030 | Quality gates y monolito | Ruff 286, Black 15 archivos, MyPy 80 errores, sin pipeline CI y `main.py` con 1.192 líneas | BLOCKED |

## 3. D-017 — Auditorías actuales de dependencias

### 3.1 Toolchain y comandos

| Herramienta | Versión observada | Comando reproducido | Código de salida |
|---|---:|---|---:|
| Python | 3.11.7 | `C:/Users/PC/AppData/Local/Programs/Python/Python311/python.exe --version` | 0 |
| pip-audit | 2.10.0 | `C:/Users/PC/AppData/Local/Programs/Python/Python311/python.exe -m pip_audit -r bridge-api/requirements.txt` | 1 |
| pip-audit | 2.10.0 | mismo alcance con `--format=json` para contar IDs únicos | 1 |
| npm | 11.6.2 | desde `portal/`: `npm audit --package-lock-only --ignore-scripts --json` | 1 |

### 3.2 Python

`pip-audit` resolvió 53 dependencias y devolvió `Found 60 known vulnerabilities in 2 packages`.

| Paquete resuelto | Entradas mostradas | IDs primarios únicos | Versiones de fix observadas | Restricción actual |
|---|---:|---:|---|---|
| `pypdf 5.9.0` | 35 | 35 | desde 6.0.0 hasta 6.14.2 según advisory | `pypdf>=5.0.0,<6` |
| `Pillow 11.3.0` | 25 | 18 | desde 12.1.1 hasta 12.3.0 según advisory | `Pillow>=10.4.0,<12` |

Resultado agregado: **60 entradas y 53 IDs primarios únicos**. Las siete entradas adicionales de Pillow son IDs repetidos en la salida, no siete vulnerabilidades distintas demostradas.

Las restricciones de `bridge-api/requirements.txt:16` y `:19` excluyen todas las versiones de fix mostradas por la auditoría. Esto implica un cambio de versión mayor y exige comprobar compatibilidad y el corpus de parsers; no se aplicó ese cambio durante la reproducción.

### 3.3 Frontend

El lockfile v3 resolvió `vite 5.4.21` y `esbuild 0.21.5`. `npm audit` informó:

| Paquete | Relación | Severidad npm | Resultado |
|---|---|---|---|
| `vite` | directa | high | Advisories de traversal/paths y handling de editor en el tooling de desarrollo |
| `esbuild` | transitiva vía Vite | moderate | El servidor de desarrollo puede exponer respuestas a sitios externos |

Resumen npm: **2 vulnerabilidades**, `0 critical`, `1 high`, `1 moderate`, `0 low`. La auditoría usó solo el lockfile y `--ignore-scripts`; no modificó el manifiesto ni ejecutó scripts de instalación.

### 3.4 Causa y gate

- **Causa observada:** rangos mayores antiguos en Python y Vite 5 en el lockfile; no existe evidencia de un gate continuo que impida reintroducir versiones afectadas.
- **Impacto:** parsers de documentos y tooling frontend permanecen asociados a advisories conocidos. No se infiere explotabilidad concreta sin reproducir cada advisory contra el modo de despliegue.
- **Gate para desbloquear:** actualizar de forma controlada, fijar/hashear dependencias, ejecutar corpus malicioso y regresión, repetir ambos audits y añadirlos al pipeline. Hasta entonces: **BLOCKED**.

## 4. D-026 — Claims documentales contradictorios

### 4.1 Comandos y alcance

Se buscaron claims activos con `rg` en Markdown propio, excluyendo `docs/archive/**`, `docs/audit/**` y este directorio de reproducciones. También se buscaron las marcas obligatorias `SUPERSEDED` y `NO UTILIZAR PARA DECISIONES ACTUALES` en los documentos conflictivos.

### 4.2 Contradicciones reproducidas

El estado autoritativo en `docs/PRODUCTION_READINESS.md:7` es `NOT PRODUCTION READY — CRITICAL RISK`, con `0/30` criterios `VERIFIED` en la línea 64. Frente a ello:

| Documento activo | Claim | Contraste actual |
|---|---|---|
| `docs/MASTER_PLATFORM_REPORT.md:4` | Estado oficial `REMEDIATED CODEBASE — LIVE VALIDATION REQUIRED` | Compite con la única fuente autoritativa y atribuye un estado no permitido para readiness |
| `docs/MASTER_PLATFORM_REPORT.md:16` | “Alembic reversible” | `bridge-api/alembic/versions/0001_initial_schema.py:28` ejecuta `Base.metadata.drop_all` |
| `docs/MASTER_PLATFORM_REPORT.md:25-29` | Auth/RBAC, webhooks, comercio, concurrencia y aprobaciones “Verificado mediante tests” | La suite histórica usa SQLite, demo y stubs; las reproducciones P0/P1 siguen abiertas |
| `docs/MASTER_PLATFORM_REPORT.md:44` | “Staging: GO” | No hay build limpio, restore, E2E crítico ni release candidata aprobada |
| `docs/REMEDIATION_REPORT.md:6,321` | “GO para staging controlado” | Contradice los stop-ship y el gate de readiness actual |
| `docs/REMEDIATION_REPORT.md:21` | Upgrade → downgrade → upgrade “Superada” | El downgrade actual borra todas las tablas; no acredita preservación de datos |
| `docs/WEBHOOKS.md:6-7,16,18` | `X-Bridge-Signature`, idempotencia Redis 24 h e invocación FlowWink | El código usa headers `X-Chatwoot-*`, persistencia `IdempotencyRecord` en DB y no invoca FlowWink en el webhook |

Los tres documentos de la tabla tienen **cero** marcas `SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES`. El checklist `docs/LIVE_VALIDATION_CHECKLIST.md` expresa condiciones futuras y no se contó como claim de cumplimiento actual.

- **Causa observada:** informes de una remediación anterior siguen en la documentación activa y mezclan código presente, tests simulados y evidencia runtime.
- **Impacto:** un operador puede autorizar staging o confiar en migraciones, webhooks y comercio basándose en evidencia que no satisface el gate actual.
- **Gate para desbloquear:** reconciliar cada claim con evidencia vigente, archivar o marcar explícitamente los informes sustituidos y mantener una sola decisión autoritativa. Estado: **BLOCKED**.

## 5. D-027 — Portal, anchors y ausencia de tests

### 5.1 Búsqueda estática

Se extrajeron los `href="#..."` e `id="..."` de `portal/src/App.tsx` y se enumeraron archivos de test bajo `portal/`, excluyendo `node_modules/**` y `dist/**`.

| Medida | Resultado |
|---|---:|
| Anchors de navegación | 7 |
| Destinos existentes | 2: `resumen`, `aprobaciones` |
| Destinos ausentes | 5: `agentes`, `automatizaciones`, `catalogo`, `documentos`, `usuarios` |
| Archivos `*.test.*`, `*.spec.*`, `tests/` o `__tests__/` | 0 |
| Scripts de test/e2e en `portal/package.json` | 0 |

Los anchors están en `portal/src/App.tsx:254-260`; solo existen secciones correspondientes en las líneas 279 y 311. `portal/package.json` contiene `dev`, `build`, `preview`, `typecheck` y `format:check`, pero no `test`, `lint` o `e2e`. Tampoco declara Vitest, Jest, Playwright ni Testing Library.

- **Causa observada:** la navegación anuncia módulos no renderizados y el frontend carece de harness de test.
- **Impacto:** enlaces sin destino, promesa funcional falsa y ausencia de detección automática de regresión, permisos visuales o accesibilidad.
- **Gate para desbloquear:** recortar o implementar cada destino y ejecutar tests de componentes, E2E y accesibilidad básica en los viewports definidos. Estado: **BLOCKED**.

La comprobación es estática; no se declara UX visual verificada.

## 6. D-029 — Exportación, eliminación y retención por cliente

### 6.1 Búsqueda estática

Alcance: `bridge-api/app`, `portal/src` y `scripts`, solo código propio. Se buscaron rutas y archivos asociados a `export`, `erase/erasure`, `retention/retención`, lifecycle y eliminación de `client`, `tenant` o `customer`.

| Evidencia | Resultado |
|---|---:|
| Rutas API de lifecycle de cliente | 0 |
| Archivos cuyo nombre implemente export/erase/retention/lifecycle | 0 |
| Controles o políticas de retención en código | 0 |

Existe `DELETE /rag/documents/{doc_id}`, pero elimina un documento RAG aislado y no constituye exportación o borrado integral de un cliente. Los scripts de backup, provisionado y actualización reciben `CLIENT_ID`, pero no implementan portabilidad, retención ni eliminación segura del conjunto de datos.

- **Causa observada:** no existe un servicio común de data lifecycle ni ownership ejecutable por recurso.
- **Impacto:** lock-in, datos residuales y ausencia de evidencia para solicitudes de exportación o borrado.
- **Límite de reproducción:** no se ejecutó ninguna eliminación porque sería destructiva; la ausencia se verificó estáticamente.
- **Gate para desbloquear:** inventario por cliente, exportación completa y borrado auditable sobre fixtures sintéticos, política de retención y pruebas de residuos en DB, objetos, índices y backups. Estado: **BLOCKED**.

## 7. D-030 — Quality gates y monolito

### 7.1 Comandos reproducidos

| Herramienta | Versión | Comando | Resultado | Código |
|---|---:|---|---|---:|
| Ruff | 0.7.4 | `python -m ruff check bridge-api/app --output-format=json` | 286 hallazgos en 15 archivos; 177 con fix disponible | 1 |
| Ruff | 0.7.4 | `python -m ruff check bridge-api/app tests --output-format=json` | 297 hallazgos en 18 archivos; 179 con fix disponible | 1 |
| Black | 26.5.1 | `python -m black --check bridge-api/app` | 15 archivos se reformatearían; 1 quedaría igual | 1 |
| MyPy | 2.3.0 | `python -m mypy bridge-api/app` | 80 errores en 5 archivos; 16 módulos comprobados | 1 |

La cifra **286** corresponde exclusivamente al código de producción. La cifra **297** incluye además 11 hallazgos en los tests existentes; ambas son correctas para alcances distintos.

Distribución Ruff principal: `UP006` 120, `B008` 90, `UP007` 34, `UP035` 21, más imports, formato y otros diagnósticos. `bridge-api/app/main.py` concentra 124 hallazgos Ruff y tiene **1.192 líneas**.

### 7.2 Gate ausente

- No hay archivos bajo `.github/` ni otro pipeline CI reconocido en el workspace.
- `Makefile` ejecuta pytest/typecheck y un target de lint parcial, pero no integra Black, MyPy, `pip-audit`, `npm audit`, frontend tests, SBOM o escaneo de imágenes.
- `portal/package.json` no define test runner ni lint ejecutable.

- **Causa observada:** monolito tipado de forma incompleta y controles locales no convertidos en gates obligatorios.
- **Impacto:** cambios de negocio lentos, regresiones difíciles de aislar y posibilidad de publicar aun con analizadores en código 1.
- **Gate para desbloquear:** baseline acordada, corrección incremental por dominio y CI que bloquee nuevos hallazgos antes de reducir la deuda existente. Estado: **BLOCKED**.

## 8. Decisión de esta tanda

Los cinco defectos permanecen **BLOCKED**. Esta reproducción acredita el estado actual de manifests, documentación y código estático; no acredita explotabilidad de cada advisory, calidad visual, cumplimiento legal, aislamiento runtime ni preparación para producción.
