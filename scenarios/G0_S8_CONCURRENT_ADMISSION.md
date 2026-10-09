# G0 S8 — Concurrent Admission Under Bounded Two-Thread Interleaving

## Claim

Within one Python process, concurrent callers using the same LEI cannot both register an attempt through the membrane's admission path. The compound unresolved-LEI check and attempt registration are serialized by a process-local re-entrant lock. Permit consumption is also serialized and single-use. This is a bounded two-thread conformance test, not a distributed-lock proof.

## Initial state

- LEI `L` is unregistered; `membrane.attempts` and `membrane.permits` are empty.
- Two OS threads have distinct attempt IDs (`A1`, `A2`) and nonces.
- Both payloads are admissible under the configured kernel bridge.
- A start barrier releases both callers concurrently.

## Sub-cases

- **S8a — Barrier-synchronized admission:** 100 independent runs. Exactly one same-LEI attempt is registered; the other call returns `(UNKNOWN, HOLD)`. Exactly one permit and at most one effect are observed per run.
- **S8b — Staggered admission:** T1 registers and is paused immediately after registration; T2 enters 1 ms later and must be rejected while T1 remains unresolved.
- **S8c — Permit-consumption race:** two threads race to consume the same already-issued permit. Exactly one consumption succeeds; the other receives `PERMIT_ALREADY_CONSUMED`; only the successful consumer dispatches an effect. This directly tests the private single-use primitive, not a public API that issues two permits.
- **S8d — Different LEIs:** simultaneous calls for `L` and `M` both complete. The admission lock is not a global one-at-a-time transaction lock.
- **S8e — Sequential regression:** the winning admissible attempt reaches `RESOLVED` and emits one effect.
- **S8f — Retry after resolved winner:** a second attempt for the same LEI remains `HOLD`, preserving the at-most-once effect rule after a successful resolution.

## Invariants

- **I1 — At-most-once effect:** at most one effect is dispatched for the contested LEI in S8a/S8b.
- **I2 — Permit single-use:** concurrent consumption of one permit has one winner.
- **I7 — Admission condition:** same-LEI unresolved-state checking and attempt registration form one serialized operation.

## Evidence

CI runs `tests/test_g0_s8_concurrent_admission.py` and executes `tools/run_s8.py` to emit:
- merged JSONL transition/thread trace;
- before/after attempt, permit, and effect-sink snapshots;
- repeat count and pass/fail summary;
- SHA-256 of this scenario definition;
- thread exceptions and exit status.

## Scope and limitations

The lock is process-local. This scenario does not establish safety for more than two callers, multi-process execution, distributed deployments, crash recovery, fairness, starvation, or deadlock freedom. The test suite's 100/100 result supports only the recorded tested interleavings. The S8c injected same-permit race tests the single-use guard independently; it is not evidence that the public admission path actually issued two permits.

## Baseline finding

Before the lock was added, the deterministic S8a test failed with two registered attempts (`A2`, `A1`) for the same LEI. The baseline CI run is retained as the falsification reference; the corrected implementation must pass the same test.
