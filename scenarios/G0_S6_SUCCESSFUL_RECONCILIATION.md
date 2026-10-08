# Scenario G0 S6 — Successful Reconciliation & Terminal Convergence

**Scenario ID:** G0_S6  
**Target:** RFC-4 Membrane / Evidence Evaluation Pipeline  
**Invariant Goal:**

$$
\operatorname{ValidEvidence}(\mathcal E) \land \neg\operatorname{Conflict}(\mathcal E)
\Rightarrow
\operatorname{TerminalTransition}(A_1)
\land \Delta\operatorname{NewEffects}=0
\land \operatorname{LEIResolved}
$$

**Normative Invariants:** REG-CORE-020, REG-CORE-015, REG-CORE-001  
**Implementation Status:** SPECIFICATION DRAFT / EMPIRICAL VALIDATION PENDING

---

## 1. Executive Summary & Intent

G0 S6 validates the membrane's ability to converge safely from epistemic uncertainty (UNKNOWN) by processing valid, non-contradictory evidence of an external outcome.

It introduces a critical distinction from G0 S4 (Stale Receipt):

- **G0 S4** rejects a late execution receipt via **deliver_qualifying_receipt** because the attempt's execution window is closed.
- **G0 S6** uses a dedicated observation API, **reconcile**, to register evidence about a past external outcome. It does not reopen the execution window, trigger execution, emit an effect, or create/reuse an execution permit.

The objective is to demonstrate that reconciliation:

1. Converges A1 to a native terminal membrane state (RESOLVED or FAILED).
2. Does not cause double execution: delta NewEffects equals zero during the reconciliation/failure-adjudication call.
3. Does not re-use the initial permit consumed by A1.
4. Resolves the LEI lock according to the verified outcome: a new attempt A2 may be admitted only if A1 is FAILED and retry_eligible is true. A successfully resolved A1 does not authorize a retry of the same logical operation.

### S5 decoupling note

S6 is an observation/convergence scenario, not an evidence-conflict scenario. Its input is a singleton, semantically unified evidence claim. Do not implement **reconcile** by calling **deliver_qualifying_receipt**, and do not allow reconciliation to invoke EffectSink or execution-permit issuance. G0 S5 remains the dedicated guard for contradictory evidence batches; where the S5 evidence contract is reused, strict binding and evidence-validity requirements remain in force.

---

## 2. Sequence Interleavings

### S6a — Successful discovery after timeout (UNKNOWN to RESOLVED)

Reconciliation proves that the external operation succeeded despite expiry of the qualification timeout. The observation updates state only.

1. Submit A1 for LEI-L; the external operation may execute and the attempt enters AWAITING_QUALIFICATION.
2. After tau_K, A1 transitions to UNKNOWN and the qualification window is closed.
3. Call **reconcile(attempt_id="A1", outcome="COMMITTED", evidence_qualified=True)** using a valid, correctly bound, non-contradictory evidence item.
4. A1 transitions to RESOLVED and qualified becomes true.
5. Return RECONCILIATION_OK. EffectSink delta during the reconcile call is zero. The initial permit remains consumed and is not reused; no new permit is issued.

### S6b — Failure discovery and LEI unlock (UNKNOWN to FAILED)

Reconciliation/failure adjudication establishes qualified evidence of non-execution. The LEI may then admit A2 only when retry eligibility is explicitly true.

1. Submit A1 for LEI-L; the attempt becomes UNKNOWN after loss/timeout.
2. Call **declare_failed(attempt_id="A1", evidence_qualified=True, retry_eligible=True)** based on qualified failure evidence.
3. A1 transitions to FAILED; the retry guard reports eligibility for the LEI.
4. Admit A2 under a new attempt ID. A2 receives its own permit through normal admission and may execute once.
5. Measure EffectSink delta across the **declare_failed** call separately from A2 admission/execution. The failure-adjudication call itself must produce no new effect and must not issue or reuse an execution permit.

---

## 3. RFC-4 Membrane Mapping

| S6 specification | Membrane mapping |
|---|---|
| Batch Reconcile(A1), success | **reconcile(attempt_id, outcome, evidence_qualified=True)** — new, dedicated observation API |
| COMMITTED outcome | **state = RESOLVED**, **qualified = True** |
| FAILED outcome | **declare_failed(..., evidence_qualified=True, retry_eligible=True)** |
| LEI unlocked for retry | **retry_eligible_for(lei) is True** when A1 is FAILED and retry-eligible |
| A2 admitted | **admit_and_await_qualification** / **_register_attempt** accepts a new attempt ID only under the S6 retry rule |
| No new effects | **len(sink.effects)** remains unchanged during **reconcile** or **declare_failed** |
| No permit reuse | Initial A1 permit remains consumed; A2 must receive its own permit only upon normal admission |
| Canonical trace | **RECONCILIATION_SUCCESS** for S6a; failure adjudication also retains the canonical T7 failure event |

