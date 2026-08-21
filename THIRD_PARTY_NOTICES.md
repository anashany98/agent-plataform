# Third-Party Notices & Open Source Licenses (SBOM)

**Product:** AI Agent Enterprise Platform (`agent-platform`)  
**License Audit Date:** 2026-08-15  

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

### C. Activepieces (opcional; sin checkout local)
- **Artefacto declarado:** `ghcr.io/activepieces/activepieces:0.86.3@sha256:208517c4f0d798a477a0c594bf432dd0f4918433f4b6f5b5f188a6e10e638c6c`
- **Evidencia local:** no existe `vendor/activepieces` ni entrada en `vendor-lock.json`.
- **Licencia:** no verificada para el contenido exacto de esa imagen. El upstream
  separa Community Edition MIT y funciones Enterprise comerciales, pero esa
  declaración no demuestra qué contiene el digest fijado.
- **Decisión:** excluido del perfil `production`; el perfil `full` no puede
  entregarse ni distribuirse hasta obtener SBOM, licencia y exclusión verificable
  de componentes Enterprise.

---

## 2. Platform Infrastructure & Libraries

| Component / Library | Version | License | Usage |
|---|---|---|---|
| **Python** | 3.12.13-slim-bookworm por digest | PSF + paquetes Debian | Runtime Environment |
| **FastAPI** | 0.141.1 | MIT | Web Framework |
| **SQLAlchemy** | 2.0.52 | MIT | ORM & DB Access |
| **PostgreSQL** | 15-alpine / 16 / 14 | PostgreSQL License | Primary Datastore |
| **pgvector** | 0.8.0 / pg16 | MIT | Vector Embeddings |
| **Redis** | 7.2.14-alpine3.21 por digest | BSD-3-Clause | Rate limiting, locks y outbox |
| **Nginx** | 1.30.4-alpine3.24 por digest | BSD-2-Clause + terceros | Reverse Proxy Gateway |
| **React** | 18.2.0 | MIT | Admin Portal SPA |
| **Tailwind CSS** | 3.4.1 | MIT | Styling Utility |

---

## 3. License Compliance Declaration
Los componentes del core deben conservar sus licencias y notices conforme al
SBOM final. Esta lista es informativa y no sustituye revisión legal. El código
propio de Bridge API y Portal permanece reservado según `LICENSE`.

---

## 4. Actualización 2026-08-15 (remediación)
- Las licencias de las dependencias Python se re-verificaron leyendo `importlib.metadata`
  del entorno de desarrollo; la matriz completa (uso + restricciones) está en
  `docs/LICENSE_MATRIX.md`.
- Los componentes *vendor* son opcionales y quedan fuera del core. FlowWink y
  Chatwoot conservan evidencia local; Activepieces queda sin licencia de artefacto
  verificada. Sus rutas *enterprise* y cualquier distribución comercial requieren
  **revisión legal (B-008)** antes de una release `full`.
- Este aviso no concede derechos de redistribución sin dicha revisión.
