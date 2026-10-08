# Scientific status of this package

**HEAD reference for this statement:** `487db4f` (update when re-validating).

## What this package establishes

1. **G0 operational definitions** for S1–S5 (ACK loss, qualification timeout, duplicate request, stale receipt, contradictory evidence).
2. An **RFC-4 lab membrane** (`Membrane` + `Receipt` + escalation/quarantine) implementing the corresponding guards.
3. **Empirical PASS** on sequential interleavings via CI (`Membrane CI (S1–S5 + T7/T8)`), including:
   - S1 membrane path against a real `tenir_governance.PolicyEngine` for scoring
   - S4 strict A6 (`Receipt` mandatory for RESOLVED; legacy kwargs cannot qualify)
   - S5 contradiction → `ESCALATED` / LEI `QUARANTINED` with Δ effects = 0
4. **Evidence artifacts** (JSON/JSONL, spec & scenario SHA-256) uploaded per family (`s1-evidence` … `s5-evidence`).

## What this package does **not** establish

- Safety under **unconstrained asynchronous concurrency**
- **Production cryptographic** verification of evidence (signatures, PKI)
- Correctness of **business-unit normalization** converters (mixed profiles are rejected; converters are not proven)
- That any **production REG/TENIR gateway** is certified conformant
- A formal mathematical proof (TLC / model checking of the full concurrent system)

## Correct public statement

> G0 S1–S5 have been empirically validated against the RFC-4 lab membrane for the tested sequential interleavings, with CI artifacts. This is not a general concurrency proof and not a production certification.

## Next steps for stronger validation

1. G0 S6 — Successful reconciliation (terminal convergence without new effects).
2. Minimal signed-evidence adapter (integrity not only injected).
3. Export lifecycle vectors into `reg-conformance`.
4. Keep this file in sync with each validation HEAD.
