# Runbook de Soporte e Incidencias — Piloto Comercial

**Versión:** `v0.9.0-rc1`  
**Canal de Incidencias:** `soporte@agentplatform.es`  
**Teléfono de Guardia P1:** `+34 900 111 222`  

---

## Clasificación de Severidad y Tiempos de Respuesta:

| Niveles de Severidad | Definición | SLA Respuesta | Acción de Escalado |
|---|---|---|---|
| **P1 — Crítico** | Caída completa de la instancia del cliente | **< 15 minutos** | Notificación al Ingeniero DevOps de Guardia |
| **P2 — Alto** | Degradación de función principal (ej. Chatwoot) | **< 1 hora** | Intervención del Desarrollador Principal |
| **P3 — Medio** | Error menor con alternativa funcional | **< 4 horas** | Revisión y parche en siguiente ventana |
| **P4 — Bajo** | Consulta general o sugerencia | **< 24 horas** | Registro en backlog de producto |
