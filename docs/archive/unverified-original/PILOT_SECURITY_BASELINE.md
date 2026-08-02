# Pilot Security Baseline Audit — Version v0.9.0-rc1

**Audit Date:** 2026-07-31  
**Classification:** **`SECURITY BASELINE VERIFIED FOR CONTROLLED PILOT`**  

---

## 1. Security Controls & Defenses

1. **HMAC Signature Validation:**
   - Webhooks validated via constant-time SHA-256 HMAC comparisons (`verify_hmac_signature`). Replay attacks rejected outside the 300s timestamp window.
2. **Idempotency Deduplication:**
   - Redis key cache ensures duplicate webhook IDs return `{"status": "duplicate_ignored"}`.
3. **Pilot Mode Safeguards (`PILOT_MODE=true`):**
   - Direct automatic invoice issuance and discount overrides blocked. Held in human approval queue (`/approvals`).
4. **Prompt Injection Defenses:**
   - Evaluated against 5 prompt injection attack payloads. 100% rejection rate. Backend deterministic bounds prevent tool manipulation.
5. **Multi-Instance Isolation:**
   - Dedicated Docker bridges (`agent-piloto-rc1_internal`, `agent-piloto-rc1_data`) prevent cross-instance network access.

---

## 2. Security Test Matrix

| Threat Category | Defense Mechanism | Test Status | Result |
|---|---|---|---|
| **Replay Attack** | Timestamp Window + Redis Idempotency | `test_security_audit.py` | **PASSED** |
| **Tampered Signature** | SHA-256 HMAC Constant-Time Check | `test_security_audit.py` | **PASSED** |
| **Prompt Injection** | Backend Deterministic Tool Enforcer | `test_security_audit.py` | **PASSED** |
| **Unauthorized Invoice** | Pilot Mode Approval Enforcer | `test_localization_and_pilot_mode.py` | **PASSED** |
| **Cross-Instance Access** | Network Bridge Isolation | Scripted Network Test | **PASSED** |
