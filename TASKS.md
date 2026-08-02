# Tareas

## Cerradas

- [x] Eliminar falsos positivos de autenticación e integraciones.
- [x] Implementar usuarios, sesiones, contraseña temporal y RBAC.
- [x] Exigir HMAC oficial de Chatwoot y protección antirreplay.
- [x] Corregir confirmación cruzada entre conversaciones.
- [x] Evitar pedidos, reservas, facturas y aprobaciones duplicadas.
- [x] Hacer atómica la reserva de stock y el proceso de confirmación.
- [x] Aplicar tarifas, impuestos y exenciones determinísticamente.
- [x] Sustituir respuestas LLM falsas por adaptadores reales que fallan cerrados.
- [x] Sustituir el RAG simulado por persistencia, extracción, embeddings y citas reales.
- [x] Sustituir el portal CDN/demo por código React/TypeScript reproducible.
- [x] Implementar adaptadores reales para Chatwoot y Activepieces.
- [x] Añadir PrestaShop: productos, características, combinaciones, precios específicos y stock.
- [x] Añadir GHL: contacto, oportunidad y nota con idempotencia.
- [x] Endurecer Docker Compose, proxy, redes, secretos y health checks.
- [x] Corregir backups, restore, actualización, rollback y aprovisionamiento.
- [x] Crear pruebas de regresión para los defectos críticos.

## Pendientes antes del piloto

- [ ] Ejecutar build limpio de los 14 servicios con Docker.
- [ ] Validar portal en navegador, responsive, modo claro y oscuro.
- [ ] Crear inbox/widget real de Chatwoot y ejecutar conversación completa.
- [ ] Ejecutar un flujo real desde Activepieces y comprobar historial/reintento.
- [ ] Conectar PrestaShop de Ofideep con clave de solo lectura.
- [ ] Ejecutar dry-run y conciliación de 100–300 productos reales.
- [ ] Verificar variantes, características, precios e inventario de una muestra manual.
- [ ] Conectar subcuenta GHL y crear contacto/oportunidad real de prueba.
- [ ] Configurar modelo real y probar indisponibilidad/fallback.
- [ ] Configurar embeddings reales y ejecutar benchmark documental.
- [ ] Ejecutar backup integral y restore en una instalación vacía.
- [ ] Probar update y rollback con una release versionada.
- [ ] Ejecutar pruebas de carga, seguridad de contenedores y aislamiento entre dos clientes.
- [ ] Rotar/revocar las credenciales Supabase que estaban presentes en el ZIP original.
- [ ] Realizar UAT y aprobación explícita del responsable de Ofideep.
