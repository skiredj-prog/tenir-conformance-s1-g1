# S1 real-subject result

The earlier PolicyEngine-only probe was correct as an architectural finding:
`tenir_governance.PolicyEngine` does not implement RFC-4 permit/attempt/receipt
reconciliation state and is therefore not itself the S1 subject.

S1 is now executed against the RFC-4 membrane implementation, with its scoring
bridge backed by the real reference `tenir_governance.PolicyEngine`.

Separation:
- membrane: permit, attempt, effect, receipt, unresolved state, retry inhibition;
- kernel bridge: maps payload `(P,V,K)` to the real PolicyEngine API;
- PolicyEngine: supplies the real admissibility score/decision only.

The reference PolicyEngine exposes `capacity_s(P,V,K)` and
`evaluate_membrane`, not a single `evaluate(P,V,K)` method. The bridge uses
those real APIs and does not add RFC-4 semantics to the kernel.

S1a, S1b and S1c produce the same client projection: **UNKNOWN / HOLD**.
For S1b, the target effect occurs once while the receipt is lost; retry for the
same LEI does not call the kernel and does not execute a second effect.

This is empirical evidence for the RFC-4 membrane implementation backed by the
reference TENIR PolicyEngine. It is not evidence that PolicyEngine itself
implements RFC-4.
