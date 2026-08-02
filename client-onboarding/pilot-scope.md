# Alcance y Límites del Piloto Comercial de 30 Días

**Duración del Piloto:** 30 Días Naturales  
**Entorno:** Instalación Aislada Single-Tenant (`PILOT_MODE=true`)  

---

## 1. Capacidades Incluidas en el Piloto
- Atención conversacional automatizada en canal Webchat (Chatwoot).
- Respuestas a preguntas sobre productos, fichas técnicas y Base de Conocimiento RAG.
- Búsqueda en tiempo real de catálogo y existencias en almacén.
- Cálculo automático de presupuestos y tarifas personalizadas por cliente.
- Creación de borradores de pedido y reserva atómica de existencias.
- Transferencia fluida a agentes humanos cuando sea solicitado.

## 2. Límites y Salvaguardas Activas
- Facturas definitivas emitidas únicamente en formato **borrador**.
- Descuentos superiores a la tarifa asignada requieren aprobación en el panel administrativo (`/approvals`).
- Límite máximo de presupuesto mensual de IA configurado.
- Reembolsos directos automáticos deshabilitados.
