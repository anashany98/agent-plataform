# Security Architecture & Guidelines

> **SECURITY BASELINE FAILED.** Este archivo describe controles previstos, no certifica que funcionen. La fuente autoritativa es `docs/PRODUCTION_READINESS.md`; los P0/P1 se siguen en `TASKS.md` y la evaluación reproducida está en `docs/audit/12_SECURITY_ASSESSMENT.md`.

## Key Security Policies
1. **Network Exposure:** Only `reverse-proxy` (port `9000`) is exposed publicly. All databases, Redis, and internal APIs are bound to internal Docker bridge networks.
2. **Secrets Management:** Secrets are stored in local `.env` files (gitignored). Never commit production credentials.
3. **Webhook Verification:** Chatwoot webhooks validate HMAC headers and Redis idempotency keys before processing.
4. **Human Approval Gateway:** Financial transactions and invoice issuance require explicit human approval via `/approvals`.
