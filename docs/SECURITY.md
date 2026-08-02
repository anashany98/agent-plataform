# Security Architecture & Guidelines

## Key Security Policies
1. **Network Exposure:** Only `reverse-proxy` (port `9000`) is exposed publicly. All databases, Redis, and internal APIs are bound to internal Docker bridge networks.
2. **Secrets Management:** Secrets are stored in local `.env` files (gitignored). Never commit production credentials.
3. **Webhook Verification:** Chatwoot webhooks validate HMAC headers and Redis idempotency keys before processing.
4. **Human Approval Gateway:** Financial transactions and invoice issuance require explicit human approval via `/approvals`.
