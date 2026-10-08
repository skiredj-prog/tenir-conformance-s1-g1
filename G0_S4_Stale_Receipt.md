# G0 — S4: Stale Receipt & Expired Evidence

**Status:** Operational definition (lab).  
**Locked name:** Stale Receipt.  
**Target:** RFC-4 membrane (`tenir_conformance.membrane.Membrane`).  
**Claim scope:** Empirical validation of tested sequential interleavings only.

## Vocabulary mapping (spec → membrane)

| Spec term | Membrane primitive |
|-----------|-------------------|
| IN_FLIGHT / window OPEN | `AttemptState.AWAITING_QUALIFICATION` |
| UNKNOWN + window CLOSED | `timeout_fired` + `AttemptState.UNKNOWN` after `check_qualification_timeouts` |
| COMMITTED | `AttemptState.RESOLVED` + `qualified=True` |
| process_receipt | `deliver_qualifying_receipt(...)` |
| ExecutionWindow CLOSED | `timeout_fired` or state `UNKNOWN` post-τ_K |

## Property

Closed Window ∨ Terminal Lock ∨ Expired Token ⇒ ¬COMMIT ∧ ¬new PERMIT for receipt ∧ Δ EffectSink = 0

## Sub-cases

| ID | Setup | Expected |
|----|--------|----------|
| S4a | A1 AWAITING → τ_K → UNKNOWN; late bound receipt | HOLD; RECEIPT_REJECTED / LATE_RECEIPT; not RESOLVED |
| S4b | A1 AWAITING (window open); token expires_at_ms <= now | StaleReceiptError; not RESOLVED; Δ effect = 0 |

## Binding (A6)

receipt.attempt_id == attempt.attempt_id; receipt.lei/nonce match when provided.
