# 19 - Registro de riesgos

| ID | Riesgo / causa | Prob. | Impacto | Nivel | Señal/trigger | Mitigación | Owner recomendado | Residual |
|---|---|---|---|---|---|---|---|---|
| R-01 | Oferta/pedido con datos demo o precio/stock erróneo | Alta | Crítico financiero/reputación | Crítico | `source=demo`, divergencia Presta | Gating de procedencia + autoridad Presta | Product + Backend | Bajo tras e2e |
| R-02 | Pedido sin consentimiento por parser textual | Alta | Crítico/legal | Crítico | Negaciones con “acepto” | State machine + confirmación explícita | Backend + QA | Bajo |
| R-03 | Integraciones principales inaccesibles | Alta | Flujo comercial nulo | Alto | Sin default route/credenciales | Egress allowlist + sandboxes | DevOps | Medio |
| R-04 | Pérdida/no recuperación de datos | Media | Crítico | Crítico | Restore nunca ejecutado | DR consistente y ensayos | DevOps/DBA | Medio |
| R-05 | Duplicados GHL/transacciones por retry | Media | Alto | Alto | Caída entre efectos | Outbox/idempotency/reconcile | Backend | Bajo/medio |
| R-06 | Agotamiento de host por vendor/loops/build | Alta | Alto, afecta coexistencia | Alto | RAM >90 %, CPU/tráfico AP | Límites, aislar hosts, retirar vendor | DevOps | Medio |
| R-07 | Exposición documental RAG | Media | Alto privacidad | Alto | Paráfrasis/ACL abierta | Deny-by-default/DLP/evals | Security + AI | Medio |
| R-08 | Coste LLM incontrolado | Media futura | Alto financiero | Alto | Estimador 0/usage no medido | Hard budgets/telemetría/kill switch | AI Platform | Bajo |
| R-09 | Incidentes invisibles | Alta | Alto/SLA | Alto | Fallos actuales sin alerta | Observabilidad/SLO/runbook | SRE | Medio |
| R-10 | Licencia EE/propiedad intelectual | Media | Alto legal/comercial | Alto | Vendor EE en artefacto | Legal, exclusión y SBOM | Legal + Release | Bajo/medio |
| R-11 | CVE en parser/upload/supply chain | Media | Alto seguridad | Alto | Advisories/imagen flotante | Pin/update/scan/sign | Security | Medio |
| R-12 | Actualización rompe todas las instancias | Alta | Alto | Alto | Checkout global/no Git | Imágenes inmutables por cliente | Release Eng | Bajo |
| R-13 | Acceso cruzado por misconfiguración | Baja-media | Crítico privacidad | Alto | Volumen/secret compartido | Preflight IDs, guards y test de aislamiento | DevOps/Security | Bajo |
| R-14 | Producto vendido por encima de capacidad | Alta | Alto reputación/margen | Alto | UI/docs anuncian módulos muertos | Catálogo contractual y acceptance matrix | Product/Sales | Bajo |
| R-15 | Coste operativo no escalable | Alta a >5 | Alto margen | Alto | 14 servicios/cliente | Simplificar MVP y control plane gradual | Architecture/FinOps | Medio |
| R-16 | Privacidad/retención incumplida | Media | Alto legal | Alto | Sin export/delete/DPA | Data lifecycle y asesoría legal | DPO/Product | Medio |

## Tratamiento

- R-01/R-02/R-04 son stop-ship.
- R-03/R-05/R-06/R-09/R-10/R-11/R-12/R-14 bloquean piloto controlado.
- Ningún riesgo se acepta por defecto; aceptación residual requiere responsable y fecha.
- No se asignan probabilidades numéricas por falta de datos históricos.

