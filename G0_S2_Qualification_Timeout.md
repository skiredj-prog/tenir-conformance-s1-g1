# G0 — S2: Qualification Timeout

**Status:** Executed against the RFC-4 lab membrane; empirically validated for the tested sequential interleavings. This operational result is not, by itself, normative approval of REG / TENIR.  
**Depends on:** S1 (ACK Loss) membrane behaviour — unresolved LEI lock, client projection `(UNKNOWN, HOLD)`.  
**Locked name:** Qualification Timeout (not “Timeout” alone).

---

## Claim

When a transition has been admitted and a permit consumed, but **no qualifying evidence** (receipt / target confirmation) arrives within the temporal validity bound τ_K, the membrane must:

1. expire the qualification window,
2. keep the attempt unresolved from the client’s point of view,
3. project `(UNKNOWN, HOLD)`,
4. **block** any new attempt on the same LEI until explicit reconciliation (S6) or an approved recovery path.

Qualification timeout is **not** silent success and **not** silent failure. It is a first-class non-terminal governance event.

---

## Path under test

```
REQUEST
  → admit + consume permit (T1 / T2)
  → AWAITING_QUALIFICATION
  → (clock advances past τ_K, no qualifying receipt)
  → QUALIFICATION_TIMEOUT
  → client: UNKNOWN / HOLD
  → retry same LEI → T1_guard_FALSE (unresolved)
```

---

## Given (initial state)

- LEI `L`, attempt `A` admitted; permit for `A` **consumed** (single-use).
- Client has not observed a qualifying receipt for `A`.
- `recon(A) = PENDING` (or equivalent unresolved).
- Fake clock at t_0; τ_K is a fixed positive duration known to the membrane.
- Target ground truth is **out of scope for the client projection** (may be 0 or 1 effect); only membrane-visible state matters for S2 assertions.

---

## When

1. No qualifying receipt is delivered before t_0 + τ_K.
2. The membrane evaluates the qualification window (explicit timeout transition or equivalent guard).
3. The client issues a **retry** with the same LEI `L` and a fresh nonce, **without** reconciliation.

---

## Then (assertions)

1. `exec` / attempt state remains non-terminal from the client view: `UNKNOWN` (or membrane-equivalent “unresolved”).
2. `recon` remains `PENDING` (or “unresolved”) — timeout does **not** auto-reconcile.
3. Client disposition = `HOLD`.
4. Transition log contains a qualification-timeout event (e.g. `T_QualificationTimeout` / `τ_K_EXPIRED`) **before** any retry guard.
5. Retry: `T1_IssuePermit` guard evaluates **FALSE** (`UNRESOLVED_SAME_LEI` or equivalent).
6. No new permit is issued for `L`.
7. `effect_sink.count()` is unchanged by the retry (no second effect caused by the timeout path or the blocked retry).
8. The scalar kernel is **not** required to be re-invoked on the blocked retry (membrane gate).

---

## Sub-cases

| ID  | Name                         | Setup                                                                 | Expected client outcome                                      |
|-----|------------------------------|-----------------------------------------------------------------------|--------------------------------------------------------------|
| S2a | Pure qualification timeout   | No receipt at all before τ_K; clock past τ_K; then retry | HOLD / UNKNOWN; guard FALSE; no new permit; no new effect    |
| S2b | Timeout then late arrival    | Clock past τ_K (timeout fired); **then** a late receipt arrives | Late receipt does **not** auto-commit; stays HOLD/UNKNOWN until explicit qualify/reconcile path (out of scope for S2 success; may be S6) |
| S2c | Bound still open (control)   | Receipt arrives **before** τ_K and is validly bound            | Not a timeout; may follow nominal qualify path — **negative control for S2** (S2 oracle must not fire timeout) |

**S2c** is a **negative control**: the timeout transition must **not** fire if qualification occurs inside τ_K. Full successful qualification/commit is not the claim of S2; it belongs to nominal path / S6.

---

## Out of scope for S2

- What reconciliation *is* (S6 — Successful Reconciliation).
- Contradictory late evidence (S5).
- Stale-but-pre-timeout binding rules beyond “no auto-commit after τ_K” (S4).
- Duplicate concurrent requests (S3).
- Changing τ_K mid-flight policy semantics (may be noted as future vector).

---

## Evidence required

- Scenario definition file + SHA-256.
- Fake-clock timestamps: t_0, τ_K, timeout-fire time, retry time.
- Append-only transition log (JSONL): seed → await → timeout → retry guard.
- Permit log: issued / consumed; no second issue on retry.
- Effect sink snapshot: count unchanged by retry.
- Client projection record: `UNKNOWN` + `HOLD`.
- Optional: kernel call count on retry path (= 0 if membrane-only gate).

---

## Epistemic boundary

Passing tests against the membrane establish that **this membrane** implements the G0 assertions for Qualification Timeout.  
They do **not** by themselves validate a production gateway, a real distributed transport, or the full TENIR stack beyond the isolation membrane under test.

**Observed lab result:** S2 was executed against the RFC-4 lab membrane. The tested cases cover τ_K expiry, the unresolved same-LEI retry guard, and the pre-deadline negative control. This is a sequential-interleaving result, not a production or general concurrency claim.

---

## Relation to locked series

```
S1  ACK Loss
    ↓
S2  Qualification Timeout    ← this G0
    ↓
S3  Duplicate Request
    ↓
S4  Stale Receipt
    ↓
S5  Contradictory Evidence
    ↓
S6  Successful Reconciliation
```

S1–S5 = fault / attack conditions.  
S6 = recovery path without erasing history.
