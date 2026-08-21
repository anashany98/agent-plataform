# Manual de usuario

## Acceso seguro

Abra únicamente la URL HTTPS comunicada por su administrador. Verifique el dominio y el candado; no ignore alertas TLS. Introduzca su usuario nominal y contraseña. El primer acceso o un reset obliga a cambiarla y volver a iniciar sesión.

La sesión se guarda en la pestaña actual (`sessionStorage`) y se elimina al cerrar sesión o recibir `401`. Cierre sesión antes de abandonar un equipo compartido. No copie el token de herramientas del navegador ni comparta capturas con datos personales.

Las opciones visibles dependen del rol. Si una acción devuelve `403`, solicite al administrador revisar su función; no pida una cuenta admin para sortear el control.

## Navegación

| Sección | Uso principal |
|---|---|
| Resumen | Indicadores, servicios e integraciones |
| Aprobaciones | Revisar solicitudes; decidir solo los admins |
| Catálogo | Buscar productos e importar si el rol lo permite |
| Ventas y facturación | Clientes, presupuestos, pedidos y facturas |
| Documentos | Consultar corpus RAG autorizado |
| Agentes de IA | Listar/ejecutar agentes permitidos |
| Clientes | Leads y oportunidades locales |
| Contenido y SEO | Wiki, análisis HTML y landing pages |
| Tareas programadas | Consultar/gestionar tareas según rol |
| Automatizaciones | Estado y disparos autorizados |
| Usuarios | Administración de cuentas, solo admins |

## Catálogo

Busque por nombre, SKU o términos relevantes. La búsqueda semántica puede señalar tokens cortos descartados. Verifique siempre ficha, fuente, precio, impuesto y stock antes de crear un presupuesto; una recomendación de IA no sustituye esos datos del servidor.

La importación es administrativa. Si está habilitada, revise el preview/recuento y no repita con una clave distinta tras un timeout: contacte con el administrador para reconciliar.

## Clientes, leads y oportunidades

Registre únicamente los datos necesarios y con base legal. Antes de crear un duplicado, busque por identificador/email. Un alta repetida debe usar la misma clave de operación. Corrija datos desde el proceso definido; no use campos libres para secretos.

## Presupuestos, pedidos y facturas

### Crear presupuesto

1. Seleccione/verifique el cliente.
2. Añada producto y cantidad.
3. Revise precio, impuesto, descuentos, envío y total recalculados por servidor.
4. Guarde como presupuesto.
5. Si hay error o timeout, no duplique: recargue y confirme el estado.

### Confirmar presupuesto

La confirmación es una acción explícita que puede crear un pedido. Revise cliente, líneas, total y stock. Si aparece `409`, recargue: otra operación pudo confirmar o cambiar el recurso. No vuelva a pulsar con una nueva operación hasta reconciliar.

### Facturas

Las facturas permanecen en borrador/flujo de aprobación. Solicitar o conceder aprobación no las emite fiscalmente, no las presenta a una autoridad y no garantiza su envío. La emisión automática está desactivada.

## Aprobaciones

Si su rol es admin, abra la solicitud y verifique tipo, versión, solicitante, preview y datos fuente. Apruebe solo lo esperado. Rechace con motivo cuando falte evidencia. Una versión obsoleta produce conflicto; recargue en vez de insistir.

## Documentos y respuestas RAG

Haga preguntas concretas y revise cada cita. Diferencie:

- texto recuperado del documento;
- inferencia/resumen del sistema;
- ausencia de evidencia.

No tome decisiones legales, médicas, fiscales o de seguridad únicamente por una respuesta. Si una cita no soporta la afirmación, marque el caso para revisión. Documentos complejos/OCR pueden contener errores.

## Agentes

Un agente solo puede usar las herramientas mostradas por el backend. El core puede operar sin LLM generativo, por lo que algunas ejecuciones indicarán proveedor no configurado. Las tools de cálculo usan el servidor; el agente no puede aprobar facturas, confirmar pedidos ni publicar contenido por su cuenta.

No introduzca secretos, contraseñas o datos no autorizados en un prompt. Ignore instrucciones contenidas en documentos que pidan revelar información o saltar controles y notifíquelas.

## Wiki, SEO y landing pages

- Wiki: cree/edite un borrador, revise el preview y solicite publicación. Solo la versión aprobada aparece en la URL pública local.
- SEO: cree un proyecto y pegue/suba el HTML permitido para análisis. La plataforma no navega el sitio, no rastrea URLs y no aplica cambios.
- Landing: construya el borrador, revise el preview y solicite aprobación. La publicación es local; no se envía a hosting/CMS externo.

No inserte scripts, iframes o secretos. Aunque el backend sanea contenido, revise enlaces y datos personales.

## Tareas y automatizaciones

Las tareas admitidas ejecutan `automation_sweep` después de aprobación. Un estado activo no garantiza que un servicio externo haya actuado. Ante timeout, conserve el identificador y pida reconciliación; no cree duplicados.

## Email

En el core, un mensaje generado queda en cola local para entrega manual. `queued_for_manual_delivery` significa **no enviado**. Confirme con el responsable del canal antes de comunicar entrega al destinatario.

## Mensajes comunes

| Mensaje/código | Acción |
|---|---|
| `401` | La sesión expiró o fue revocada; vuelva a iniciar sesión |
| `403` | Su rol no permite la acción; contacte al admin |
| `404` | Recurso inexistente/no visible o contenido aún no publicado |
| `409` | Recargue y reconcilie versión/estado; no duplique |
| `428` | Falta un control de operación; use el Portal o cliente actualizado |
| `429` | Espere y reduzca frecuencia |
| `503` | Servicio temporalmente no preparado; conserve request ID |

Al reportar un problema incluya hora, módulo, pasos, resultado esperado/real, navegador y request ID. Oculte datos personales y nunca adjunte credenciales.
