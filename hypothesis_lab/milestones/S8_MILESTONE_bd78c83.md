# Milestone S8 — Concurrent admission (bounded scope)

**Status:** VERIFIED — BOUNDED SCOPE  
**HEAD:** `bd78c83b1a7011b9500c0fa7cf306435661c7e2f`  
**CI run:** https://github.com/skiredj-prog/tenir-conformance-s1-g1/actions/runs/37989324889 (success)  
**Date pinned:** 2026-10-09  

**Formal statement:**

> S8 finite-model and targeted-harness verification completed for the tested two-thread scenarios. The expected adversarial counterexamples remain present, the intended models satisfy their declared invariants, and the associated targeted tests pass. Multi-process behavior, crash recovery, general concurrency safety, and production conformance remain unestablished.

## Evidence bundle (this milestone)

| Item | Reference |
|------|-----------|
| Lab report JSON | `hypothesis_lab/milestones/S8_lab_report_bd78c83.json` |
| Report SHA-256 | `cf0cdb7d530f4c5760b161b6adb77bdbf3ee7961ddaf41c38068a27f44f5e2c7` (file: `S8_lab_report_bd78c83.sha256`) |
| Tested commit | `bd78c83b1a7011b9500c0fa7cf306435661c7e2f` |
| CI run | [37989324889](https://github.com/skiredj-prog/tenir-conformance-s1-g1/actions/runs/37989324889) |
| CI artifact name | `hypothesis-lab-report` |
| S8 pytest module | `tests/test_g0_s8_concurrent_admission.py` (105 passed on prior verification) |
| H4 prior milestone | `hypothesis_lab/milestones/H4_MILESTONE_3a11679.md` (FROZEN) |

## Exit criteria

| Criterion | State |
|-----------|--------|
| P1 — at most one effect | Adversarial counterexample present; intended PASS |
| P2 — at most one same-LEI registration | Adversarial counterexample present; intended PASS |
| P3 — stale commit adds no effect | Adversarial counterexample present; intended PASS |
| S8 pytest | 105 passed (prior verification on same code lineage) |
| CI on bd78c83 | Success |
| Lab report | Deterministic re-run: 7 FAIL / 5 PASS / 1 VACUOUS / 0 anomaly |
| H4 | Still present; frozen milestone |
| General / production conformance | Not established |

## Lab outcomes on pinned HEAD

```
S8-P1-adversarial  FAIL  t1_register → consume_and_effect → adversarial_double_effect
S8-P1-intended     PASS
S8-P2-adversarial  FAIL  adversarial_both_see_clear
S8-P2-intended     PASS
S8-P3-adversarial  FAIL  first_effect → mark_stale_commit → adversarial_apply_stale
S8-P3-intended     PASS
```

Adversarial FAIL is the **expected** finite-model outcome. Disappearance of an expected counterexample is an **ANOMALY**, not an automatic improvement.

## Implementation test references

| Model property | Primary harness tests |
|----------------|----------------------|
| P1 at-most-one effect | `test_s8a_barrier_synchronized_same_lei_admits_at_most_one` (×100), `test_s8c_racing_consumers_cannot_consume_same_permit_or_dispatch_twice`, `test_s8f_retry_after_resolved_winner_is_held_to_prevent_second_effect` |
| P2 single registration | `test_s8a_…`, `test_s8b_staggered_same_lei_admission_rejects_second` |
| P3 no extra effect after resolve / single-use | `test_s8c_…`, `test_s8f_…`, `test_s8e_winner_completes_and_resolved_lei_remains_locked` |
| Non-global lock | `test_s8d_different_leis_are_not_globally_serialized` |

## Explicit limits

- Finite two-thread model and process-local harness lock only.
- Intended PASS means violations are unreachable under *that* action set — not that the harness enforces the invariant in all untested scenarios.
- CI workflow success and artifact presence were observed; the remote ZIP was not always byte-inspected (API auth). Local re-run on the pinned SHA is archived here for audit.
- Multi-process, crash recovery, general concurrency safety, and production conformance remain **unestablished**.

## Freeze rule

Do not remove expected FAIL entries for `S8-P1-adversarial`, `S8-P2-adversarial`, or `S8-P3-adversarial` without a deliberate milestone revision.
