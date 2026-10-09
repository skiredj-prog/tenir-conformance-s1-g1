# Scenario G0 S5 — Contradictory Evidence & Epistemic Escalation

**Scenario ID:** G0_S5  
**Target:** RFC-4 Membrane / Evidence Evaluation Pipeline  
**Invariant Goal:**

$$
\operatorname{Conflict}(\mathcal E)\Rightarrow
\neg\operatorname{CommitTransition}(\mathcal E)
\land \Delta\operatorname{Effects}=0
\land \Delta\operatorname{IssuedExecutionPermits}=0
\land \neg\operatorname{ExistingPermitUsable}(\mathcal E)
\land \operatorname{EscalationRecorded}
$$

**Normative Invariants:** REG-CORE-019, REG-CORE-015, REG-CORE-012  
**Implementation Status:** EXECUTED / EMPIRICALLY VALIDATED — TESTED SEQUENTIAL INTERLEAVINGS ONLY

---

## 1. Executive Summary & Intent

G0 S5 validates the membrane response to hard epistemic uncertainty: a complete batch containing receivable evidence items that make semantically incompatible claims about the same attempt. The membrane MUST NOT silently resolve conflict through optimistic heuristics. Evaluation is atomic and escalation is auditable. Each evidence item has a unique, stable evidence_id.

Conflict is defined by at least one pair of items in the batch:

- **OutcomeConflict:** incompatible final outcomes, such as FAILED versus COMMITTED.
- **PropertyConflict:** divergent values for the same authoritative, conflict-sensitive business property, for the same scope and reference snapshot, after applicable normalization.

A missing mandatory property is incomplete evidence, rejected as IncompleteEvidence at schema validation; it is not a contradiction. Evidence properties supplied to the evaluator are already normalized according to their declared normalization profile. A deployment adapter must establish that normalization and the upstream integrity/source-authority verdicts.

## 2. Sequence Interleavings

### S5a — Divergent outcomes on a non-terminal attempt

1. Submit A1 for LEI-L; the attempt is UNKNOWN and effects have baseline count C.
2. Submit a complete, correctly bound batch containing E_FAIL and E_OK.
3. The atomic contradiction guard records EVIDENCE_CONTRADICTION and transitions the non-terminal attempt to ESCALATED.
4. Return HOLD or ContradictoryEvidenceError. Effect count remains C; no new permit is issued and existing permits are unusable through this path.

### S5b — Property contradiction on a terminal attempt

1. A1 is already RESOLVED, representing a committed terminal outcome; effects have baseline count C.
2. Reconcile a complete batch containing E_OK(X) and E_OK(Y), both COMMITTED but with different normalized values for the same conflict-sensitive property, scope and reference snapshot.
3. Record EVIDENCE_CONTRADICTION and a separate escalation incident. Preserve A1's exact terminal state and apply Governance Quarantine to LEI-L.
4. Return HOLD or ContradictoryEvidenceError. Effect count remains C; no new permit is issued and prior permits cannot be used on this path.
5. Governance Quarantine persists until explicitly released by an authorized, audited resolution procedure.

## 3. Consolidated Normative Guard Hierarchy

1. **Schema, integrity and completeness:** validate mandatory fields, upstream integrity/authenticity results, freshness, source authority and scope. Missing mandatory data raises IncompleteEvidence.
2. **Strict binding:** every item MUST match the same attempt_id, nonce and LEI. Failure raises BindingError, not ContradictoryEvidenceError.
3. **Atomic evaluation:** validate the complete batch before any outcome transition. No item may commit early.
4. **Contradiction detection:** detect OutcomeConflict or PropertyConflict after applicable normalization, for the same reference scope/snapshot.
5. **If EVIDENCE_CONTRADICTION:**
   - Record the canonical event with attempt_id and all conflicting evidence_id values.
   - Delta IssuedExecutionPermits equals zero.
   - Existing permits must be unusable through the contradictory-evidence path.
   - Delta EffectSink count equals zero.
   - If the attempt is non-terminal, transition it to ESCALATED and preserve the LEI lock.
   - If the attempt is terminal, preserve its exact state, apply a Governance Quarantine Lock to the LEI, and record a separate incident.
   - Return HOLD or raise ContradictoryEvidenceError.
6. **Only if** the complete batch is valid, correctly bound and non-contradictory may normal outcome evaluation continue.

The LEI quarantine is a separate governance state; it does not rewrite a terminal attempt. Quarantine remains active until an explicit resolution with an authorized actor, incident identifier and rationale is recorded. Previously revoked permits are never restored.

## 4. Empirical Evidence Requirements

PASS requires the harness to write:

1. The exact SHA-256 of this versioned specification file.
2. An attempt/LEI-lock snapshot showing the non-terminal lock for S5a and QUARANTINE_LOCK for S5b.
3. A measured EffectSink delta: count_after minus count_before equals zero on every contradictory path.
4. A permit registry diff proving no new permit was issued and no existing permit remained usable through the contradictory path.
5. A raw JSONL transition trace containing EVIDENCE_CONTRADICTION, attempt_id and the conflicting evidence_id values.

The harness must adapt these observations to actual lab interfaces; it must not claim cryptographic verification unless a real verifier supplies that result.

## 5. Formal Assertions Matrix

| # | Domain | Assertion | Success criteria |
|---|---|---|---|
| A1 | Client/API | Protocol decision | HOLD or ContradictoryEvidenceError |
| A2 | State safety | Post-evaluation attempt state | ESCALATED if initially non-terminal; otherwise exact terminal state preserved and LEI QUARANTINED |
| A3 | Effect invariant | Effect sink delta | Delta EffectSink.count equals zero |
| A4 | Guard decision | Explicit contradiction trace | EVIDENCE_CONTRADICTION with bound evidence IDs |
| A5 | Permit safety | Execution authorization lock | No new permit and no existing permit usable through this path |
| A6 | Identity/binding | Evidence binding | Attempt ID, nonce and LEI strictly match; negative tests reject at binding |
| A7 | Empiricism | Scientific claim scope | Tested sequential interleavings only |

## 6. Scientific Claim Statement

> **Epistemic notice:** Successful execution of G0 S5 empirically validates epistemic escalation, atomic batch evaluation and anti-auto-resolution for the tested sequential interleavings of the RFC-4 membrane implementation. It is not a formal proof of real-time thread safety under unconstrained asynchronous concurrency. Implementation conformance mapping remains subject to the concrete adapters used in the test harness.
