# Registro de riesgos de producción

**Fecha:** 2026-08-02
**Candidata evaluada:** ninguna
**Decisión vigente:** `NOT PRODUCTION READY — CRITICAL RISK`

La probabilidad y el impacto son cualitativos porque aún no existe telemetría ni carga reproducible de una candidata. Un riesgo solo se reduce con evidencia enlazada; una corrección de código sin prueba permanece abierta.

| ID | Riesgo | Probabilidad | Impacto | Defectos | Control actual | Tratamiento obligatorio | Responsable | Indicador de cierre | Estado |
|---|---|---|---|---|---|---|---|---|---|
| R-001 | Oferta, pedido o reserva incorrectos/no consentidos | Media | Crítico comercial y financiero | D-001–D-004, D-033, D-034 | Seis P0, paginación y visibilidad PrestaShop verificados localmente; concurrencia PostgreSQL | Completar E2E de candidata contra snapshot/provider autorizado | Backend/Commerce/Security | Cero regresiones P0, regla 501, producto oculto y golden sandbox/local | BLOCKED |
| R-002 | Pérdida o corrupción de datos durante migración/restore/rollback | Media-alta | Existencial | D-005, D-015, D-016 | Alembic clean/histórica/downgrade-reupgrade verificado; recovery commit | Backup consistente y restore/rollback de release aislados | Data/DevOps | Fixture y flujo sobreviven upgrade, restore y rollback; RPO/RTO medidos | BLOCKED |
| R-003 | Acceso cruzado entre clientes o fuga documental | Media | Crítico de seguridad/privacidad | D-020, D-029, D-031 | 14 modelos scoped, 12 FKs compuestas y ACL RAG deny-by-default verificadas | Clasificación/DLP, corpus adversarial, archivos y export/erase auditados | Architecture/Security | Matriz completa de dos clientes sin enumeración ni fuga | BLOCKED |
| R-004 | Plataforma inaccesible o integraciones inoperantes | Alta | Alto/stop-ship | D-006–D-009, D-019 | Contenedores y volúmenes conservados | Egress allowlisted, proxy unprivileged, PID robusto, puerto/preflight y chat local/real | DevOps/Integrations | Arranque repetido, HTTP, chat y conectividad positiva/negativa | BLOCKED |
| R-005 | Efectos externos duplicados o éxitos ficticios | Media-alta | Alto comercial/operativo | D-010, D-011, D-013, D-021, D-035, D-036 | CAS, ID estricto e import atómico verificados; retries, inbox/lease y checkpoints parciales | Reconciliación/outbox/DLQ y fault injection en cada frontera externa ambigua | Backend/Integrations | Concurrencia y crash conservan un efecto/decisión máximo y ninguna pérdida | BLOCKED |
| R-006 | Agentes ejecutan fuera de política o consumen presupuesto sin límite | Alta si se habilitan tools | Alto de seguridad/coste | D-012, D-014 | Usage/tarifario y presupuesto atómico verificados en PostgreSQL | Executor deny-by-default, schemas/policy y kill switch | AI/Security/FinOps | Tool evals y límite de coste disparan de forma reproducible | BLOCKED |
| R-007 | Vulnerabilidades explotables al procesar archivos o servir el portal | Alta | Alto de seguridad/disponibilidad | D-017 | Versiones acotadas, sin locks con hashes | Upgrade, corpus malicioso, SCA continuo, imágenes/SBOM y política de excepciones | Security/Platform | Cero high/critical sin aceptación documentada | BLOCKED |
| R-008 | Host degradado u OOM sin detección | Alta | Alto, también afecta otros proyectos | D-024, D-025, D-028 | Liveness/readiness separados y fallo DB señalizado; sin prueba de stack | Budgets CPU/RAM/pids, logs/métricas/trazas/alertas y soak | SRE/DevOps | Idle/soak dentro de budget y fault injection alerta | BLOCKED |
| R-009 | Venta o redistribución sin derechos demostrados | Media-alta | Crítico legal/comercial | D-018, D-023 | `THIRD_PARTY_NOTICES.md` parcial | Resolver titularidad, LICENSE, EE, modelos, SBOM y revisión legal del artefacto | Legal/Product/Release | Aprobación escrita sobre release concreta | BLOCKED |
| R-010 | Decisiones basadas en documentación/tests falsamente positivos | Media-alta | Alto de gobierno y calidad | D-026, D-027, D-030, D-032, D-037 | Readiness autoritativo; verificador P0 guardado y probado con `-O` | Docs derivadas de gates, tests herméticos, CI y E2E visual/funcional | QA/Documentation/Product | CI verde y claims trazados a evidencia de candidata | BLOCKED |

## Stop-ship

La promoción queda prohibida si se cumple cualquiera de estas condiciones:

1. Existe un P0 abierto o una operación sensible sin consentimiento/idempotencia.
2. Demo, datos de otro cliente o documentos sin ACL pueden llegar a una ruta cliente.
3. Precio, impuesto o stock carecen de una autoridad explícita y snapshot trazable.
4. Una migración, restore o rollback puede borrar o mezclar datos.
5. Ingress/egress, servicios esenciales, tests críticos, restore, licencias o build reproducible no están verificados.

Los diez riesgos permanecen `BLOCKED`. Los cierres P0/P1 reducen R-001, R-003, R-005, R-006 y R-008, pero el alcance parcial de efectos externos, restore, runtime, seguridad del executor y release sigue impidiendo un piloto real.
