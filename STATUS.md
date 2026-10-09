# Scientific status of this package

**Validated source commit:** `07b5f315bbbaab7649e6ae9049445913de141f25` (head of latest successful post-merge run).
**PR #4 merge commit:** `84e46d94a6259ad1ec57757074a422d2f356ec49`.
**Latest post-merge CI:** [Run #58 — Membrane CI (S1–S6 + T7/T8)](https://github.com/skiredj-prog/tenir-conformance-s1-g1/actions/runs/37865306599) — **PASS**, including S1–S6 and T7/T8 test steps and all six evidence uploads.
**Manifest:** [MANIFEST.json](./MANIFEST.json).

## What this package establishes

1. **G0 operational definitions** for S1–S6: lost evidence after commit, qualification timeout, duplicate request, stale receipt, contradictory evidence, and successful reconciliation.
2. An **RFC-4 lab membrane** implementing the corresponding guards and state transitions.
3. **Empirical PASS for the tested sequential interleavings** through CI, including:
   - S1 membrane path against a real `tenir_governance.PolicyEngine` for scoring;
   - S4 strict A6: a `Receipt` is mandatory for RESOLVED; legacy kwargs cannot qualify;
   - S5 contradictory evidence leading to escalation/quarantine with zero new effects;
   - S6 reconciliation from UNKNOWN to RESOLVED or FAILED, with no execution effect or permit mutation during reconciliation.
4. Seven dedicated S6 tests, alongside the S1–S5 and T7/T8 suites. The post-merge workflow passed and uploaded evidence archives for S1–S6.
5. A machine-readable manifest records the validated source commit, CI run, evidence archive URLs, and GitHub-reported SHA-256 digests.

## Important epistemic boundary

`Evidence.non_execution_confirmed` is a **declarative upstream attestation**. The lab membrane does not itself cryptographically verify that the target did not execute. A production deployment must back this attestation with a signed reconciliation receipt from the target or an independent audit path.

The CI result validates only the **tested sequential interleavings**. It is not a proof of unconstrained concurrent/thread-safe execution.

## What this package does not establish

- Safety under unconstrained asynchronous concurrency.
- Production cryptographic verification of evidence (signatures, PKI).
- Correctness of business-unit normalization converters; mixed profiles are rejected, but converters are not proven.
- Conformance or certification of any production REG/TENIR gateway.
- A formal mathematical proof or full concurrent-system model check.

## Correct public statement

> G0 S1–S6 have been empirically validated against the RFC-4 lab membrane for the tested sequential interleavings, with CI evidence artifacts and recorded archive digests. This is not a general concurrency proof, production cryptographic verification, or production certification.

## Remaining work outside this repository

- Update `REFERENCE_CHALLENGE.md` to mark S6 complete.
- Update manuscript v6.6.1 to v6.7, including the explicit upstream-attestation limitation above.
- Keep this status and `MANIFEST.json` synchronized with future validation runs.

Phase 1 is complete at the lab-validation level. Do not infer production readiness or start multi-agent Phase 2 from this result.
