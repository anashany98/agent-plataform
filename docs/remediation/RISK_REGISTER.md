# Registro de riesgos de producción

**Fecha:** 2026-08-02
**Candidata evaluada:** ninguna
**Decisión vigente:** `NOT PRODUCTION READY — CRITICAL RISK`

La probabilidad y el impacto son cualitativos porque aún no existe telemetría ni carga reproducible de una candidata. Un riesgo solo se reduce con evidencia enlazada; una corrección de código sin prueba permanece abierta.

| ID | Riesgo | Probabilidad | Impacto | Defectos | Control actual | Tratamiento obligatorio | Responsable | Indicador de cierre | Estado |
|---|---|---|---|---|---|---|---|---|---|
| R-001 | Oferta, pedido o reserva incorrectos/no consentidos | Media | Crítico comercial y financiero | D-001–D-004, D-033, D-034 | Seis P0 verificados; contratos y concurrencia PostgreSQL | Completar paginación/visibilidad PrestaShop y E2E de candidata | Backend/Commerce/Security | Cero regresiones P0, regla 501, producto oculto y golden sandbox/local | BLOCKED |
| R-002 | Pérdida o corrupción de datos durante migración/restore/rollback | Media-alta | Existencial | D-005, D-015, D-016 | Alembic clean/histórica/downgrade-reupgrade verificado; recovery commit | Backup consistente y restore/rollback de release aislados | Data/DevOps | Fixture y flujo sobreviven upgrade, restore y rollback; RPO/RTO medidos | BLOCKED |
| R-003 | Acceso cruzado entre clientes o fuga documental | Media | Crítico de seguridad/privacidad | D-020, D-029, D-031 | 14 modelos scoped y 12 FKs compuestas verificadas; DB/red por instancia | ACL RAG cerrada, archivos y export/erase auditados | Architecture/Security | Matriz completa de dos clientes sin enumeración ni fuga | BLOCKED |
| R-004 | Plataforma inaccesible o integraciones inoperantes | Alta | Alto/stop-ship | D-006–D-009, D-019 | Contenedores y volúmenes conservados | Egress allowlisted, proxy unprivileged, PID robusto, puerto/preflight y chat local/real | DevOps/Integrations | Arranque repetido, HTTP, chat y conectividad positiva/negativa | BLOCKED |
| R-005 | Efectos externos duplicados o éxitos ficticios | Alta | Alto comercial/operativo | D-010, D-011, D-013, D-021, D-035, D-036 | Confirmación P0 atómica; integraciones/import aún parciales | Inbox/outbox/lease/CAS, contratos estrictos, retries acotados, reconciliación y DLQ | Backend/Integrations | Fault injection y concurrencia con un efecto/decisión máximo y sin pérdida | BLOCKED |
| R-006 | Agentes ejecutan fuera de política o consumen presupuesto sin límite | Alta si se habilita IA | Alto de seguridad/coste | D-012, D-014 | Mock explícito en tests; guard production-like parcial | Executor deny-by-default, usage/tarifario, presupuesto atómico y kill switch | AI/Security/FinOps | Tool evals y límite de coste disparan de forma reproducible | BLOCKED |
| R-007 | Vulnerabilidades explotables al procesar archivos o servir el portal | Alta | Alto de seguridad/disponibilidad | D-017 | Versiones acotadas, sin locks con hashes | Upgrade, corpus malicioso, SCA continuo, imágenes/SBOM y política de excepciones | Security/Platform | Cero high/critical sin aceptación documentada | BLOCKED |
| R-008 | Host degradado u OOM sin detección | Alta | Alto, también afecta otros proyectos | D-024, D-025, D-028 | Healthchecks parciales | Budgets CPU/RAM/pids, readiness real, logs/métricas/trazas/alertas y soak | SRE/DevOps | Idle/soak dentro de budget y fault injection alerta | BLOCKED |
| R-009 | Venta o redistribución sin derechos demostrados | Media-alta | Crítico legal/comercial | D-018, D-023 | `THIRD_PARTY_NOTICES.md` parcial | Resolver titularidad, LICENSE, EE, modelos, SBOM y revisión legal del artefacto | Legal/Product/Release | Aprobación escrita sobre release concreta | BLOCKED |
| R-010 | Decisiones basadas en documentación/tests falsamente positivos | Media-alta | Alto de gobierno y calidad | D-026, D-027, D-030, D-032, D-037 | Readiness autoritativo; verificador P0 guardado y probado con `-O` | Docs derivadas de gates, tests herméticos, CI y E2E visual/funcional | QA/Documentation/Product | CI verde y claims trazados a evidencia de candidata | BLOCKED |

## Stop-ship

La promoción queda prohibida si se cumple cualquiera de estas condiciones:

1. Existe un P0 abierto o una operación sensible sin consentimiento/idempotencia.
2. Demo, datos de otro cliente o documentos sin ACL pueden llegar a una ruta cliente.
3. Precio, impuesto o stock carecen de una autoridad explícita y snapshot trazable.
4. Una migración, restore o rollback puede borrar o mezclar datos.
5. Ingress/egress, servicios esenciales, tests críticos, restore, licencias o build reproducible no están verificados.

Los diez riesgos permanecen `BLOCKED`. El cierre de los seis P0 reduce R-001/R-002/R-003, pero los riesgos residuales P1, restore, runtime y release siguen impidiendo un piloto real.
