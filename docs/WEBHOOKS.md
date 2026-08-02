# Webhook Architecture & Security

## Signature Verification & Security
All webhook requests passing through `Bridge API` must be authenticated:
1. **Chatwoot Webhook:** Validates secret tokens configured in Chatwoot integration settings.
2. **HMAC Header Validation:** Payload signature verified using SHA-256 HMAC header (`X-Bridge-Signature`).
3. **Idempotency Key Verification:** Every event contains an `idempotency_key` (e.g. Chatwoot `message_id`). Webhooks are cached in Redis for 24h to prevent duplicate execution.

## Flow Routing
```
[Chatwoot Webhook Event]
       │
       ▼
[Bridge API: /webhooks/chatwoot]
       │ ── 1. Validate Signature & HMAC
       │ ── 2. Check Idempotency Key in Redis
       │ ── 3. Parse Message & Extract Intent / Attachments
       │ ── 4. Invoke FlowWink Agent Engine
       │ ── 5. Execute Deterministic Tools (Product/Stock/Cart)
       │ ── 6. Log Audit, Tokens, Cost
       ▼
[Chatwoot API: Send Response Message]
```
