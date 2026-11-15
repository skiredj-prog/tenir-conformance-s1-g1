# E2 exploration baselines

Counts are meaningful only with the exact explorer, membrane revision, world, depth, and invocation that produced them. The historical count is not a CI oracle.

## v1 — historical pre-PR#6 reference

- Historical depth-8 figure: **36,892** states (`honest`).
- Status: `REPRODUCED_FROM_ARCHIVE` (15 November 2026). The explorer archived at tag `archive/forensic/e2-key-audit-20261009` (`cf1b1ea`), run with the membrane overlay `84e46d9` as in `e1-e2-repro.yml`, reproduces all four v1 outputs field for field, runtime excepted. The script behind the first Zenodo version itself is not preserved. Replay record: `reg-conformance/manuscript/evidence/v7.2/replay-2026-11-15/` (Zenodo [10.5281/zenodo.24249646](https://doi.org/10.5281/zenodo.24249646)).
- The figure remains a historical reference, not a CI oracle for the current explorer and membrane.

## Current main-branch baseline

- Source: PR #15 merge `26b9466ec666de18e5acaac4ce1fac0135cadd9e`.
- Evidence: [post-merge Membrane CI Run #150](https://github.com/skiredj-prog/tenir-conformance-s1-g1/actions/runs/37962357582).
- Depth: 8; all four worlds completed; no invariant violations.

| World | Distinct states | Transitions checked | Violations |
|---|---:|---:|---|
| `honest` | 675 | 25,297 | 0 |
| `false_attest` | 1,539 | 56,111 | 0 |
| `hidden_honest` | 1,059 | 41,807 | 0 |
| `adversarial` | 2,307 | 88,567 | 0 |

These are the current four-world observations for this exact main-branch explorer/membrane revision. They are not expected to equal v1.

**These counts exercise no dispatch.** The replay of 15 November 2026 showed that against the current membrane every dispatch-class event of the unmodified explorer raises `NONCE_REQUIRED` and every qualified non-execution claim is rejected for a missing signature, so the zero violations above are not evidence about `I1`. With the explorer supplying the attempt nonce and an Ed25519 attestation from `tests/s7_helpers.py` (patch in the replay record), `d42499b` gives:

| World | Depth | Distinct states | Transitions checked | `I1` occurrences | Shortest trace |
|---|---:|---:|---:|---:|---:|
| `honest` | 8 | 149,771 | 2,702,234 | 0 | — |
| `false_attest` | 7 | 178,890 | 2,201,968 | 0 | — |
| `hidden_honest` | 8 | 180,193 | 3,424,852 | 0 | — |
| `adversarial` | 7 | 280,023 | 3,410,213 | 305,429 | 3 |

The committed explorer has not yet been updated with that patch; until it is, its CI output should not be read as an invariant check of dispatch.

## Separate diagnostic-branch observation

The earlier diagnostic branch `diagnostic/e2-caller-nonce-and-exceptions-2026-10-09` recorded **2,658 states / 96,103 transitions** at depth 8 in its invocation. That result belongs to that branch/configuration and must not be conflated with the four separately invoked worlds in Run #150.

## CI policy

E2 remains active as a bounded exploration and invariant check. CI must not fail merely because a current state count differs from the pre-PR#6 historical figure. If a current baseline changes, preserve the run link and explain the configuration; do not silently change expected counts to manufacture a green build.
