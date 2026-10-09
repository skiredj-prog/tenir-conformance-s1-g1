# G0 S8 CI Evidence Record

Recorded: 2026-10-09  
Repository: https://github.com/skiredj-prog/tenir-conformance-s1-g1

## Baseline falsification

- Baseline CI run: https://github.com/skiredj-prog/tenir-conformance-s1-g1/actions/runs/37909668110
- Baseline run ID: `37909668110`
- Result: expected failure of S8a against the unprotected admission check-then-act path.
- Observed counterexample: both `A2` and `A1` registered for the same LEI `L`; both reached `RESOLVED` and both dispatched effects.
- Assertion failed: exactly one attempt registered; actual count was 2.

This is a concrete counterexample for the tested implementation and schedule, not a claim that every unsynchronized run must fail.

## Corrected implementation and CI

- Tested source commit: `3fb9413fd66cc1b91bd773635a1f24887ac51356`
- Workflow: `Membrane CI (S1–S8 + T7/T8)`
- Run ID: `37910123312`
- Run URL: https://github.com/skiredj-prog/tenir-conformance-s1-g1/actions/runs/37910123312
- Result: `completed / success`
- S8 test step: success
- S8 evidence-generation step: success
- S8 artifact-upload step: success
- S8a repeated executions: **100 passed / 100; 0 failed**
- Scenario SHA-256: `65924e6e8308f6b3544c9e6c6d6656edb97ee26ca04befb2132c1c7ce85f5552`

The CI suite includes S8a (100 parametrized test runs), S8b, S8c, S8d, S8e, and S8f, plus the existing S1–S7 and T7/T8 checks.

## Evidence artifact

- Artifact name: `s8-evidence`
- Artifact ID: `11606252583`
- Archive size: `24585` bytes
- GitHub artifact SHA-256: `c37239583dfad1544359231851695dbdc4e611f903ca17e2ce7864c860394e19`
- Artifact URL: https://api.github.com/repos/skiredj-prog/tenir-conformance-s1-g1/actions/artifacts/11606252583
- Expires: `2027-01-07T09:15:40Z`

The archive contains the generated JSONL transition/thread trace, registry snapshots, run summary, and scenario SHA-256 record. GitHub Actions artifact retention is finite; download and preserve the archive separately if long-term archival is required.

## Interpretation and limitations

The baseline establishes a concrete failure under a deliberately synchronized check-then-act interleaving. The corrected run establishes that the implemented process-local admission lock and single-use permit guard passed the recorded tests, including 100 repeated S8a cases.

This does **not** establish safety for more than two callers, multi-process or distributed concurrency, crash recovery, fairness, deadlock/starvation freedom, or production deployments. The S8c test deliberately races two consumers against one already-issued permit; it tests single-use consumption and does not claim that the public admission path issued two permits. A 100/100 result is empirical evidence for the tested executions, not a mathematical proof of all schedules.
