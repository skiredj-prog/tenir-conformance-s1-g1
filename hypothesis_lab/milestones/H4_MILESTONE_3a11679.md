# Milestone H4 — Signature validity ≠ standing

**Status:** FROZEN / VERIFIED (lab + targeted harness)
**HEAD:** `3a116798271e62acb11b4d97a2ce9c7809e7f4f5`
**CI run:** https://github.com/skiredj-prog/tenir-conformance-s1-g1/actions/runs/37987678636 (success)
**Date pinned:** 2026-10-09

## Three evidence levels (kept separate)

| Level | Result on this HEAD | Does **not** mean |
|-------|---------------------|-------------------|
| Hypothesis Lab (finite model) | 5 FAIL expected, 3 PASS, 1 VACUOUS, 0 anomaly | Product conformance |
| Conformance pytest (targeted) | S7b, S7c, S10a–c PASS | Universal standing property |
| Production | Explicitly not established | — |

## Model outcome (reproducible on HEAD)

```
H4-signature-not-standing  FAIL  present_valid_untrusted → admit_collapse_crypto → execute
H4-intended-only           PASS  (no collapse action in model)
```

## Implementation link (same HEAD)

| Test | Property slice |
|------|----------------|
| `test_s7b_unknown_signing_key_is_rejected` | unknown key → reject |
| `test_s7c_revoked_signing_key_is_rejected` | revoked key → reject |
| `test_s10a/b/c_*_out_of_scope_*` | insufficient scope → reject before kernel |

## Explicit limits

- Distant CI artifact ZIP not always byte-inspected (API auth).
- S7 = attestation trust-root path; S10 = signed TAU scope — not a general PDP.
- No production or generic conformance claim.

## Freeze rule

Do not weaken `admit_collapse_crypto` or remove expected FAIL for `H4-signature-not-standing`
without a deliberate milestone revision. Disappearance of the counterexample is an **ANOMALY**.
