# Platform Architecture & Component Blueprint

> **ESTADO DE REMEDIACIÓN — NO USAR COMO DISEÑO DE PRODUCCIÓN APROBADO.** La arquitectura observada y sus fallos están en `docs/baseline/` y `docs/PROJECT_TECHNICAL_AUDIT.md`. La decisión vigente es mantener `MULTI-INSTANCE SINGLE-TENANT`, hacer el core funcional sin integraciones externas y formalizar providers/ownership en la Fase 3. Este documento se reescribirá tras cerrar P0/P1.

```
+-------------------------------------------------------------------+
|                        Client & End User                          |
+-------------------------------------------------------------------+
                                  │
                                  ▼
+-------------------------------------------------------------------+
|               Reverse Proxy (Nginx / Gateway) :9000               |
+-------------------+--------------------+--------------------------+
                    │                    │
                    ▼                    ▼
          +-------------------+  +-------------------+
          |  Chatwoot Web UI  |  |   Control Portal  |
          |       :3000       |  |       :3005       |
          +---------+---------+  +---------+---------+
                    │                    │
                    ▼                    ▼
+-------------------------------------------------------------------+
|                  Bridge API Middleware (FastAPI) :8005             |
|  - Webhook Handlers     - Human Approvals Gateway                 |
|  - Agent Router         - Audit & Cost Telemetry Tracker          |
|  - Idempotency Cache    - Deterministic Financial Tools           |
+-------------------+--------------------+--------------------------+
                    │                    │
                    ▼                    ▼
          +-------------------+  +-------------------+
          | FlowWink Engine   |  | Activepieces Engine|
          |       :8090       |  |       :8080       |
          +-------------------+  +-------------------+
```

## Network Isolation Strategy
- **Public Network:** Exposed port `9000` on Reverse Proxy only.
- **Internal Network:** Communication between Proxy, Chatwoot, FlowWink, Activepieces, Bridge API, and Portal.
- **Data Network:** Isolated traffic between applications and their dedicated databases / Redis instances.
