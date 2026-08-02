# Bloqueos de producción

| ID | Área | Bloqueo | Impacto | Qué falta | Trabajo que continúa | Estado |
|---|---|---|---|---|---|---|
| B-001 | Recursos | Host al 87,7 % de RAM en la captura de baseline y build previo superó 95 % | No es seguro levantar/build full stack | Liberar memoria Docker/WSL sin afectar otros proyectos o usar host limpio | Código, tests aislados, Compose config y documentación | BLOCKED |
| B-002 | Git/procedencia | Entrega original sin `.git` ni metadata vendor | Historial previo y limpieza vendor no demostrables | Remote/tags originales o aprobación del nuevo baseline | Git local y commits nuevos | BLOCKED |
| B-003 | PrestaShop | Sin sandbox/credenciales autorizadas | Precio, variante, impuesto, stock y pedido e2e no verificables | Sandbox con datos ficticios y clave mínima | Provider local, contratos y tests | BLOCKED |
| B-004 | GHL | Sin subcuenta sandbox/credenciales | Lead/oportunidad e2e no verificables | Subcuenta de prueba y scopes | Local CRM, outbox y contratos | BLOCKED |
| B-005 | Chatwoot | Sin inbox/widget configurado y runtime roto | Conversación visible/handoff e2e no verificables | Runtime estable e inbox ficticio | Chat interno y contract tests | BLOCKED |
| B-006 | IA externa | Sin proveedor/modelo autorizado y sin egress | Tool calling, coste y fallback remoto no verificables | Endpoint local autorizado o claves sandbox | Provider local real, schemas y evals | BLOCKED |
| B-007 | DR | No existe restore completo reproducido | RPO/RTO y recuperabilidad desconocidos | Host/instalación vacía con margen seguro | Mejorar scripts/manifiestos y tests estáticos | BLOCKED |
| B-008 | Legal | Código propio sin licencia raíz y rutas EE presentes en vendor | Redistribución comercial incierta | Revisión de titularidad, licencia y componentes EE | SBOM, notices y matriz técnica | BLOCKED |

Los bloqueos externos no autorizan mocks de producción ni respuestas sintéticas. Cada adapter debe ofrecer error explícito y permitir continuar con su proveedor local.
