# 03 - Propiedad y flujo de datos

## Decisión de fuente de verdad recomendada

| Dominio | Estado actual | Fuente oficial recomendada | Estado |
|---|---|---|---|
| Catálogo, categorías, variantes, precios, impuestos y stock vendible | Copia en Bridge; 100 registros `source=demo`; atributos PrestaShop almacenados pero no aplicados | PrestaShop | BROKEN |
| Cliente/contacto comercial | Customer local y contacto GHL potencialmente duplicados | GHL para CRM; Bridge solo referencia y datos mínimos | CONFIGURED ONLY |
| Conversación, participante, asignación y mensajes | Chatwoot previsto; DB vacía | Chatwoot | BROKEN |
| Presupuesto | Bridge | Bridge, con snapshot trazable de oferta PrestaShop | PARTIALLY VERIFIED |
| Pedido y reserva | Bridge confirma localmente; no escribe PrestaShop | PrestaShop para pedido/stock oficial; Bridge como orquestador/idempotencia | BROKEN |
| Factura | Solo borrador local | ERP/facturación legal futuro; Bridge no debe emitir hasta integrar | NOT IMPLEMENTED |
| Agentes y workflows | Registro en memoria + FlowWink/Supabase no configurado + AP vacío | Una sola configuración versionada; para MVP, Bridge | BROKEN |
| Documentos/RAG | Bridge DB + `bridge_uploads` | Bridge por instalación u object storage por cliente | PARTIALLY VERIFIED |
| Auditoría y costes | Bridge DB | Bridge, con almacenamiento inmutable/retención | PARTIALLY VERIFIED |

## Evidencia crítica

- La base real contiene exclusivamente `products_by_source=demo:100`, además de 25 clientes demo.
- `search_products` no filtra `source`; el chat llama a esa búsqueda y etiqueta la respuesta como catálogo verificado.
- La sincronización PrestaShop copia datos a Bridge, pero la cotización usa `base_price`, IVA por defecto y reglas locales; ignora combinaciones y precios específicos.
- La reserva solo incrementa `reserved_stock` local. No reduce ni bloquea stock en PrestaShop y no tiene expiración/liberación/cancelación.
- No existe reconciliación de bajas de catálogo ni indicador de frescura.
- `docs/DATA_OWNERSHIP.md` atribuye a FlowWink catálogo/transacciones, en contradicción con código y README. FlowWink no tiene backend configurado.

## Aislamiento

- La separación normal es física/lógica por proyecto Compose, DB, Redis, redes y volúmenes: corresponde a **multi-instance single-tenant** en diseño.
- Usuarios llevan `installation_id`; la mayoría de tablas comerciales no. La barrera real es la DB independiente, no una defensa en profundidad.
- Una reutilización accidental de volumen/credenciales podría mezclar datos sin que el modelo lo detecte.
- No hay proceso de exportación, retención, anonimización o eliminación segura por cliente.

## Flujo recomendado

1. Resolver intención sin crear transacción.
2. Consultar PrestaShop en tiempo real o caché con TTL/frescura explícita.
3. Cotizar un snapshot firmado: IDs externos, combinación, precio específico, impuesto, moneda, stock y timestamp.
4. Capturar consentimiento y contacto con una máquina de estados.
5. Upsert idempotente en GHL.
6. Confirmar pedido/reserva en PrestaShop con clave idempotente y control optimista.
7. Persistir referencias y auditoría en Bridge.
8. Transferir/asignar conversación en Chatwoot.

## Archivos revisados

Modelos SQLAlchemy, servicio determinista, seed, rutas de Chatwoot/PrestaShop/GHL, adaptadores, migración, Compose y documentación de ownership.

## Defectos, riesgos y pendiente

- **P0:** datos demo pueden convertirse en oferta y pedido.
- **P0:** precio y disponibilidad divergen de la fuente oficial.
- **P1:** no hay ciclo de vida de reserva ni reconciliación.
- **P1:** documentación contradictoria impide responsabilidad operativa.
- Pendiente: definir contrato de ownership aprobado por producto/legal y ejecutar pruebas con sandbox PrestaShop/GHL.

