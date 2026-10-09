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
    for f in seq:
        assert BRIDGE.evaluate(OK).admissible
        effects += EFFECT[f]
        if f == "F0":
            confirmed = True
    return dict(effects=effects, confirmed=confirmed, blocked=0)


def run_b2(seq):
    effects, confirmed, applied = 0, False, False
    for f in seq:
        assert BRIDGE.evaluate(OK).admissible
        if EFFECT[f] and not applied:
            applied = True; effects += 1          # same key => target dedups later effects
        if f == "F0":
            confirmed = True
    return dict(effects=effects, confirmed=confirmed, blocked=0)


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
    for i, f in enumerate(seq):
        aid, nonce = f"A{i+1}", f"n{i+1}"
        n_attempts = len(m.attempts)
        if f == "F4":
            r = m.process_transaction(lei="L", attempt_id=aid, payload=OK, target_rejected=True, nonce=nonce)
        else:
            r = m.admit_and_await_qualification(
                lei="L", attempt_id=aid, payload=OK, apply_effect=bool(EFFECT[f]), nonce=nonce)
        if len(m.attempts) == n_attempts:               # admission refused by the membrane guard
            blocked += 1
            break                                        # naive client keeps getting HOLD; stops retrying
        if f == "F0":
            r = m.deliver_qualifying_receipt(Receipt(attempt_id=aid, lei="L", nonce=nonce))
            confirmed = r.client_state == AttemptState.RESOLVED.value
            break
        if f == "F4":
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
                break
        # client retries with a fresh attempt id on the next loop iteration
    # a blocked retry in the membrane is a HOLD, so count attempts the membrane never let through
    return dict(effects=len(m.sink.effects), confirmed=confirmed, blocked=blocked)


def summarize(name, fn):
    res = [fn(s) for s in SEQS]
    c = Counter()
    for r in res:
        c["dup" if r["effects"] >= 2 else ("once" if r["effects"] == 1 else "zero")] += 1
        c["client_confirmed"] += r["confirmed"]
        c["blocked_seq"] += r["blocked"] > 0
    once_unconfirmed = sum(1 for r in res if r["effects"] == 1 and not r["confirmed"])
    return {"system": name, "sequences": len(res), "duplicate_effects": c["dup"],
            "exactly_one_effect": c["once"], "zero_effects": c["zero"],
            "client_confirmed_success": c["client_confirmed"],
            "exactly_one_effect_but_client_unaware": once_unconfirmed,
            "sequences_where_membrane_blocked_a_retry": c["blocked_seq"]}


SEQS = sequences()

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
