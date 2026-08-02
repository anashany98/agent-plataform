# Limitaciones conocidas autoritativas

**Estado:** `NOT PRODUCTION READY — CRITICAL RISK`

1. El catálogo activo contiene 100 productos demo y la búsqueda actual no garantiza excluirlos de respuestas comerciales.
2. La confirmación conversacional depende de coincidencias de texto y puede interpretar negaciones como aceptación.
3. Pricing y stock no están integrados end-to-end con una autoridad real; variantes, precios específicos, impuestos, reservas, expiración y reconciliación están incompletos.
4. La migración inicial usa `create_all` y el downgrade contiene `drop_all`; no debe ejecutarse sobre datos valiosos.
5. Chatwoot Web no sobrevivió a reinicio por PID obsoleto y el proxy Nginx quedó sin workers por capabilities incompatibles.
6. Bridge, Chatwoot y Activepieces carecían de ruta egress; APIs y modelos externos no eran alcanzables.
7. PrestaShop, GHL, Chatwoot, Activepieces y modelos externos no tienen credenciales sandbox ni flujo end-to-end verificado.
8. FlowWink es una SPA sin backend Supabase operativo; Activepieces no contiene flujos reales.
9. La suite backend histórica usa SQLite, demo, mocks/stubs y TF-IDF local; no demuestra el producto real.
10. No existen tests frontend, E2E visual ni verificación completa responsive/accesible.
11. El backup no se ha restaurado en una instalación vacía; RPO y RTO no están medidos.
12. No hay observabilidad, alertas ni fault-injection suficientes para sostener un SLA.
13. El build limpio completo fue cancelado por superar el límite seguro de memoria; las imágenes actuales no constituyen una release reproducible.
14. El workspace original carecía de Git. El historial local comienza en `ed77056` y no demuestra procedencia anterior.
15. Licencia del código propio, rutas Enterprise vendor, modelos y SBOM requieren resolución técnica y legal antes de redistribuir.

Estas limitaciones solo se retiran cuando `TASKS.md` contiene evidencia y un commit verificable para el criterio correspondiente.
