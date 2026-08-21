# Control de acceso basado en roles (RBAC)

## Roles reconocidos

| Rol | Propósito |
|---|---|
| `provider_admin` | Administración del proveedor y vista agregada permitida |
| `client_admin` | Administración integral de una instalación cliente |
| `supervisor` | Operación y supervisión de negocio |
| `commercial` | Trabajo comercial: clientes, leads, presupuestos y consultas |
| `support` | Soporte operativo y diagnóstico no administrativo |
| `operator` | Ejecución de operaciones de negocio |
| `viewer` | Solo lectura donde la ruta admite `READ_ROLES` |

Agrupaciones efectivas del backend:

- `ADMIN_ROLES`: `provider_admin`, `client_admin`.
- `OPERATOR_ROLES`: admins + `supervisor`, `commercial`, `support`, `operator`.
- `READ_ROLES`: operator roles + `viewer`.

Estas agrupaciones son el control general observado en las dependencias FastAPI. Una organización puede aplicar una política más restrictiva, pero no debe ampliar roles desde el Portal.

## Matriz de capacidades

| Capacidad | Provider admin | Client admin | Supervisor | Commercial | Support | Operator | Viewer |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Login/cambio de contraseña | Sí | Sí | Sí | Sí | Sí | Sí | Sí |
| Gestionar usuarios | Sí | Sí | No | No | No | No | No |
| Health detallado/métricas | Sí | Sí | No | No | No | No | No |
| Ver dashboard general | Sí | Sí | Sí | Sí | Sí | Sí | Sí |
| Dashboard proveedor | Sí | No | No | No | No | No | No |
| Ver costes | Sí | Sí | No | No | No | No | No |
| Operar clientes/presupuestos/pedidos/facturas | Sí | Sí | Sí | Sí | Sí | Sí | No |
| Aprobar/rechazar solicitudes | Sí | Sí | No | No | No | No | No |
| Ingestar/borrar documentos RAG | Sí | Sí | No | No | No | No | No |
| Consultar RAG/documentos autorizados | Sí | Sí | Sí | Sí | Sí | Sí | Sí* |
| Ejecutar agentes/tools | Sí | Sí | Sí | Sí | Sí | Sí | No |
| Crear/editar/activar agentes | Sí | Sí | No | No | No | No | No |
| Crear/editar/publicar wiki | Sí | Sí | No | No | No | No | No |
| Previsualizar wiki/landing | Sí | Sí | Sí | Sí | Sí | Sí | Sí |
| Gestionar SEO | Sí | Sí | análisis/listado | análisis/listado | análisis/listado | análisis/listado | No |
| Gestionar landing/tareas | Sí | Sí | No | No | No | No | No |
| Importar datos | Sí | Sí | No | No | No | No | No |
| Lifecycle/export/erase/legal hold | Sí | Sí | No | No | No | No | No |
| Ver leads/oportunidades | Sí | Sí | Sí | Sí | Sí | Sí | No |
| Crear leads | Sí | Sí | Sí | Sí | Sí | Sí | No |
| PrestaShop consultar | Sí | Sí | Sí | Sí | Sí | Sí | Sí |
| PrestaShop sincronizar | Sí | Sí | No | No | No | No | No |

`*` La lectura RAG sigue limitada por la ACL de roles de cada documento; pertenecer a `READ_ROLES` no concede acceso universal.

## Aislamiento por instalación

RBAC y tenancy son controles distintos y ambos deben pasar. El JWT incluye `installation_id`; las entidades heredan propiedad de instalación, las consultas aplican filtros ORM y los writes cruzados se rechazan antes de flush. El esquema añade claves/uniques compuestos para reforzar relaciones dentro del tenant.

Un `provider_admin` no debe usar una instalación arbitraria proporcionada por el cliente HTTP. Su alcance deriva del token/contexto y de las rutas expresamente diseñadas para proveedor. El despliegue recomendado mantiene una base y un proyecto Compose por cliente, reduciendo el blast radius además del aislamiento lógico.

## Aprobaciones y segregación

Las acciones sensibles usan estados, control de versión y aprobación: activación de agentes, publicación wiki/landing, activación de tareas y factura. El cliente debe definir quién solicita y quién decide; aunque dos cuentas admin tengan capacidad técnica, no deben compartir credenciales ni autoaprobar sin política explícita.

Las facturas aprobadas son estados internos y no emisión fiscal. Los agentes no reciben herramientas para aprobar, emitir o publicar.

## Sesión del Portal

El Portal guarda el JWT en `sessionStorage` y lo elimina al recibir `401`. Esto limita persistencia entre sesiones del navegador, pero un XSS ejecutado en la misma pestaña podría leerlo. Son obligatorios CSP/headers, prohibición de scripts de terceros no revisados y cierre de sesión al abandonar un equipo compartido. MFA y SSO no están implementados.

## Pruebas mínimas antes del go-live

Para cada fila aplicable ejecute:

1. caso permitido por rol;
2. caso denegado con `403`;
3. token de instalación B contra recurso A;
4. recurso inexistente y no visible sin fuga diferencial;
5. token revocado/cambio de contraseña;
6. conflicto `If-Match` y retry idempotente;
7. intento de aprobar con rol operativo;
8. intento de invocar una tool no allowlisted.

Los tests backend existentes cubren controles relevantes; el recorrido de todos los roles sobre la imagen candidata final permanece `PENDING`.
