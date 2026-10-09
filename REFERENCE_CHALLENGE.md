# TENIR Reference Challenge

**Status:** Phase 1 complete at laboratory scope · Phase 2 proposed, not started  
**Last updated:** 2026-10-09  
**Reference commit:** `84e46d9` (merge of PR #4)  
**Companion paper:** *Architectural Separation and Verifiable Admissibility in Cross-Realm Governance*, Manuscript v6.6.1 (v6.7 pending)  
**Companion protocol:** RFC-0 through RFC-7, `skiredj-prog/reg-conformance`

---

## Purpose

This document defines the two-phase evaluation program for the TENIR
admissibility membrane. It separates two questions that are often
conflated:

1. **Protocol conformance.** Does a membrane implement the RFC
   specification correctly?
2. **Comparative effectiveness.** Given a conforming membrane, does it
   reduce harm compared to alternative control models?

Phase 1 answers the first. Phase 2 answers the second. Phase 2 requires
a Phase 1 result: without a conforming subject, comparison has no
referent.

---

## Phase 1 — Protocol Conformance

**Status:** Complete at laboratory scope, sequential interleavings only.

**Question:** Does an implementation satisfy RFC-4 at the boundary it
claims to govern?

**Subject under test:** the RFC-4 membrane in this repository
(`src/tenir_conformance/membrane/`), backed by the reference
`PolicyEngine` from `reg-conformance` for scoring. The kernel supplies
the scalar score; the membrane enforces the permit/attempt/receipt
lifecycle.

**Method:** fault-injection scenarios S1–S6, each with a frozen G0
specification, an executable harness, and raw evidence artifacts. Each
scenario is executed against the membrane. Client-side projections,
state transitions, permit consumption, and kernel invocation counts are
recorded.

### Scenario status

| ID | Locked name | G0 spec frozen | Executed | Artifacts |
|----|-------------|:--------------:|:--------:|:---------:|
| S1 | ACK Loss | ✓ | ✓ | ✓ |
| S2 | Qualification Timeout | ✓ | ✓ | ✓ |
| S3 | Duplicate Request | ✓ | ✓ | ✓ |
| S4 | Stale Receipt | ✓ | ✓ | ✓ |
| S5 | Contradictory Evidence | ✓ | ✓ | ✓ |
| S6 | Successful Reconciliation | ✓ | ✓ | ✓ |

### Evidence

Each executed scenario produces a set of artifacts:
- transition log (JSONL, append-only)
- permit registry state
- effect sink snapshot
- result summary
- SHA-256 of the scenario definition file

Artifacts are generated at CI runtime, not versioned in the repository.
An aggregate manifest is committed at [`MANIFEST.json`](./MANIFEST.json).

**Reference runs:** [CI #56](https://github.com/skiredj-prog/tenir-conformance-s1-g1/actions/runs/37865202825) and [CI #58](https://github.com/skiredj-prog/tenir-conformance-s1-g1/actions/runs/37865306599) (post-merge), both green.

The workflow runs the S1–S6 and T7/T8 suites and the real TENIR
`PolicyEngine` integration.

### Verified properties

| Assertion | Result observed |
|-----------|-----------------|
| S1 client projection uniformity | `(UNKNOWN, HOLD)` across all three sub-cases |
| S2 τ_K boundary semantics | Fires at boundary, idempotent, per-LEI isolated |
| S3 duplicate request | Second attempt blocked before permit issuance |
| S4 stale receipt | Receipt rejected after window closure; `effect_observed` required |
| S5 contradictory evidence | Conflict preserved; no auto-resolution; quarantine on terminal conflict |
| S6 reconciliation | `UNKNOWN → RESOLVED` (effect confirmed) and `UNKNOWN → FAILED` (non-execution attested) |
| LEI lock semantics | `RESOLVED` permanent lock; `FAILED` releases only with `non_execution_confirmed=True` |

### Epistemic scope

Successful execution of S1–S6 empirically validates **the tested
sequential interleavings** of the RFC-4 membrane implementation. It
does not constitute:

- a formal proof of thread safety under unconstrained asynchronous
  concurrency;
- a demonstration that the reference `PolicyEngine` implements RFC-4
  (the kernel supplies scoring; the membrane supplies lifecycle
  governance);
- a claim about production behavior outside the tested single-process
  environment;
- a cryptographic verification of `non_execution_confirmed`. That flag
  is a declarative attestation supplied by the caller. In production
  deployment, it must be backed by a signed reconciliation receipt from
  the target or an independent audit path.

---

## Phase 2 — Comparative Effectiveness

**Status:** Proposed. Not started.

**Question:** Given a conforming membrane, does it reduce harm compared
to alternative control models?

**Method:** a multi-agent testbed with a shared backend, incompatible
agent objectives, and protected resources. Four control conditions are
compared under identical workloads.

### Control conditions

| # | Condition | Description |
|---|-----------|-------------|
| 1 | No independent control | Agents act directly on the backend. No gate. |
| 2 | Prompt-declared hierarchy | Agents receive roles via prompt; no runtime enforcement. |
| 3 | Conventional least privilege | Static permission model applied at the API layer. |
| 4 | TENIR membrane | RFC-4 conforming membrane at the execution boundary. |

### Required properties of the testbed

1. **Shared mutable backend.** State that agents can modify.
2. **Protected resources.** Assets whose loss is observable.
3. **Incompatible objectives.** Agent goals that produce interference
   if uncoordinated.
4. **Legitimate workload.** Tasks that must succeed, so the evaluation
   measures both harm avoided *and* work authorized.
5. **Indirect consequences.** Descendant credentials, retries,
   failover paths, and alternative routes must be covered.
6. **Pre-declared invalidation criteria.** Failure conditions stated
   before execution, not after.
7. **Comparison to conventional controls.** Not merely to absence of
   control.

### Outputs

- incidents avoided (per condition)
- false blocks (legitimate work refused)
- operational latency introduced
- evidence trace completeness per incident
- cost of governance friction

### Gate for Phase 2 entry

Phase 2 begins only after:
- all six G0 specifications are frozen and versioned;
- the corresponding executions and artifacts are published;
- a stable subject implementation is identified and pinned.

These conditions are met for the laboratory baseline at reference commit
`84e46d9`. This is a sequencing gate, not evidence of comparative
effectiveness or production readiness.

### What is not claimed

- Phase 2 has not been started.
- No comparison against a deployed commercial PEP/PDP has been run.
- No multi-agent measurement has been produced.
- No claim is made that TENIR reduces harm in any operational setting.
  That is precisely the question Phase 2 exists to test.
- Phase 1 results do not establish effectiveness. They establish that
  the subject behaves as specified under the tested interleavings.

---

## Relationship to the strategic document

A separate strategic document (dated 2026-09) proposed the "TENIR
Reference Challenge" as the first deliverable. That document predates
the current implementation work.

This file is the operational reference. The strategic document remains
valid as the source of Phase 2 requirements. Where the two diverge,
this file is authoritative for status and sequencing.

**Correspondence:**

| Strategic element | Operational status |
|--------------------|--------------------|
| TENIR Manifesto | Not written. Manuscript v6.6.1 serves as technical reference. |
| Reference Harness | Phase 1 complete (S1–S6). Phase 2 testbed not started. |
| Admissibility Policy | Distributed across RFC-4 and RFC-5. No single unified document. |
| Evidence Pack | CI artifacts per scenario + `MANIFEST.json` aggregate. |

---

## Next actions

1. Update the companion manuscript from v6.6.1 to v6.7, declaring S1–S6
   and their actual laboratory scope.
2. Integrate the `non_execution_confirmed` limitation stated above into
   the manuscript.
3. Keep this status and `MANIFEST.json` synchronized with future
   validation runs.

Do not begin Phase 2 design until the manuscript updates above are
complete.

---

## Closing note

The purpose of this program is not to demonstrate that TENIR works.
It is to define the conditions under which TENIR can be falsified,
and to publish the results — positive, negative, or inconclusive —
under those conditions.

A failed result is as informative as a passing one. A gap in the
specification is as valuable as a closed one.
