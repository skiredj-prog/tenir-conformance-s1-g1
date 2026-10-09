# E2 exploration baselines

Counts are meaningful only with the exact explorer, membrane revision, world, depth, and invocation that produced them. The historical count is not a CI oracle.

## v1 — historical pre-PR#6 reference

- Historical depth-8 figure: **36,892** states.
- V1 was produced against a pre-PR#6 membrane by an explorer that was not committed. Neither artifact is recoverable. The 36,892 figure is preserved as historical evidence, not as a reproducible reference.
- Status: `HYPOTHESIS_UNRECOVERABLE`. Do not attempt to reproduce it with the current explorer and do not gate CI on it.

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

## Separate diagnostic-branch observation

The earlier diagnostic branch `diagnostic/e2-caller-nonce-and-exceptions-2026-10-09` recorded **2,658 states / 96,103 transitions** at depth 8 in its invocation. That result belongs to that branch/configuration and must not be conflated with the four separately invoked worlds in Run #150.

## CI policy

E2 remains active as a bounded exploration and invariant check. CI must not fail merely because a current state count differs from the unrecoverable pre-PR#6 historical figure. If a current baseline changes, preserve the run link and explain the configuration; do not silently change expected counts to manufacture a green build.
