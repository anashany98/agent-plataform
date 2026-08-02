# Plan de Ejecución del Primer Piloto Comercial (30 Días)

**Nombre del Proyecto:** Plataforma de Agentes IA  
**Versión Release Candidate:** `v0.9.0-rc1`  
**Estado:** **`FIRST CLIENT PILOT — READY FOR CONTROLLED GO-LIVE`**  
**Duración:** 30 Días Naturales  

---

## 1. Fases de Activación Progresiva (Fases A – E)

| Fase | Nombre de la Fase | Comportamiento del Agente | Criterio de Transición |
|---|---|---|---|
| **Fase A** | Observación | Analiza conversaciones sin responder al usuario final | 3 días sin discrepancias analíticas |
| **Fase B** | Borradores | Genera respuestas sugeridas para revisión de empleados | Tasa de aprobación > 90% |
| **Fase C** | Respuesta Automática Limitada | Responde automáticamente FAQs y consultas de existencias | 5 días operando sin incidentes |
| **Fase D** | Venta Asistida | Genera presupuestos y borradores de pedido | Aceptación formal escrita |
| **Fase E** | Automatización Controlada | Operación comercial continua bajo `PILOT_MODE=true` | Fin del periodo de 30 días |

---

## 2. Salvaguardas en Modo Piloto (`PILOT_MODE=true`)
- Facturas emitidas únicamente en formato **borrador** (`draft`).
- Descuentos y modificaciones de precios retenidos en cola de aprobación (`/approvals`).
- Límite de consumo mensual de IA configurado en 50,00 USD.
