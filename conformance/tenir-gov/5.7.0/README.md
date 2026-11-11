# TENIR-Gov 5.7.0 — Conformance claim register (candidate)

Status: **UNQUALIFIED / PARTIAL_EVIDENCE**. This is a historical intake record, not certification or a release attestation.

## Binding (mandatory before promotion)
- Product: TENIR-Gov
- Claimed release: 5.7.0
- Release tag and immutable commit SHA: **UNVERIFIED**
- Reference: REG-ARCH v0.4 (normative text and digest **TO BIND**)
- REG contracts: exact RFC revisions and applicability **TO BIND**
- Conformance suite version and commit: **TO BIND**
- Evidence run IDs, timestamps, hashes: **TO VERIFY**

## Claims and evidence boundaries
| Claim | State | Basis / limitation |
|---|---|---|
| Native reconciliation/idempotency tests | PARTIAL_EVIDENCE | Earlier P0 report: 44/44 native tests, 6/6 verifier adversarial tests. CI-to-release binding not yet established. |
| REG T6/T7 | PARTIAL_EVIDENCE | Earlier harness report: 14 PASS / 41 GAP; not a full normative qualification. |
| REG T8 retry authorization | GAP | Authorization contract not yet demonstrated for 5.7.0. |
| REG-ARCH v0.4 | NOT_DEMONSTRATED | Preliminary documentary review of 25 obligations: 23 PARTIAL, 2 GAP, 0 DEMONSTRATED; not runtime proof. |
| External regulatory certification | NOT_CLAIMED | No certification claimed. |

## Rules
1. Every claim binds standard version, applicability, implementation release+commit, test suite version+commit, and immutable evidence manifest.
2. Unknown fields must stay UNKNOWN; never synthesize provenance or promote draft PR tests to released-version evidence.
3. Changes in any binding require impact assessment and potentially requalification.
4. Distinguish structural admissibility from effective guarantees and legal compliance.
5. Status values: DEMONSTRATED, PARTIAL_EVIDENCE, GAP, NOT_DEMONSTRATED, NOT_APPLICABLE (justified), NOT_CLAIMED.

## Next qualification steps
- Pin release tag to SHA; verify workflow run provenance and evidence digests.
- Establish clause-level applicability and evidence links for REG-ARCH.
- Export real traces without fabricating causal/authority/version fields; evaluate with independent P0-A oracle.
- Generate machine-readable record and CI validation, preserving this file as a human-readable intake.
