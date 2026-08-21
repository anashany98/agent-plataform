> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Documento histórico; sus estados, rutas o contratos pueden no corresponder al árbol actual. Consulte `docs/PRODUCTION_READINESS.md` y la documentación canónica homónima de 2026-08-15.

# Guía de Pruebas de Aceptación de Usuario (UAT) del Cliente

**Cliente:** [Nombre de la Empresa]  
**Instancia Aislada:** `agent-piloto-rc1`  

---

## 18 Escenarios de Prueba UAT:
1. Acceso e inicio de sesión en el Admin Portal (`http://localhost:3400`).
2. Recuperación y cambio de contraseña.
3. Consulta de producto en el chat web (Chatwoot).
4. Consulta de tarifa personalizada de cliente.
5. Verificación de comportamiento ante producto sin existencias.
6. Generación automática de presupuesto.
7. Confirmación de pedido por parte del cliente.
8. Retención en cola de aprobación humana (`/approvals`).
9. Transferencia fluida a un agente humano.
10. Consulta a la Base de Conocimiento RAG.
11. Verificación de abstención ante pregunta sin evidencia.
12. Importación de productos vía asistente / CSV.
13. Consulta de métricas de consumo y costes de IA.
14. Visualización de estado del sistema y alertas.
15. Exportación de datos de conversaciones y presupuestos.
16. Cierre de sesión seguro.
17. Verificación de navegación en teléfono móvil.
18. Alternancia entre modo claro y modo oscuro.
