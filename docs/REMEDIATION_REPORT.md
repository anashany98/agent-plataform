# Informe de remediación técnica — `agent-platform`

**Fecha:** 31/07/2026  
**Origen:** revisión del archivo `agent-platform.zip`  
**Directorio corregido:** `agent-platform-fixed`  
**Decisión actual:** **GO para staging controlado; NO-GO para cliente real hasta completar validación viva.**

## 1. Resumen

Se ha sustituido la prueba de concepto insegura por una base de código que corrige los defectos críticos demostrados en la auditoría inicial. La solución conserva la arquitectura Opción A: Bridge API es el núcleo transaccional y los productos externos se integran mediante APIs, sin compartir bases de datos.

La remediación no se limita a documentación. Se modificaron backend, modelos, migraciones, portal, Docker, proxy, adaptadores, scripts operativos y pruebas automatizadas.

## 2. Resultado de las comprobaciones ejecutadas

| Comprobación | Resultado |
|---|---|
| Pruebas automatizadas | **31/31 superadas** |
| Cobertura backend | **67 %** |
| Compilación Python | Superada |
| Alembic upgrade → downgrade → upgrade | Superada |
| Sintaxis de scripts Bash | Superada |
| TypeScript del portal | Superado |
| Docker Compose estático | YAML correcto; 14 servicios |
| Escaneo básico de secretos | Sin hallazgos en código propio |
| Build Docker real | No ejecutado: Docker no disponible |
| Scripts PowerShell | No ejecutados: PowerShell no disponible |
| E2E con sistemas externos | Bloqueado: faltan credenciales y red del cliente |

Las evidencias están en `test-results/remediation/`.

## 3. Correcciones de defectos críticos

### CR-01 — API sin autenticación

**Corregido.**

- Usuarios persistentes.
- Contraseñas PBKDF2 con sal única.
- Política mínima de contraseña.
- Token firmado con expiración, instalación, versión de sesión y `jti`.
- Revocación mediante `token_version`.
- Cambio obligatorio de contraseña temporal.
- Roles y permisos por endpoint.
- Acceso administrativo restringido.

Pruebas: acceso sin token, contraseña errónea, cambio de contraseña, logout, viewer sin permisos y separación de instalación.

### CR-02 — Webhook Chatwoot sin firma

**Corregido.**

- Firma obligatoria.
- HMAC SHA-256 sobre `timestamp.body`.
- Formato oficial `sha256=<hex>`.
- Comparación constante con `hmac.compare_digest`.
- Ventana temporal configurable.
- Idempotencia por `X-Chatwoot-Delivery` o ID de mensaje.
- Recuperación de claims bloqueados.

### CR-03 — Confirmación del presupuesto de otra conversación

**Corregido.**

Se añadió `ConversationState` y relaciones explícitas:

```text
account_id + conversation_id
→ customer_id
→ active_quote_id
→ order_id
```

Una conversación sin presupuesto propio devuelve conflicto y nunca toma el último presupuesto global.

### CR-04 — Duplicación de pedidos y facturas

**Corregido.**

- `source_message_id` único en presupuestos.
- `quote_id` e `idempotency_key` únicos en pedidos.
- Una factura por pedido.
- Una reserva por pedido/producto.
- Aprobaciones de un solo uso.
- Repetir la confirmación devuelve el mismo pedido.

### CR-05 — Pedido creado sin stock

**Corregido.**

La confirmación es una operación transaccional:

1. Verifica el presupuesto.
2. Reserva stock con actualización atómica condicionada.
3. Crea pedido.
4. Crea reservas.
5. Crea borrador de factura.
6. Crea aprobación.
7. Confirma todo o revierte todo.

La actualización de stock utiliza una condición SQL sobre stock disponible para evitar sobreventa concurrente.

### CR-06 — Modelos de IA simulados presentados como reales

**Corregido.**

- Ollama real.
- API compatible con OpenAI.
- Anthropic real.
- Adaptadores para DeepSeek, Qwen, Kimi, GLM y MiniMax mediante endpoints configurables.
- El sistema falla con HTTP 503 sin credenciales/proveedor.
- El modo mock solo existe cuando `ALLOW_MOCK_LLM=true` y queda marcado como `simulated`.
- Los tokens proceden de la respuesta del proveedor.
- El coste se mantiene en cero hasta configurar un catálogo de precios, evitando métricas inventadas.

### CR-07 — RAG simulado y citas falsas

**Corregido.**

- Persistencia SQL de documentos y chunks.
- pgvector en PostgreSQL.
- Embeddings Ollama u OpenAI-compatible.
- TF-IDF local únicamente en pruebas explícitas.
- PDF, DOCX, XLSX, CSV, HTML, TXT e imágenes.
- OCR opcional con Tesseract.
- Validación de rutas permitidas.
- Control de tamaño y ZIP-bomb para formatos Office.
- Hash SHA-256 y deduplicación.
- ACL por roles.
- Umbral de evidencia y abstención.
- Citas derivadas de chunks existentes.
- Un archivo inexistente se rechaza.

### CR-08 — Portal demo diferente al código React

**Corregido en código y empaquetado.**

- Portal React/TypeScript real.
- Login contra Bridge API.
- Cambio obligatorio de contraseña.
- Datos obtenidos de endpoints reales.
- Aprobaciones reales.
- Estado de integraciones y consumo reales.
- Español, diseño clean, modo claro/oscuro y responsive.
- Dockerfile multi-stage.
- Nginx sin CDN ni Babel en navegador.
- Dependencias opcionales Linux de Rollup/esbuild declaradas para evitar el problema de instalaciones creadas en Windows.

