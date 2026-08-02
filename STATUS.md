# Estado del proyecto

**Fecha:** 31/07/2026  
**Estado:** `REMEDIATED CODEBASE — INTERNAL AUTOMATED TESTS PASSED; LIVE VALIDATION REQUIRED`

## Completado

- Autenticación real, cambio obligatorio de contraseña, revocación de sesiones y RBAC.
- Webhooks Chatwoot con firma HMAC oficial, timestamp, ventana antirreplay e idempotencia.
- Asociación exacta conversación → cliente → presupuesto → pedido.
- Idempotencia transaccional de presupuestos, pedidos, reservas, facturas y aprobaciones.
- Reserva de stock atómica y rollback completo.
- Tarifas de cliente, exenciones y tipos fiscales configurables.
- Adaptadores LLM reales y modo mock únicamente explícito en pruebas.
- RAG persistente con extracción real, ACL, embeddings configurables, pgvector y abstención.
- Portal React/TypeScript conectado a la API; sin datos de demostración incrustados.
- Integraciones de solo lectura con PrestaShop y comerciales con GHL.
- Adaptadores reales para Chatwoot y Activepieces que fallan de forma explícita.
- Docker Compose endurecido, 14 servicios, redes y volúmenes aislados.
- Aprovisionamiento seguro por cliente, backups cifrados, restore, update y rollback.
- Informes originales engañosos archivados y separados del estado actual.

## Validación interna ejecutada

- `31 passed`.
- Cobertura backend: `67 %`.
- `compileall`: correcto.
- Alembic upgrade/downgrade/upgrade: correcto.
- Sintaxis Bash: correcta.
- TypeScript: correcto.
- Compose: YAML correcto y 14 servicios detectados.
- Escaneo básico de secretos: sin hallazgos en el código propio.

## Bloqueos del entorno de revisión

- Docker no está instalado; no se pudo ejecutar `docker compose build/up`.
- PowerShell no está instalado; los scripts `.ps1` no pudieron ejecutarse aquí.
- La construcción local de Vite queda bloqueada por el binario opcional de Rollup procedente del `node_modules` de Windows. El Dockerfile fuerza instalación limpia de dependencias opcionales para Linux.
- No se proporcionaron credenciales reales de Chatwoot, PrestaShop, GHL, Activepieces ni proveedores de IA.

## Estado comercial

**NO-GO para cliente real todavía.**  
**GO para validación controlada en staging**, siguiendo `docs/LIVE_VALIDATION_CHECKLIST.md`.
