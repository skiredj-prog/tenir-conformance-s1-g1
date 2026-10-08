# G0 — S3: Duplicate Request

**Status:** Operational definition (lab).  
**Depends on:** S1 unresolved LEI lock; T7/T8 terminal FAILED + retry_eligible.  
**Locked name:** Duplicate Request.

---

## Claim

While an LEI is locked by an unresolved attempt A1, a concurrent or subsequent submit A2 on the same LEI must be **rejected at the registration barrier**:

- no new attempt registry entry for A2,
- no new permit for A2,
- no additional effect on the LEI,
- A1 state unchanged.

Additionally, **attempt_id** is globally unique: reusing an existing attempt_id is rejected **before** LEI-lock evaluation (S3d).

---

## Sub-cases

| ID  | Name | Setup | Expected |
|-----|------|-------|----------|
| S3a | A1 in-flight / awaiting | A1 admitted, AWAITING or effect path open | A2 → UnresolvedSameLEI / HOLD; A2 not registered |
| S3b | A1 executed, receipt pending | A1 effect applied, state UNKNOWN (receipt lost) | same rejection; effect count unchanged |
| S3c | A1 UNKNOWN (timeout/lost) | A1 UNKNOWN | same rejection |
| S3d | Duplicate attempt_id | A2 uses A1's attempt_id | DuplicateAttemptID; A1 not overwritten |

---

## Normative assertion

```
Unresolved(L, A1) ∧ Submit(A2, L) ∧ A2.id ≠ A1.id  →  ¬Admit(A2) ∧ ¬Execute(A2)
Submit(A2) ∧ A2.id ∈ Registered  →  DuplicateAttemptID ∧ no mutation of A1
```

---

## Out of scope

- Successful reconciliation path (S6)
- Cross-process distributed locking (single-process membrane only)
