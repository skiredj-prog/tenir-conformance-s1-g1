#!/usr/bin/env python3
"""E1 - exhaustive fault-sequence comparison on one logical operation.

Fault alphabet for a single dispatch (one attempt):
  F0 success (effect applied, acknowledgement delivered)
  F1 request lost before the target (no effect, no response)          [S1a]
  F2 effect applied, acknowledgement lost                              [S1b]
  F3 target rejects, rejection response lost (no effect, no response)  [S1c]
  F4 target rejects, rejection observed by the client (explicit)

Client policy ("naive retrier"): retry after a NO-RESPONSE outcome (F1,F2,F3),
at most 3 attempts in total; stop on explicit success (F0) or explicit
rejection (F4). All fault sequences consistent with this policy are enumerated
(53 sequences). This is an exhaustive enumeration, not a probability estimate.

Systems under test
  B1  stateless PEP/PDP: kernel decision, then dispatch. No post-admission state.
  B2  B1 + target-side idempotency key; client REUSES the key on retry.
  M0  RFC-4 lab membrane, no reconciliation path used.
  M1  RFC-4 lab membrane + evidence-bound reconciliation (truthful upstream
      attestations) between a no-response outcome and the next retry.
"""
from __future__ import annotations

import itertools
import json
from collections import Counter

from tenir_conformance.membrane import AttemptState, Evidence, FakeClock, Membrane, Receipt
from tenir_conformance.membrane.kernel_bridge import KernelBridge

OK = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}
FAULTS = ["F0", "F1", "F2", "F3", "F4"]
NO_RESPONSE = {"F1", "F2", "F3"}
MAX_ATTEMPTS = 3
T0, TAU = 1_000_000, 5_000
BRIDGE = KernelBridge()


def sequences():
    out = []
    def rec(prefix):
        if prefix and (prefix[-1] not in NO_RESPONSE or len(prefix) == MAX_ATTEMPTS):
            out.append(tuple(prefix)); return
        for f in FAULTS:
            rec(prefix + [f])
    rec([])
    return out


EFFECT = {"F0": 1, "F1": 0, "F2": 1, "F3": 0, "F4": 0}


# ----------------------------------------------------------------- baselines
def run_b1(seq):
    effects, confirmed = 0, False
    nonexecution_confirmed, prior_unresolved = False, False
    for f in seq:
        assert BRIDGE.evaluate(OK).admissible
        effects += EFFECT[f]
        if f in NO_RESPONSE:
            prior_unresolved = True
        if f == "F0":
            confirmed = True
            nonexecution_confirmed = False
        elif f == "F4":
            # A rejection settles the logical operation only if no earlier
            # no-response attempt remains epistemically unresolved.
            nonexecution_confirmed = not prior_unresolved
    return dict(effects=effects, confirmed=confirmed,
                nonexecution_confirmed=nonexecution_confirmed, blocked=0)


def run_b2(seq):
    effects, confirmed, applied = 0, False, False
    nonexecution_confirmed, prior_unresolved = False, False
    for f in seq:
        assert BRIDGE.evaluate(OK).admissible
        if EFFECT[f] and not applied:
            applied = True; effects += 1          # same key => target dedups later effects
        if f in NO_RESPONSE:
            prior_unresolved = True
        if f == "F0":
            confirmed = True
            nonexecution_confirmed = False
        elif f == "F4":
            nonexecution_confirmed = not prior_unresolved
    return dict(effects=effects, confirmed=confirmed,
                nonexecution_confirmed=nonexecution_confirmed, blocked=0)


# ----------------------------------------------------------------- membrane
def _ev(aid, nonce, status, nonexec):
    return Evidence(evidence_id=f"E-{aid}-{status}", attempt_id=aid, lei="L", nonce=nonce,
                    status=status, properties={}, reference_scope="op:L",
                    reference_snapshot="snap:1", normalization_profile="np-1",
                    integrity_verified=True, source_authoritative=True,
                    expires_at_ms=T0 + 10**9, non_execution_confirmed=nonexec)


