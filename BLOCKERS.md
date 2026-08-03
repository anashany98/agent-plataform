# Bloqueos de producción

| ID | Área | Bloqueo | Impacto | Qué falta | Trabajo que continúa | Estado |
|---|---|---|---|---|---|---|
| B-001 | Recursos | Host al 87,7 % de RAM en la captura de baseline y build previo superó 95 % | No es seguro levantar/build full stack | Medir margen tras parada del stack antiguo; si la VM Docker no libera memoria, valorar reinicio de Docker Desktop en ventana acordada | Código, tests aislados, Compose config y documentación | BLOCKED (mitigado 2026-08-03: parados `agent-platform`, `agent-piloto-rc1` y `agent-cliente-demo-es-staging` del workspace antiguo con volúmenes intactos; puerto 9000 liberado; host al 85 % pendiente de liberación de la VM) |
| B-002 | Git/procedencia | Entrega original sin `.git` ni metadata vendor | Historial previo y limpieza vendor no demostrables | Remote/tags originales o aprobación del nuevo baseline | Git local y commits nuevos | BLOCKED |
| B-003 | PrestaShop | Sin sandbox/credenciales autorizadas ni versión declarada | Contratos P0 están verdes, pero precio/stock/pedido E2E, paginación y flags de visibilidad no son verificables | Sandbox con datos ficticios, versión soportada y clave mínima | Contratos oficiales, fail-closed y corrección D-033/D-034 | BLOCKED |
| B-004 | GHL | Sin subcuenta sandbox/credenciales | Lead/oportunidad e2e no verificables | Subcuenta de prueba y scopes | Local CRM, outbox y contratos | BLOCKED |
| B-005 | Chatwoot | Sin inbox/widget configurado y runtime roto | Conversación visible/handoff e2e no verificables | Runtime estable e inbox ficticio | Chat interno y contract tests | BLOCKED |
| B-006 | IA externa | Sin proveedor/modelo autorizado y sin egress | Tool calling, coste y fallback remoto no verificables | Endpoint local autorizado o claves sandbox | Provider local real, schemas y evals | BLOCKED |
| B-007 | DR | No existe restore completo reproducido | RPO/RTO y recuperabilidad desconocidos | Host/instalación vacía con margen seguro | Mejorar scripts/manifiestos y tests estáticos | BLOCKED |
| B-008 | Legal | Código propio sin licencia raíz y rutas EE presentes en vendor | Redistribución comercial incierta | Revisión de titularidad, licencia y componentes EE | SBOM, notices y matriz técnica | BLOCKED |

Los bloqueos externos no autorizan mocks de producción ni respuestas sintéticas. Cada adapter debe ofrecer error explícito y permitir continuar con su proveedor local. El cierre P0 en `de236e9` no elimina ninguno de estos bloqueos de candidata/runtime.

El 2026-08-03 el propietario aprobó la Ruta A (candidata core, ver `DECISIONS.md` D-007) y la parada del stack antiguo (D-008), ya ejecutada. B-001 permanece abierto hasta medir margen real de memoria en un build.
