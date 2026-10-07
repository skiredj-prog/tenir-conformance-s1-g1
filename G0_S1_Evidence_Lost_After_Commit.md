# G0 — S1: Evidence Lost After Commit

**Status:** Candidate operational definition (proposed). Not yet an approved normative scenario of REG.

**Claim**  
When the client cannot observe whether a consequential effect occurred, the retry must be held, not executed. Reconciliation resolves the state before any new attempt is authorized.

**Given (initial state)**
- `permit(L, A) = ISSUED`, not `CONSUMED`
- target state is not observable to the client
- `receipt_observed = false`

**When**
- the client retries with LEI `L` and a fresh nonce, without reconciliation

**Then (assertions)**
1. `exec(A) = UNKNOWN`
2. `recon(A) = PENDING`
3. `T1_IssuePermit` guard evaluates `FALSE`
4. no new permit is issued for `L`
5. `effect_sink.count()` is unchanged by the retry
6. transition log contains `T3_ReceiptLost`, then `T1_guard_FALSE`
7. client response = `HOLD`

**Sub-cases** (same client behavior, different target truth)

| Sub-case | Name                    | Target effect | Receipt | Expected client outcome |
|----------|-------------------------|---------------|---------|-------------------------|
| S1a      | request lost            | 0             | 0       | HOLD                    |
| S1b      | response lost           | 1             | 0       | HOLD                    |
| S1c      | rejection response lost | 0             | 0       | HOLD                    |

**Post-reconciliation** (separate test, not part of S1)
- T7 (resolved non-execution) → new attempt authorized, same LEI
- T8 (resolved execution)     → COMMITTED, history preserved

**Out of scope for S1**
- what the reconciliation mechanism is
- how T7/T8 are triggered
- multi-LEI idempotency

**Evidence required**
- raw JSONL transition log
- effect_sink snapshot (count + entries)
- permit log (issued / consumed / rejected)
- fake clock timestamps
- SHA-256 of the scenario definition file

**Epistemic boundary**  
Passing tests against a harness only establish that the harness satisfies these assertions.  
They do **not** validate a production gateway, a real transport, or the REG/TENIR protocol itself until the harness is adapted to call the actual subject under test.
