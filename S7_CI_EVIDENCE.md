# S7 CI Evidence Record

Status: **CI passed; PR #7 merged**  
Recorded: 2026-10-09  
Repository: https://github.com/skiredj-prog/tenir-conformance-s1-g1

## Source and validation

- Pull request: https://github.com/skiredj-prog/tenir-conformance-s1-g1/pull/7
- PR head tested: `d515c211af59318641f9e8d91191e5d11bebe0a3`
- Squash merge commit on `main`: `fcc53f0970e8aa13b24ed0fa379d2a446d9201ed`
- Workflow: **Membrane CI (S1–S7 + T7/T8)**, run #86
- Run ID: `37908524682`
- Run URL: https://github.com/skiredj-prog/tenir-conformance-s1-g1/actions/runs/37908524682
- Result: `completed / success`
- Job `test`: success. The S1–S7/T7/T8 test steps and S1–S7 evidence upload steps all completed successfully.

## Artifact identities

The following SHA-256 digests are the GitHub Actions artifact digests returned by GitHub for run `37908524682`.

| Artifact | Artifact ID | Size (bytes) | SHA-256 digest | Expires |
|---|---:|---:|---|---|
| `s1-evidence` | 11606070740 | 4,758 | `0c741f1fc690f23dc3ee414ffdfe8f75c183ecc05341a9084d465b6fd20dbfda` | 2027-01-07 |
| `s2-evidence` | 11606110400 | 5,281 | `ace9e55758456f5691e63f7b69d599dbbbd30d5bafb249879cfae511b5f79b03` | 2027-01-07 |
| `s3-evidence` | 11605152840 | 6,660 | `52175a9416a4c41adde7790305c8e3787a3a463089aff77c575e93b6f7bf764f` | 2027-01-07 |
| `s4-evidence` | 11605222591 | 3,527 | `fed8453b4c19939ce430e144dc646d4a725df2ff3ff45a417a371e8e3a705f66` | 2027-01-07 |
| `s5-evidence` | 11605282131 | 4,142 | `67cc9444ce99ff6a5a183bfd5aac5344d19d7134fc29cc2648b87e2515b32960` | 2027-01-07 |
| `s6-evidence` | 11605217584 | 6,343 | `366f6dde57ac6bd0798530ffa09d71a451f8e7f233c808261c784313e5136e4c` | 2027-01-07 |
| `s7-evidence` | 11605302200 | 26,472 | `dba00a3101338b46b2ab80ba16932b683bcd0b5df759788b2d5828d6bada3d2b` | 2027-01-07 |

Artifact archive URLs are available through the run's Artifacts section. For direct artifact metadata, use:
- https://api.github.com/repos/skiredj-prog/tenir-conformance-s1-g1/actions/artifacts/11605302200
- https://api.github.com/repos/skiredj-prog/tenir-conformance-s1-g1/actions/artifacts/11606070740
- https://api.github.com/repos/skiredj-prog/tenir-conformance-s1-g1/actions/artifacts/11606110400
- https://api.github.com/repos/skiredj-prog/tenir-conformance-s1-g1/actions/artifacts/11605152840
- https://api.github.com/repos/skiredj-prog/tenir-conformance-s1-g1/actions/artifacts/11605222591
- https://api.github.com/repos/skiredj-prog/tenir-conformance-s1-g1/actions/artifacts/11605282131
- https://api.github.com/repos/skiredj-prog/tenir-conformance-s1-g1/actions/artifacts/11605217584

## Scope and limitations

This record freezes the run identity, tested source SHA, merge SHA, artifact IDs, sizes, digests, and stated expiry dates in version control. **The GitHub Actions artifact binaries themselves are still subject to GitHub's expiry policy (listed above); this manifest does not archive their binary contents permanently.**

The CI result supports the claim that the repository's defined S1–S7/T7/T8 checks and artifact-generation steps passed on the recorded PR head. It does not establish production REG validation, truthfulness of signed non-execution claims, or safety beyond the tested scenarios. The K1 key in the S7 fixtures is test-only and must not be used in production.
