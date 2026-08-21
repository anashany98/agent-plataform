> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Documento histórico; sus estados, rutas o contratos pueden no corresponder al árbol actual. Consulte `docs/PRODUCTION_READINESS.md` y la documentación canónica homónima de 2026-08-15.

# Checklist de validación viva antes de Ofideep

No declarar el piloto listo sin completar todos los puntos críticos.

## 1. Entorno limpio

- [ ] Docker Engine y Compose actualizados.
- [ ] Máquina sin imágenes/volúmenes anteriores del proyecto.
- [ ] Recursos mínimos medidos.
- [ ] DNS o hosts configurados.
- [ ] TLS válido en staging.
- [ ] `PILOT_MODE=true`.
- [ ] `ALLOW_MOCK_LLM=false`.
- [ ] `ALLOW_INTEGRATION_STUBS=false`.

## 2. Build y servicios

- [ ] `docker compose ... config` correcto.
- [ ] `docker compose ... build --no-cache --pull` correcto.
- [ ] Los 14 servicios están `running`.
- [ ] Los 14 health checks son reales.
- [ ] Sin reinicios repetidos.
- [ ] Sin errores críticos en 500 líneas de log.
- [ ] Portal carga sin Internet/CDN.

## 3. Portal

- [ ] Login real.
- [ ] Cambio de contraseña temporal.
- [ ] Logout revoca token.
- [ ] Roles probados.
- [ ] Modo claro/oscuro.
- [ ] Escritorio, portátil, tablet y móvil.
- [ ] Todo el texto visible en español.
- [ ] No presenta datos ficticios como reales.

## 4. Chatwoot

- [ ] Crear cuenta, usuario, inbox y widget.
- [ ] Configurar webhook con `configure-chatwoot-webhook.py`.
- [ ] Enviar mensaje desde widget real.
- [ ] Firma y delivery ID recibidos.
- [ ] Respuesta visible en widget.
- [ ] Transferencia a humano.
- [ ] Nota privada y etiqueta.
- [ ] Duplicado ignorado.
- [ ] Reinicio y persistencia.

## 5. PrestaShop Ofideep

- [ ] Clave Webservice solo lectura.
- [ ] Verificar versión y multitienda.
- [ ] Ejecutar sync `dry_run=true` de 100–300 productos.
- [ ] Revisar manualmente 30 productos.
- [ ] Verificar nombre, referencia, descripción y categoría.
- [ ] Verificar características.
- [ ] Verificar combinaciones/variantes.
- [ ] Verificar precio base y reglas específicas.
- [ ] Verificar stock total y por combinación.
- [ ] Resolver conflictos de stock reservado.
- [ ] Ejecutar sync confirmada.
- [ ] Conciliar origen y destino.

## 6. Agente comercial

- [ ] 30–50 preguntas reales de Ofideep.
- [ ] Recomendaciones solo con productos verificables.
- [ ] No inventa SKU, precio, característica ni stock.
- [ ] Pregunta por cantidad/datos cuando procede.
- [ ] Se abstiene cuando no hay evidencia.
- [ ] Transfiere al comercial.
- [ ] No crea pedido automático en el MVP.
- [ ] Facturas definitivas deshabilitadas.

## 7. GHL

- [ ] Subcuenta de prueba.
- [ ] Pipeline y etapa configurados.
- [ ] Contacto creado/actualizado.
- [ ] Oportunidad creada.
- [ ] Nota añadida.
- [ ] Mismo presupuesto no duplica oportunidad.
- [ ] Error de GHL visible y reintentable.

## 8. Activepieces

- [ ] App y worker operativos.
- [ ] Flujo real creado.
- [ ] Trigger real.
- [ ] Llamada al Bridge.
- [ ] Historial de ejecución.
- [ ] Error y reintento.
- [ ] Persistencia después de reinicio.

## 9. IA y RAG

- [ ] Modelo real configurado.
- [ ] Sin proveedor: falla cerrado.
- [ ] Fallback probado.
- [ ] Límites diarios probados.
- [ ] Embeddings reales.
- [ ] pgvector real.
- [ ] PDF, DOCX, XLSX y HTML reales.
- [ ] Citas correctas.
- [ ] Abstención correcta.
- [ ] ACL de documentos.
- [ ] Benchmark guardado.

## 10. Comercio y seguridad

- [ ] Conversación no confirma presupuesto ajeno.
- [ ] Confirmación repetida no duplica.
- [ ] Stock insuficiente revierte todo.
- [ ] Dos usuarios no compran la última unidad.
- [ ] Descuento de tarifa correcto.
- [ ] Exención correcta.
- [ ] Aprobación de un solo uso.
- [ ] Viewer no aprueba.
- [ ] Webhook sin firma rechazado.
- [ ] Replay rechazado.
- [ ] Token de otra instalación rechazado.

## 11. Recuperación

- [ ] Backup cifrado integral.
- [ ] Checksums válidos.
- [ ] Restore en instalación vacía.
- [ ] Conversaciones recuperadas.
- [ ] Catálogo y oportunidades recuperados.
- [ ] Documentos y embeddings recuperados.
- [ ] Flujos recuperados.
- [ ] RPO y RTO medidos, no estimados.
- [ ] Update probado.
- [ ] Rollback probado.

## 12. Decisión

- [ ] No hay defectos críticos.
- [ ] No hay defectos altos bloqueantes.
- [ ] Limitaciones aceptadas.
- [ ] Responsable de Ofideep aprueba UAT.
- [ ] Soporte y rollback preparados.

**Estado permitido al completar todo:** `GO — CONTROLLED OFIDEEP PILOT`.
