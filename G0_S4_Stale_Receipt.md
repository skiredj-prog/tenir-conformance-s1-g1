# Scenario G0 S4 — Stale Receipt & Expired Evidence Interleaving

**Scenario ID:** `G0_S4`  
**Target:** RFC-4 Membrane / attempt registry (`tenir_conformance.membrane.Membrane`)  
**Invariant Goal:** CommitCount(L) ≤ 1 and State(A1) ≠ COMMITTED via stale receipt  
**Normative Invariants:** REG-CORE-012, REG-CORE-018, REG-CORE-031  
**Status:** Locked operational specification (lab harness maps to real membrane API).

---

## 1. Executive Summary & Intent

G0 S4 validates membrane behaviour when a receipt or evidence token arrives **after execution-window closure** or **after its own TTL expiry**.

Sub-cases:

| ID | State | Window | Token | Expected |
|----|-------|--------|-------|----------|
| **S4a** | UNKNOWN | CLOSED | cryptographically valid / bound | HOLD / RECEIPT_REJECTED |
| **S4b** | AWAITING_QUALIFICATION (IN_FLIGHT) | OPEN | expired | `StaleReceiptError` |

**Critical couple:** `State = UNKNOWN` **and** `ExecutionWindow = CLOSED` is never an implicit permission to proceed.

**Boundary with S6:** S4 tests receipt delivery and must reject a receipt after the execution window closes. S6 uses a separate `reconcile` observation API to inspect qualified evidence about an already-past outcome. Reconciliation must not call `deliver_qualifying_receipt`, reopen the S4 window, issue a permit, or cause an effect. The two paths are tested and reported as distinct scenarios.

### Vocabulary mapping (spec → membrane)

| Spec term | Membrane primitive |
|-----------|-------------------|
| IN_FLIGHT / window OPEN | `AttemptState.AWAITING_QUALIFICATION` |
| UNKNOWN + window CLOSED | `timeout_fired` + `AttemptState.UNKNOWN` after `check_qualification_timeouts` |
| COMMITTED | `AttemptState.RESOLVED` + `qualified=True` |
| process_receipt | `deliver_qualifying_receipt(Receipt(...))` |

---

## 2. Sequence Interleavings

### S4a — Window Closed (`UNKNOWN` + `CLOSED`)

1. Submit A1 → AWAITING_QUALIFICATION (window OPEN).  
2. Advance clock past τ_K → UNKNOWN, `timeout_fired=true` (window CLOSED).  
3. Present late bound Receipt → RECEIPT_REJECTED / WINDOW_CLOSED; client HOLD; no RESOLVED; Δ effect = 0.

### S4b — Expired Token on Active Attempt (window OPEN)

1. Submit A1 → AWAITING_QUALIFICATION.  
2. Process Receipt with `expires_at_ms <= now` → STALE_RECEIPT → `StaleReceiptError`; not RESOLVED; Δ effect = 0.

---

## 3. Required Guard Hierarchy

On `deliver_qualifying_receipt(...)`, evaluation order:

1. **Attempt / receipt binding (mandatory)** — a `Receipt` object is required for qualification; `receipt.attempt_id == attempt.attempt_id` ∧ `receipt.lei == attempt.lei` ∧ `receipt.nonce == attempt.nonce` (nonce must be registered at admit; empty nonce → reject). Legacy kwargs MUST NOT transition to RESOLVED.  
2. **Terminal / window closure** — state not FAILED/RESOLVED; window OPEN (not `timeout_fired` / UNKNOWN post-τ_K).  
3. **Token freshness** — `expires_at_ms` absent or `now < expires_at_ms`.  
4. **State transition** — only then may transition toward RESOLVED.  
5. **Permit** — no new execution permit for a rejected/stale path.  
6. **EffectSink** — no emission on reject/stale paths.

**Golden rule:**  
IF `execution_window_closed` OR `terminal_locked` OR `token_expired`  
THEN MUST NOT COMMIT ∧ MUST NOT issue a new execution permit for that receipt ∧ MUST NOT emit effect from that receipt path.

---

## 4. Empirical Evidence Requirements (5 artifacts)

PASS requires generation of:

1. **Scenario / spec SHA-256** — of versioned `G0_S4_Stale_Receipt.md` and `scenarios/S4.json`.  
2. **Attempt / LEI state snapshot** — including `timeout_fired`, state, nonce.  
3. **Effect sink snapshot** — Δ count == 0 on reject paths (prefer baseline effect > 0).  
4. **Permit registry** — no new permit for stale path; existing permit not usable to commit via stale receipt.  
5. **JSONL transition log** — canonical reject events (`RECEIPT_REJECTED` / `STALE_RECEIPT`).

---

## 5. Formal Assertions Matrix (A1–A7)

| # | Domain | Assertion | Success criteria |
|---|--------|-----------|------------------|
| **A1** | Client/API | Projection of rejection | HOLD or `StaleReceiptError` |
| **A2** | State safety | Post-rejection state of A1 | FAILED or UNKNOWN, never RESOLVED/COMMITTED |
| **A3** | Effect invariant | Cumulative effect sink delta | Δ EffectSink.count == 0 on reject path (strong: baseline may be > 0) |
| **A4** | Guard decision | Explicit stale/reject trace | `RECEIPT_REJECTED` / `STALE_RECEIPT` (or LATE_RECEIPT alias) |
| **A5** | Permit safety | Execution authorization lock | No new permit; stale path cannot consume a usable permit to commit |
| **A6** | Identity/binding | Attempt/receipt identity | Receipt required; attempt_id/lei/nonce exact match; legacy kwargs cannot RESOLVED |
| **A7** | Empiricism | Scope of claim | Sequential interleavings only — not general concurrent proof |

---

## 6. Scientific Claim Statement

> **Epistemic notice:** Successful execution of G0 S4 empirically validates the specified stale-receipt rejection and time-boundary isolation for the **tested sequential interleavings** of the RFC-4 lab membrane. It does **not** constitute a formal mathematical proof of real-time thread safety under unconstrained async concurrency.
