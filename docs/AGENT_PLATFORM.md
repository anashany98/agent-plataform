# Plataforma de agentes

## Alcance certificado

La plataforma permite definir agentes por instalación, limitar sus herramientas, ejecutar consultas y conservar auditoría de uso y coste. El control efectivo vive en backend: el Portal no amplía permisos ni puede añadir herramientas fuera del registro del servidor.

En el perfil `production` core, los niveles LLM parten en `provider=none` y RAG usa `local_tfidf`. Por tanto, las búsquedas deterministas, las herramientas y el chat documental extractivo pueden funcionar sin un proveedor externo, pero una ejecución que requiera generación LLM debe fallar cerrada hasta que se configure y certifique un proveedor. No presentar esa configuración base como un asistente generativo completo.

## Modelo operativo

1. Un administrador crea una definición en `POST /agents` con nombre, instrucciones, modelo/nivel y `allowed_tools`.
2. La definición permanece inactiva o en borrador hasta solicitar activación.
3. `POST /agents/{agent_id}/request-activation` crea el flujo de aprobación versionado.
4. Un administrador distinto o autorizado revisa la petición desde `/approvals` y aprueba o rechaza.
5. Un operador ejecuta `POST /agents/run`; el backend vuelve a resolver instalación, rol, estado, presupuesto y allowlist.
6. Cada invocación de herramienta queda sujeta a validación estricta de nombre y argumentos.

Las definiciones se persisten en PostgreSQL desde la migración `0013`. No dependen de archivos editables dentro de la imagen para su estado operativo.

## Herramientas registradas

| Herramienta | Clase | Efecto permitido |
|---|---|---|
| `search_products` | lectura | Buscar catálogo de la instalación |
| `get_product` | lectura | Obtener un producto concreto |
| `get_customer` | lectura | Obtener un cliente concreto |
| `check_stock` | lectura | Consultar disponibilidad |
| `calculate_price` | lectura/cálculo | Recalcular precio en servidor con reglas deterministas |
| `create_quote` | borrador | Crear exclusivamente un presupuesto borrador |
| `rag_search` | lectura | Recuperar fragmentos autorizados con citas |

La política es **deny-by-default**. La allowlist efectiva es la intersección entre `allowed_tools` y el registro compilado del backend; nombres desconocidos, allowlists vacías y herramientas financieras mutantes se rechazan. El agente no puede confirmar pedidos, aprobar facturas, emitir documentos fiscales, publicar contenido, activar tareas ni administrar usuarios.

## RAG y chat documental

- Ingesta administrativa por texto o archivo con límites de tamaño y raíces permitidas.
- ACL por roles en cada documento.
- Fragmentos y citas se filtran por `installation_id` y rol antes de responder.
- `local_tfidf` es un recuperador local y determinista; tiene límites de chunks, corpus y features.
- Existe detección defensiva de instrucciones maliciosas en el corpus, pero no reemplaza revisión humana ni una prueba red-team del corpus real.
- OCR local es básico y depende de Tesseract; no está certificado para manuscritos, tablas complejas o documentos degradados.

Una respuesta sin evidencia suficiente debe reconocerse como insuficiente; la recuperación correcta no garantiza por sí sola que un modelo generativo produzca una respuesta fiel.

## Proveedores y costes

El router contempla niveles `cheap`, `standard`, `advanced` y `critical`, límites de entrada/salida, timeout, presupuesto diario global y catálogo de precios. Cualquier modelo externo configurado requiere catálogo de precios y credenciales mediante secretos. Los costes son telemetría de consumo, no conciliación financiera.

Antes de habilitar un proveedor LLM:

1. aprobar DPA, región y retención;
2. registrar modelo y precio;
3. configurar timeout, límites y presupuesto;
4. probar redacción de logs y salida sin egress no autorizado;
5. ejecutar pruebas de prompt injection, fuga entre roles y agotamiento de cuota;
6. documentar rollback a `provider=none`.

## Roles y endpoints

| Acción | Roles mínimos |
|---|---|
| Listar agentes/herramientas | roles de lectura, incluido `viewer` |
| Ejecutar agente o invocar herramienta | roles operativos; no `viewer` |
| Crear, editar o solicitar activación | administradores |
| Aprobar/rechazar activación | administradores |
| Ver costes | administradores |

Consulte [RBAC.md](RBAC.md) para la matriz completa y [API.md](API.md) para contratos HTTP.

## Límites y estado de preparación

| Aspecto | Estado actual |
|---|---|
| Registro y allowlist deny-by-default | Verificado por tests herméticos |
| Creación solo de presupuestos borrador | Verificado por política/tests |
| Aprobación de activación | Implementado y cubierto |
| RAG local con citas y ACL | Parcial: tests verdes; falta E2E final con corpus real/malicioso |
| Ejecución generativa en core | Desactivada por defecto (`provider=none`) |
| Proveedores LLM externos | No certificados para la candidata core |
| Cancelación asíncrona, colas y rollback de modelo | No certificado como capacidad completa |
| E2E de todos los agentes en imágenes finales | PENDING |

La fuente autoritativa para promoción es [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).