El `typecheck` se ejecutó correctamente. El build local de Vite no pudo completarse porque el `node_modules` original contiene binarios de Windows y este entorno no puede descargar el binario Linux. El Dockerfile hace una instalación limpia en Linux y debe validarse mediante Docker.

## 4. Correcciones de severidad alta

### Chatwoot

- Ya no devuelve éxito falso al fallar la API.
- Respuesta, handoff, nota y etiquetas usan endpoints reales.
- Sin token, falla salvo stub explícito de test.
- Script para crear el webhook y recuperar su secreto real.

### Activepieces

- Adaptador de webhook real.
- App y worker separados.
- Worker apunta a `activepieces-app`, no a `localhost`.
- Health check comprueba proceso y conexión HTTP con la app.
- Las respuestas se registran con su ID real de ejecución.

### Precios y fiscalidad

- `Decimal`/`Numeric`, no `Float`, para dinero.
- Tarifa de cliente aplicada.
- Exención fiscal aplicada.
- Impuesto, moneda, serie y transporte configurables por instalación.
- Factura permanece en borrador en modo piloto.
- Sin facturación definitiva automática.

### Concurrencia de stock

- Actualización atómica.
- Constraint `reserved_stock <= stock_quantity`.
- Prueba de dos operaciones contra disponibilidad limitada.

### Aprobaciones

- Revisor tomado del token autenticado.
- Roles requeridos.
- Estados válidos.
- Doble aprobación rechazada.
- Instalación aislada.

### Importación

- CSV, XLSX y JSON.
- Tamaño y límite de filas.
- Validación por entidad.
- Duplicados en fichero y base.
- Dry-run.
- Transacción y rollback.
- Errores por fila.

## 5. MVP específico de Ofideep

### PrestaShop

Se implementó un adaptador de solo lectura para:

- Búsqueda de productos.
- Listado paginado.
- Producto completo.
- Nombre y descripción localizados.
- Características y valores.
- Combinaciones/variantes.
- Opciones de combinación.
- Stock total y por combinación.
- Reglas de precio específicas disponibles.
- Categoría.
- Sincronización dry-run o confirmada.

El Bridge no modifica PrestaShop. La tienda continúa siendo la fuente oficial. La caché local existe para búsqueda, auditoría y operaciones del piloto.

### Recomendaciones sin invención

El buscador determinista puntúa coincidencias en:

- Nombre.
- SKU.
- Categoría.
- Descripción.
- Características JSON.

Las consultas que encuentran catálogo verificable devuelven únicamente productos existentes, precio cacheado y stock disponible. Si no hay catálogo ni evidencia documental suficiente, el sistema se abstiene y transfiere la conversación a una persona. No usa un LLM libre para inventar productos.

### GHL

Se implementó:

- Upsert de contacto.
- Creación de oportunidad.
- Nota comercial.
- Referencia externa del presupuesto.
- Idempotencia por presupuesto.
- Fallo explícito y registro de error.

## 6. Infraestructura

- 14 servicios definidos.
- Solo el proxy expone puerto público.
- PostgreSQL y Redis no se publican.
- Redes `public`, `internal` y `data`.
- Volúmenes independientes.
- Health checks mejorados.
- Logs con rotación.
- `no-new-privileges` y capabilities reducidas donde es viable.
- Proxy por hostname para evitar subrutas incompatibles con Chatwoot/Activepieces.
- CSP, `nosniff`, `X-Frame-Options` y política de permisos en portal.
- Variables y secretos fuera de Git.

## 7. Operaciones

### Aprovisionamiento

Los scripts Linux y PowerShell:

- Validan identificador de cliente.
- Generan secretos criptográficos.
- Crean `.env.<cliente>`.
- Crean un proyecto Compose aislado.
- Levantan perfil completo.
- Esperan salud de 14 servicios.
- Generan un recibo de credenciales separado.

### Backup y restore

- Dumps custom-format de las tres bases.
- Documentos/adjuntos y uploads.
- Checksums.
- Cifrado AES-256-CBC con PBKDF2.
- Restore en el cliente indicado.
- Reinicio y comprobación de salud.

### Update y rollback

- Estado Git limpio obligatorio.
- Referencia exacta obligatoria.
- Backup cifrado previo.
- Build, migraciones, salud y rollback automático ante fallo.

## 8. Seguridad pendiente fuera del código

1. Rotar o revocar la URL/anon key de Supabase que estaba en el ZIP original.
2. Ejecutar escaneo de dependencias e imágenes en CI.
3. Configurar TLS y secretos con un gestor apropiado.
4. Probar el aislamiento con dos instalaciones activas.
5. Realizar revisión externa antes de producción.

## 9. Validaciones que no pudieron realizarse aquí

El entorno de revisión no incluye Docker ni PowerShell y no dispone de credenciales externas. Por tanto, siguen pendientes:

- Build y arranque real de los 14 contenedores.
- Migraciones reales PostgreSQL de todos los vendor.
- Widget Chatwoot completo.
- Flujo real Activepieces.
- Consulta real de PrestaShop.
- Lead real en GHL.
- LLM/embeddings reales.
- OCR en contenedor.
- Backup/restore integral real.
- Update/rollback real.
- Navegación visual y pruebas responsive.
- Pruebas de carga y escaneo de contenedores.

## 10. Decisión

### Código

**PASSED WITH CONDITIONS.** Los defectos demostrados en el código propio han sido corregidos y cuentan con pruebas de regresión.

### Staging

**GO.** Puede pasar a un entorno de staging limpio para validación viva.

### Cliente real

**NO-GO todavía.** Solo debe cambiar a `GO — CONTROLLED PILOT` después de completar `docs/LIVE_VALIDATION_CHECKLIST.md` y aportar evidencias.
