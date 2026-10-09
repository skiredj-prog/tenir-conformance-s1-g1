# G0 S11 — Transition as governed object

**Implementation note (post-inspection correction):** canonical bytes use the `rfc8785` JCS implementation. Explicit non-legacy transitions require a configured target-Realm policy. The in-process execution commit records the transition hash, target Realm, payload digest, attempt ID and nonce; the effect sink rechecks the transition hash and payload digest at the effect boundary. This is an in-process conformance mechanism, not a signed, durable, or distributed commit protocol.

`Transition` is the explicit governed object. Required fields: `tau_id`, `source_realm`, `target_realm`, `action_class`, `principal`, `scope`, `payload_digest`, `evidence_refs`, `source_preconditions`, `target_postconditions`, and `declared_at`.

`canonical_hash(transition)` hashes RFC 8785 JCS canonical UTF-8 bytes using SHA-256. Every required field participates. The hash is stable across processes for the same canonical field values. The payload digest is computed over the canonical payload supplied to the kernel.

The membrane verifies TAU identity, exact TAU action/principal/LEI scope, optional source-realm scope, target-Realm policy (allowed action classes, allowed principals and required declared postconditions), and payload-digest binding before kernel evaluation. The current target policy verifies declared postconditions against policy requirements; it does not independently prove that arbitrary external-world postconditions occurred. `expected_transition_hash` is a caller-supplied frozen admission hash used to detect a changed object at a later boundary; mismatch returns HARD_VETO before kernel.

A compatibility adapter still constructs a marked legacy Transition for existing S1–S10 test callers that pass `payload` without `transition`. New callers should pass `transition=` explicitly. Omitting both is refused with `TRANSITION_REQUIRED`. This adapter is transitional and should be removed after migrating legacy tests.

## Oracle

- S11a: valid Transition reaches kernel once and passes.
- S11b: same payload with allowed versus excluded source realm produces PASS versus HOLD.
- S11c: mutation relative to frozen transition hash produces HARD_VETO before kernel.
- S11d: payload digest mismatch produces BINDING_VIOLATION before kernel.
- S11e: undeclared target postconditions produce HOLD before kernel.
- S11f: changing evidence references changes canonical hash.
- S11g: canonical hash is identical across independent Python processes.
- S11h: target-Realm policy changes the admission outcome before kernel evaluation.
- S11i: execution commitment binds transition hash, target Realm, payload digest, attempt ID and nonce at the effect boundary.
- S11j: basic RFC 8785 JCS byte vectors and string-only object keys are checked.
- τ-001: admission without a Transition is refused.
- τ-002: mutated Transition fails comparison against frozen hash.

S12 (Realms) and S13 (EVP) are not implemented or modified by this change.
