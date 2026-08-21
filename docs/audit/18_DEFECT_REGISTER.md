> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# 18 - Registro de defectos

Escala: P0 crítica, P1 alta, P2 media, P3 baja. Esfuerzo: XS <4 h, S 1 día, M 2–5 días, L 1–3 semanas, XL >3 semanas.

| ID | Área / descripción | Evidencia y causa raíz | Impacto / prob. | Sev. | Solución | Esf. / deps. | Riesgo de corrección | Test de regresión |
|---|---|---|---|---|---|---|---|---|
| D-001 | Catálogo demo presentado como verificado | 100 `source=demo`; búsqueda sin filtro; seed activo | Precio/stock/producto inventado; alta | P0 | Separar namespaces, excluir demo y mostrar procedencia/frescura | S / ownership | Romper demos | Ninguna ruta cliente devuelve demo |
| D-002 | `no acepto` confirma pedido | Substring `acepto`/`confirmar`; sin state machine | Pedido/factura no autorizados; alta | P0 | Intent parser determinista + token de confirmación/estado | M / UX-chat | Cambiar conversación | Tabla de negaciones/adversarial |
| D-003 | Precio incorrecto | Specific prices/variantes se almacenan pero no se usan; IVA default | Cobro/oferta incorrecta; alta | P0 | Motor contractual PrestaShop con snapshot | L / sandbox | Diferencias fiscales | Golden tests por variante/grupo/IVA |
| D-004 | Stock/reserva diverge de PrestaShop | `reserved_stock` solo local, sin TTL/release/write | Oversell; alta | P0 | Reserva/pedido en autoridad, lock/idempotencia y reconciliación | L / PrestaShop | Contención/compatibilidad | Concurrencia N compradores |
| D-005 | Migración destructiva/no evolutiva | `create_all`; downgrade `drop_all` | Pérdida total de datos; media | P0 | Migraciones explícitas, backup gate, prohibir downgrade destructivo | M / schema | Migración existente | Upgrade/rollback con fixture |
| D-006 | Sin egress para integraciones | Redes `internal`; no default route; Ollama errno 101 | Flujo principal inutilizable; alta | P1 | Red egress separada, firewall/allowlist/DNS | S/M / DevOps | Ampliar SSRF | Conectividad solo a destinos permitidos |
| D-007 | Chatwoot no reinicia | PID stale `/app/tmp/pids/server.pid` | Chat sin servicio; alta | P1 | Entrypoint valida/elimina PID y graceful shutdown | S | Ocultar PID legítimo | Reboot/recreate repetido |
| D-008 | Proxy sin workers | Falta CAP_SETUID; `setuid(101)`; master solo | Toda entrada rota; alta | P1 | Nginx unprivileged o caps mínimas correctas | XS/S | Superficie de privilegio | Arranque + process/HTTP/health |
| D-009 | Puerto/proxy no publicado | 9000 ocupado por otro stack; container sin public/bind | Inaccesible; alta en host | P1 | Preflight puerto, puerto por cliente, fail-fast | S | Cambiar URLs | Provision con puerto ocupado |
| D-010 | GHL no idempotente/atómico | Efectos externos antes del registro; oportunidad siempre create | Duplicados/estado parcial; media-alta | P1 | Outbox, idempotency key, upsert y reconciliación | M/L / sandbox | Compatibilidad API | Fault injection en cada paso |
| D-011 | Race de aprobación | Read-then-write sin lock/CAS | Estado de factura incoherente; media | P1 | Update condicional/row lock y versionado | S | Deadlocks | Approve/reject concurrentes |
| D-012 | “Agente” sin tool calling | Chat heurístico; `allowed_tools` inerte | Alucinación/promesa falsa; alta | P1 | O implementar loop de tools seguro o renombrar/reducir | L | Complejidad LLM | Evals allowlist/no-tool |
| D-013 | Activepieces fabrica éxito | Fallback `exec-*` ante 2xx sin ID | Evidencia falsa; alta | P1 | Exigir schema/ID y consultar estado | S | Romper APIs antiguas | 2xx sin ID debe fallar |
| D-014 | Kill switch de coste inerte | `_estimate_cost` siempre 0 | Coste ilimitado/no detectable; alta si LLM activo | P1 | Tarifario versionado, usage real y hard limit | M | Bloqueo falso | Presupuesto y concurrent usage |
| D-015 | Backup no verificable/completo | No restore; omite cache/Redis/config; snapshot no coordinado | Recuperación incierta; alta | P1 | Diseño DR, snapshot consistente y restore automatizado | L | Restore destructivo | Restore aislado con hashes |
| D-016 | Update/rollback rotos | No `.git`; checkout global compartido | Sin parche/rollback seguro; alta | P1 | Releases inmutables/digests y migraciones compatibles | L | Cambiar distribución | Upgrade+rollback por cliente |
| D-017 | Parsers/deps vulnerables | pip audit pypdf/Pillow; npm Vite/esbuild | DoS/seguridad supply chain; media-alta | P1 | Actualizar, pin/hash, scan/SBOM | M | Breaking changes | Corpus malicioso + build |
| D-018 | FlowWink es shell vacío | Supabase env vacío y sin backend | Función ficticia/consumo; alta | P1 | Retirar MVP o desplegar backend real | S o L | Pérdida de promesa | Ruta útil real o ausencia del servicio |
| D-019 | Chat/lead/handoff incompletos | DB CW vacía; sin captura posterior; handoff solo open | MVP Ofideep falla; alta | P1 | Onboarding, state machine lead y asignación | L / CW+GHL | Flujo UX | E2E widget→asignación |
| D-020 | RAG exfiltrable por paráfrasis | Keyword denylist; ACL por defecto abierta a roles read | Fuga documental; media | P1 | Clasificación, ACL deny-by-default, DLP/policy | M/L | Más abstenciones | Dataset de exfil/prompt injection |
| D-021 | Integraciones sin resiliencia | Sin retry/backoff/circuit/outbox | Pérdida/duplicado de eventos; alta | P1 | Librería común de resiliencia + DLQ | L | Retry storm | 429/5xx/timeouts/caídas |
| D-022 | Piloto ejecuta `development` | Validación estricta solo prod-like; admin no fuerza cambio | Baseline seguridad omitida; alta | P1 | Perfil staging fail-closed y preflight | S | Impedir entorno local | Arranque con secretos/defaults inválidos |
| D-023 | Licencias/notices incorrectos | EE presente; “excluded”; código propio sin LICENSE | Bloqueo legal/comercial; media-alta | P1 | Revisión legal, excluir EE, LICENSE/NOTICE/SBOM | M | Cambiar packaging | Scan de rutas/artefacto |
| D-024 | Health falso positivo | `/health` DB error responde 200; Compose no usa ready | Incidente no detectado; alta | P2 | Semántica liveness/readiness separada | S | Restart loops | DB caída y códigos HTTP |
| D-025 | Sin límites y loops de recursos | No limits; AP/Redis CPU/tráfico; build RAM 95,3 % | Host degradado; alta | P1 | Límites, pids, diagnosticar loop y capacity gate | M | Throttling | Soak/idle 60 min |
| D-026 | Documentación afirma evidencia falsa | GO staging, ownership y backup contradictorios | Decisión comercial errónea; alta | P2 | Docs generadas desde evidencia/release gates | S/M | Cambio organizativo | Checklist de claims |
| D-027 | Portal incompleto/sin pruebas | Links a secciones ausentes; no test runner | UX rota/regresiones; alta | P2 | Recortar navegación y tests e2e/a11y | M | Alcance visible | Playwright/axe/viewports |
| D-028 | Sin observabilidad/alertas | Logs dispersos, costes 0, no dashboards | Incidentes invisibles; alta | P1 | Telemetría mínima, SLO y alertas | L | Ruido/PII | Fault injection + alerta |
| D-029 | Sin export/eliminación/retención | No endpoints/scripts/políticas | Riesgo privacidad/lock-in; media | P1 | Lifecycle de datos por cliente | L / legal | Borrado irreversible | Export+delete fixture auditado |
| D-030 | Quality gates y monolito | Ruff 297, MyPy 71, format fail, main 1.192 líneas | Cambio lento/defectos; alta | P2 | CI, modularizar por dominio y tipar ORM | L | Refactor de negocio | Suite + contract tests sin regresión |

## Notas

- No todos los defectos son independientes: D-001/003/004 forman el riesgo transaccional principal; D-006 bloquea todas las integraciones.
- La prioridad de corrección no autoriza activar flujos reales antes de completar tests de aceptación.
- Escaneos de imagen pueden añadir defectos; quedaron BLOCKED por recursos.
