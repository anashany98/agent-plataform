# Third-Party Notices & Open Source Licenses (SBOM)

**Product:** AI Agent Enterprise Platform (`agent-platform`)  
**License Audit Date:** 2026-07-31  

---

## 1. Primary Vendor Microservices

### A. FlowWink Vendor Engine (`vendor/flowwink`)
- **Version / Commit:** Commit `0cd4e9b8af0d432c9a942a692d8f1fa4a04ec67b`
- **License:** MIT License
- **Copyright:** (c) Magnus Froste / FlowWink Contributors
- **Notice:** Permission is hereby granted, free of charge, to any person obtaining a copy of this software...

### B. Chatwoot Community Edition (`vendor/chatwoot`)
- **Version / Commit:** Commit `b05f22da8df103a349c3e820afcb76acb129692a`
- **License:** MIT License (Community Edition)
- **Copyright:** (c) Chatwoot Inc.
- **Notice:** Distributed under MIT Community License. Enterprise plugins excluded.

### C. Activepieces Community Edition (`vendor/activepieces`)
- **Version / Commit:** Commit `44143d700ef7d5eb00b7397fddc2bc40f247ab88` (v0.86.3)
- **License:** MIT License (Community Edition)
- **Copyright:** (c) Activepieces Inc.
- **Notice:** Distributed under MIT License.

---

## 2. Platform Infrastructure & Libraries

| Component / Library | Version | License | Usage |
|---|---|---|---|
| **Python** | 3.11-slim | PSF License | Runtime Environment |
| **FastAPI** | 0.109.0 | MIT | Web Framework |
| **SQLAlchemy** | 2.0.25 | MIT | ORM & DB Access |
| **PostgreSQL** | 15-alpine / 16 / 14 | PostgreSQL License | Primary Datastore |
| **pgvector** | 0.8.0 / pg16 | MIT | Vector Embeddings |
| **Redis** | 7-alpine | BSD-3-Clause | Caching & Locks |
| **Nginx** | 1.25-alpine | BSD-2-Clause | Reverse Proxy Gateway |
| **React** | 18.2.0 | MIT | Admin Portal SPA |
| **Tailwind CSS** | 3.4.1 | MIT | Styling Utility |

---

## 3. License Compliance Declaration
All third-party open-source components used in `agent-platform` comply with their respective MIT, BSD, and PostgreSQL licenses. Proprietary business logic developed for Bridge API and Admin Portal remains strictly client-owned under Option A Architecture.

---

## 4. Actualización 2026-08-04 (remediación)
- Las licencias de las dependencias Python se re-verificaron leyendo `importlib.metadata`
  del entorno de desarrollo; la matriz completa (uso + restricciones) está en
  `docs/LICENSE_MATRIX.md`.
- Los componentes *vendor* (FlowWink MIT, Chatwoot CE, Activepieces CE) son opcionales
  y quedan fuera del core (Ruta A). Sus rutas *enterprise* y cualquier distribución
  comercial requieren **revisión legal (B-008)** antes de una release.
- Este aviso no concede derechos de redistribución sin dicha revisión.