---

## 4. Consolidated Normative Guard Hierarchy

1. **Path distinction:** Reconciliation uses the dedicated observation API **reconcile**; it does not call **deliver_qualifying_receipt** and does not reopen the S4 execution window.
2. **Schema and integrity:** Validate evidence completeness, integrity/authenticity result, freshness and source authority. The adapter must provide the evidence-verification result; the reconciliation shim must not claim to perform cryptographic verification unless it actually does so.
3. **Strict binding:** The evidence must be bound to A1's exact **attempt_id** and LEI. Where the S5 evidence contract applies, **nonce** binding is also mandatory.
4. **Contradiction guard:** S6 receives a singleton, semantically unified outcome. If a batch or conflicting claims are introduced, route to the G0 S5 contradiction guard; do not choose a result optimistically.
5. **Terminal idempotency:**
   - If A1 is already terminal and consistent with the evidence, acknowledge idempotently without state mutation, effect, or permit change.
   - If terminal state and evidence disagree, fail closed and defer to the applicable contradiction/escalation path; do not overwrite terminal state.
6. **Valid, non-terminal UNKNOWN:**
   - A verified COMMITTED outcome transitions A1 to RESOLVED and qualified=true through **reconcile**.
   - A verified FAILED outcome transitions through T7 **declare_failed**, with **evidence_qualified=True** and an explicit **retry_eligible** value.
   - Record the corresponding canonical state-transition event.
7. **Permit and effect isolation:** Reconciliation is read/observation-only with respect to execution: it MUST NOT call EffectSink, issue an execution permit, or restore/reuse A1's consumed permit.

**LEI retry rule:** A2 may be admitted if and only if A1 has been resolved to FAILED and **retry_eligible=True**. A RESOLVED success does not authorize retry of the same logical operation. The implementation must distinguish this terminal business lock from transient unresolved-attempt blocking and preserve existing T7/T8 rules for explicitly eligible failures.

---

## 5. Empirical Evidence Requirements

For empirical PASS, the harness must record:

1. **Scenario Spec SHA-256:** Exact SHA-256 of this versioned file.
2. **LEI lock/map state:** Evidence that S6b releases the retry lock only after A1 becomes FAILED with **retry_eligible=True**, and a successful RESOLVED A1 does not authorize A2 for the same logical operation.
3. **EffectSink delta:** **count_after - count_before == 0** measured over the **reconcile** or **declare_failed** call itself.
4. **Permit registry log:** No new permit during reconciliation/failure adjudication; A1's consumed permit remains consumed and is not reused; A2 receives a separate permit only through normal admission when retry is eligible.
5. **Raw JSONL transition log:** Trace showing UNKNOWN to RESOLVED for S6a, and UNKNOWN to FAILED plus retry eligibility for S6b.

The harness must explicitly separate the measured observation/failure-adjudication window from the later A2 admission/execution window.

---

## 6. Formal Assertions Matrix (7 G0 Rules)

| # | Domain | Assertion | Success criteria |
|---|---|---|---|
| A1 | Client/API | Decision upon valid reconciliation | Explicit successful state update or idempotent acknowledgement |
| A2 | State safety | Post-evaluation state of A1 | RESOLVED or FAILED, according to qualified evidence |
| A3 | Effect invariant | Delta in effect count | Delta NewEffects equals zero during reconciliation/adjudication |
| A4 | Guard decision | Explicit reconciliation trace | Canonical RECONCILIATION_SUCCESS event for S6a; T7 failure event for S6b |
| A5 | Permit safety | Execution authorization isolation | No new permit during reconciliation; A1's consumed permit is not reused |
| A6 | Identity/retry binding | LEI lock behavior | A2 admitted if and only if A1 is FAILED and retry_eligible is true |
| A7 | Empiricism | Scientific claim scope | Tested sequential interleavings only |

---

## 7. Scientific Claim Statement

> **Epistemic notice:** Successful execution of G0 S6 empirically validates safe convergence from unobserved states and proper resolution of retry locks for the tested sequential interleavings of the RFC-4 membrane implementation.
>
> - S6a (UNKNOWN to RESOLVED) requires the dedicated **reconcile** observation API, distinct from late receipt delivery.
> - S6b (UNKNOWN to FAILED plus LEI unlock) maps to T7 and **retry_eligible**.
> - EffectSink delta during reconciliation/failure adjudication equals zero.
>
> This is not a formal proof of real-time thread safety under unconstrained asynchronous concurrency. G0 S6 canonical conformance remains PENDING until the reconciliation API and test harness are implemented and empirically validated.
