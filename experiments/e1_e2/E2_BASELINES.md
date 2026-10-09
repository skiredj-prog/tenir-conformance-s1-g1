# E2 exploration baselines

This record separates the historical reference from the current membrane. Counts are meaningful only together with the exact explorer and membrane revisions that produced them.

## v1 — pre-S7 reference (HYPOTHESIS; reproduction pending)

- Expected depth-8 count: **36,892**.
- Candidate membrane revision: `84e46d94a6259ad1ec57757074a422d2f356ec49` (the S6 merge; pre-S7 according to the project chronology).
- Status: **HYPOTHESIS**, not yet reproduced from a pinned explorer + membrane pair.
- Important limitation: the tree at `84e46d94` does **not** contain `experiments/e1_e2/e2_explore.py`. Checking out that commit and running the present command verbatim is therefore not possible. The historical explorer that produced 36,892 must be recovered or the experiment must explicitly pin a compatible explorer and record that it is a reconstructed experiment. Do not describe 36,892 as reproduced until that evidence exists.

## v2 — current diagnostic branch (CURRENT)

- Current diagnostic branch: `diagnostic/e2-caller-nonce-and-exceptions-2026-10-09`.
- Depth 1: **18 distinct states**, 38 transitions checked; no invariant violations. The two added states are `admit_await(A1,effect=False)` and `admit_await(A2,effect=False)`, enabled by explicit nonce paths.
- Depth 8: **2,658 distinct states**, 96,103 transitions checked; no invariant violations.
- Status: **CURRENT observed baseline**, not a claim of equivalence to the pre-S7 machine.
- Run evidence: [Run #5](https://github.com/skiredj-prog/tenir-conformance-s1-g1/actions/runs/37957660266).

## Interpretation

The 18-versus-16 depth-1 delta is understood as two additional explicit-nonce paths in the current explorer. The 36,892-versus-2,658 depth-8 delta is **not yet causally attributed**. S7/S8/S10/S11 preconditions are plausible contributors, but this remains a hypothesis until a compatible historical run or a controlled cross-revision experiment isolates them.

The CI gate uses 18 as the expected current depth-1 anchor and runs depth 8 only after that anchor passes. It does not require the current membrane to reproduce the historical count.

## S12 ND-1

S12 ND-1 is validated independently of the E2 state-count baseline by `tests/test_s12_nd1_realm_divergence.py`. The diagnostic workflow runs this test before E2 exploration. An E2 count mismatch must not, by itself, block S12; S12 remains contingent on its own test result and its own scope.
