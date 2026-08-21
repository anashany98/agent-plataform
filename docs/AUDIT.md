> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Documento histórico; sus estados, rutas o contratos pueden no corresponder al árbol actual. Consulte `docs/PRODUCTION_READINESS.md` y la documentación canónica homónima de 2026-08-15.

# System & Codebase Audit Report

## 1. Vendor Repositories Overview

### FlowWink
- **Type:** React (Vite + TypeScript) SPA UI with Supabase / Edge functions / MCP capabilities.
- **License:** MIT
- **Architecture:** Client-side React dashboard with agent design system, process simulation, MCP tool call wrappers, and Supabase integration.
- **Key Modules:** Agents, MCP tool registration, process automation, quote-to-cash simulation, RAG knowledge docs, SEO automation hooks.

### Chatwoot Community Edition
- **Type:** Ruby on Rails monolith backend + Vue.js frontend UI + Sidekiq workers.
- **License:** MIT License for Community Edition (with Enterprise directory split under non-OSL license).
- **Architecture:** Multi-channel customer messaging platform. Provides Web Widget, Inbox management, Webhooks, APIs for conversation management, agent handoff, and contacts.
- **Integrations:** Webhooks triggered on `message_created`, `conversation_created`, `conversation_status_changed`.

### Activepieces Community Edition
- **Type:** Node.js / TypeScript Nx monorepo (Bun / npm) backend + Angular frontend.
- **License:** MIT License.
- **Architecture:** Workflow automation platform (Zapier/Make alternative). Uses Pieces for triggers and actions. Supports webhook triggers, REST API flow triggers, and custom TypeScript piece execution.

## 2. Shared Infrastructure Strategy
To prevent single points of failure and version conflicts:
- Each service runs isolated PostgreSQL and Redis instances (or separate databases within isolated containers).
- Data is NOT shared via direct DB connections across vendor boundaries.
- All inter-service communications are handled strictly via HTTP Webhooks, REST APIs, and the custom **Bridge API**.
