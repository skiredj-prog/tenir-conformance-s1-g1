# TAU Runtime Stress Rig — prototype

Status: **synthetic simulation / experimental harness**, not production integration or a conformance claim for the complete membrane.

## Scenarios

The harness models four behaviors:

1. **Concurrent permit replay:** 32 concurrent requests using one single-use permit; exactly one admission is expected.
2. **`tau_K` expiry:** a request older than the configured admission window is rejected.
3. **Cross-realm contradiction:** two proofs bound to the same attempt but making contradictory effect claims trigger `QUARANTINE_LOCK`; later admissions are refused.
4. **E3 epistemic limit:** the test driver knows an external effect happened, while the rig receives a signed proof claiming no effect. The rig cannot independently infer the hidden effect. This is an expected limitation, not a successful detection.

Additional tests verify that invalid signatures and proof/attempt binding mismatches are rejected, and that an expired request does not consume its permit.

## Run locally

From the repository root:

```bash
python -m pytest experiments/runtime_stress/test_tau_runtime_stress.py -v --tb=short
python experiments/runtime_stress/tau_runtime_stress.py --output artifacts/runtime-stress/result.json
```

The JSON output is scenario evidence for this model run. It is not cryptographic audit evidence and is not a signed EVP artifact.

## Model boundaries

- `MutableClock` makes the tests deterministic; the default clock is Python's monotonic clock. No real clock drift or network delay is injected.
- `valid_signature` is a boolean test fixture, not cryptographic signature verification.
- Realm Alpha/Beta/Gamma are proof labels, not isolated execution environments.
- `reported_effects_register` counts positive received claims, not ground-truth external effects.
- The model does not invoke the production `Membrane`, TAU manifest loader, TENIR kernel bridge, permit/receipt state machine, or external effect sink.
- The harness exercises selected behaviors only; it does not establish conformance of all invariants I1–I8 or production `tau_K` enforcement.

The production integration remains a separate follow-up requiring an explicit adapter boundary, cryptographic EVP verification, a defined authoritative clock contract, and evidence tied to the actual membrane state machine.