def run_membrane(seq, reconcile):
    clock = FakeClock(now_ms=T0)
    m = Membrane(BRIDGE, clock=clock, tau_k_ms=TAU)
    confirmed, blocked = False, 0
    nonexecution_confirmed, prior_unresolved = False, False
    for i, f in enumerate(seq):
        aid, nonce = f"A{i+1}", f"n{i+1}"
        n_attempts = len(m.attempts)
        if f == "F4":
            r = m.process_transaction(lei="L", attempt_id=aid, payload=OK, nonce=nonce, target_rejected=True)
        else:
            r = m.admit_and_await_qualification(
                lei="L", attempt_id=aid, payload=OK, apply_effect=bool(EFFECT[f]), nonce=nonce)
        if len(m.attempts) == n_attempts:               # admission refused by the membrane guard
            blocked += 1
            continue                                     # uniform client policy: retry HOLD up to MAX_ATTEMPTS
        if f == "F0":
            r = m.deliver_qualifying_receipt(Receipt(attempt_id=aid, lei="L", nonce=nonce))
            confirmed = r.client_state == AttemptState.RESOLVED.value
            nonexecution_confirmed = False
            break
        if f == "F4":
            # An observed rejection only establishes operation-level
            # non-execution if all preceding attempts were already settled.
            nonexecution_confirmed = not prior_unresolved
            break
        # no-response outcome: the qualification window elapses
        clock.advance_to(clock.now_ms + TAU)
        m.check_qualification_timeouts()
        if reconcile:
            truth_effect = bool(EFFECT[f])
            m.reconcile(attempt_id=aid, evidence=_ev(aid, nonce, "COMMITTED" if truth_effect else "FAILED",
                                                     nonexec=not truth_effect))
            if m.attempts[aid].state == AttemptState.RESOLVED:
                confirmed = True
                nonexecution_confirmed = False
                break
            if m.attempts[aid].state == AttemptState.FAILED:
                # Qualified reconciliation has established non-execution for
                # this attempt and all earlier attempts admitted by the guard.
                nonexecution_confirmed = True
                prior_unresolved = False
        else:
            prior_unresolved = True
            nonexecution_confirmed = False
        # client retries with a fresh attempt id on the next loop iteration
    # Record both per-attempt blocks and sequences containing any block.
    return dict(effects=len(m.sink.effects), confirmed=confirmed,
                nonexecution_confirmed=nonexecution_confirmed, blocked=blocked)


def summarize(name, fn):
    res = [fn(s) for s in SEQS]
    c = Counter()
    for r in res:
        c["dup" if r["effects"] >= 2 else ("once" if r["effects"] == 1 else "zero")] += 1
        c["client_confirmed"] += r["confirmed"]
        c["blocked_seq"] += r["blocked"] > 0

    # The sequence-level denominator is defined from the fault trace, not
    # from a system's output: 15 no-effect traces and 38 effect-expected traces.
    no_effect_expected = sum(all(f in {"F1", "F3", "F4"} for f in seq) for seq in SEQS)
    effect_expected = sum(any(EFFECT[f] for f in seq) for seq in SEQS)
    correct_no_effect = sum(
        1 for seq, r in zip(SEQS, res)
        if all(f in {"F1", "F3", "F4"} for f in seq)
        and r["effects"] == 0 and r["nonexecution_confirmed"]
    )
    correct_single_effect = sum(
        1 for seq, r in zip(SEQS, res)
        if any(EFFECT[f] for f in seq)
        and r["effects"] == 1 and r["confirmed"]
    )
    once_unconfirmed = sum(1 for r in res if r["effects"] == 1 and not r["confirmed"])
    return {
        "system": name,
        "sequences": len(res),
        "duplicate_effects": c["dup"],
        "exactly_one_effect": c["once"],
        "zero_effects": c["zero"],
        "client_confirmed_success": c["client_confirmed"],
        "exactly_one_effect_but_client_unaware": once_unconfirmed,
        "correct_no_effect_sequences": correct_no_effect,
        "no_effect_expected_sequences": no_effect_expected,
        "correct_no_effect_rate_percent": round(100 * correct_no_effect / no_effect_expected, 2),
        "correct_single_effect_sequences": correct_single_effect,
        "effect_expected_sequences": effect_expected,
        "correct_single_effect_rate_percent": round(100 * correct_single_effect / effect_expected, 2),
        "blocked_retry_attempts": sum(r["blocked"] for r in res),
        "sequences_with_at_least_one_block": c["blocked_seq"],
    }


SEQS = sequences()
assert len(SEQS) == 53, f"Expected 53 fault sequences, got {len(SEQS)}"
assert sum(all(f in {"F1", "F3", "F4"} for f in seq) for seq in SEQS) == 15
assert sum(any(EFFECT[f] for f in seq) for seq in SEQS) == 38

if __name__ == "__main__":
    out = [summarize("B1 stateless PEP/PDP", run_b1),
           summarize("B2 PEP/PDP + idempotency key (reused)", run_b2),
           summarize("M0 membrane, no reconciliation", lambda s: run_membrane(s, False)),
           summarize("M1 membrane + evidence-bound reconciliation", lambda s: run_membrane(s, True))]
    print(json.dumps(out, indent=2))
    # which sequences produce duplicates in B1
    dups = [list(s) for s in SEQS if run_b1(s)["effects"] >= 2]
    print("B1 duplicate sequences:", len(dups), dups[:6])
    print("M0/M1 any duplicate:", any(run_membrane(s, r)["effects"] >= 2 for s in SEQS for r in (False, True)))
