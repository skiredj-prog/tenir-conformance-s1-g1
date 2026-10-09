#!/usr/bin/env python3
"""E2 - bounded exhaustive exploration of the RFC-4 lab membrane.

Explicit-state breadth-first search over the PUBLIC API of
tenir_conformance.membrane.Membrane for ONE logical operation (LEI "L") and up
to two attempt identifiers. After every step the safety invariants below are
checked on the concrete membrane state (not on an abstraction of it).

World model (two modes, selected with --world):
  honest        O and A hold (observation sound, attestations sound).
  false_attest  O holds, A violated: attestations may be asserted TRUE regardless of truth.
  hidden_honest O violated, A holds: a dispatch may produce an external effect the
                membrane does not observe (apply_effect=False, world effect occurs).
  adversarial   O and A both violated.

Usage: python e2_explore.py --depth 6 --world honest
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from collections import deque

from tenir_conformance.membrane import (
    AttemptState, Evidence, FakeClock, Membrane, Receipt, StaleReceiptError,
)
from tenir_conformance.membrane.kernel_bridge import KernelBridge

LEI = "L"
IDS = ("A1", "A2")
NONCE = {"A1": "nA1", "A2": "nA2"}


def nonce_for(attempt_id: str, action: str) -> str:
    """Stable caller-supplied nonce for each E2 attempt/action transition."""
    return f"e2-{attempt_id}-{action}"
OK = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}
VETO = {"P": 10.0, "V": 10.0, "K": 0.1, "option_space": 1.0}
T0 = 1_000_000
TAU = 5_000
MAX_ADVANCES = 2


def ev(eid, status, aid, *, nonexec=False, props=None, nonce=None, ttl=60_000_000):
    return Evidence(
        evidence_id=eid, attempt_id=aid, lei=LEI, nonce=nonce or NONCE[aid],
        status=status, properties=props or {}, reference_scope="op:L",
        reference_snapshot="snap:1", normalization_profile="np-1",
        integrity_verified=True, source_authoritative=True,
        expires_at_ms=T0 + ttl, non_execution_confirmed=nonexec,
    )


class World:
    """Ground truth kept OUTSIDE the membrane."""
    def __init__(self):
        self.effects = {a: 0 for a in IDS}          # real external effects per attempt
        self.advances = 0

    def total(self):
        return sum(self.effects.values())


def build_events(world_mode):
    """Return list of (label, fn(m, w) -> dispatch_flag). Exceptions = guard rejections."""
    E = []
    # 2x2 assumption matrix: O = membrane observes every effect it dispatches,
    # A = upstream non-execution attestations are sound.
    hidden = world_mode in ("adversarial", "hidden_honest")       # O violated
    false_att = world_mode in ("adversarial", "false_attest")     # A violated

    for a in IDS:
        # --- dispatch-class events (may create an effect) ---
        for label, kw, eff in [
            ("ok", {}, 1),
            ("request_lost", {"request_lost": True}, 0),
            ("receipt_lost", {"receipt_lost": True}, 1),
            ("target_rejected_seen", {"target_rejected": True}, 0),
            ("target_rejected_lost", {"target_rejected": True, "receipt_lost": True}, 0),
        ]:
            def f(m, w, a=a, kw=kw, eff=eff):
                n0 = len(m.sink.effects)
                m.process_transaction(lei=LEI, attempt_id=a, payload=OK, nonce=nonce_for(a, label), **kw)
                if len(m.sink.effects) > n0:
                    w.effects[a] += 1
                return True
            E.append((f"process({a},{label})", f))

        def fveto(m, w, a=a):
            m.process_transaction(lei=LEI, attempt_id=a, payload=VETO, nonce=nonce_for(a, "kernel_veto"))
            return True
        E.append((f"process({a},kernel_veto)", fveto))

        for apply_eff in (True, False):
            def f(m, w, a=a, apply_eff=apply_eff):
                n0 = len(m.sink.effects)
                m.admit_and_await_qualification(
                    lei=LEI, attempt_id=a, payload=OK, apply_effect=apply_eff, nonce=NONCE[a])
                if len(m.sink.effects) > n0:
                    w.effects[a] += 1
                return True
            E.append((f"admit_await({a},effect={apply_eff})", f))
        if hidden:
            # dispatch whose external effect is invisible to the membrane
            def f(m, w, a=a):
                n0 = len(m.attempts)
                m.admit_and_await_qualification(
                    lei=LEI, attempt_id=a, payload=OK, apply_effect=False, nonce=NONCE[a])
                if len(m.attempts) > n0 and m.permits[a].consumed:
                    w.effects[a] += 1       # world applied it, membrane did not observe it
                return True
            E.append((f"admit_await({a},HIDDEN_effect)", f))

        def fretry(m, w, a=a):
            n0 = len(m.sink.effects)
            m.retry(lei=LEI, attempt_id=a, payload=OK, nonce=nonce_for(a, "retry"))
            if len(m.sink.effects) > n0:
                w.effects[a] += 1
            return True
        E.append((f"retry({a})", fretry))

        # --- non-dispatch events ---
        E.append((f"receipt({a},valid)", lambda m, w, a=a: m.deliver_qualifying_receipt(
            Receipt(attempt_id=a, lei=LEI, nonce=NONCE[a], expires_at_ms=None)) and False))
        E.append((f"receipt({a},expired_token)", lambda m, w, a=a: m.deliver_qualifying_receipt(
            Receipt(attempt_id=a, lei=LEI, nonce=NONCE[a], expires_at_ms=m.clock.now_ms)) and False))
        E.append((f"receipt({a},wrong_nonce)", lambda m, w, a=a: m.deliver_qualifying_receipt(
            Receipt(attempt_id=a, lei=LEI, nonce="BAD", expires_at_ms=None)) and False))

        for q in (True, False):
            def f(m, w, a=a, q=q):
                if q and not false_att and w.effects[a] > 0:
                    return False                      # honest world: no false attestation
                m.declare_failed(attempt_id=a, evidence_qualified=q)
                return False
            E.append((f"declare_failed({a},qualified={q})", f))

        for label, status, nonexec in [("COMMITTED", "COMMITTED", False),
                                       ("FAILED+nonexec", "FAILED", True),
                                       ("FAILED-noproof", "FAILED", False)]:
            def f(m, w, a=a, status=status, nonexec=nonexec, label=label):
                if nonexec and not false_att and w.effects[a] > 0:
                    return False
                if status == "COMMITTED" and not false_att and w.effects[a] == 0:
                    return False                      # honest world: no false COMMITTED either
                m.reconcile(attempt_id=a, evidence=ev(f"R-{a}-{label}", status, a, nonexec=nonexec))
                return False
            E.append((f"reconcile({a},{label})", f))

        def fcontra(m, w, a=a):
            m.evaluate_evidence_batch(attempt_id=a, evidence_batch=[
                ev(f"X1-{a}", "COMMITTED", a), ev(f"X2-{a}", "FAILED", a, nonexec=True)])
            return False
        E.append((f"evidence_batch({a},contradictory)", fcontra))

    def ftick(m, w):
        w.advances += 1
        m.clock.advance_to(m.clock.now_ms + TAU)
        m.check_qualification_timeouts()
        return False
    E.append(("advance(tau_K)", ftick))

    def frelease(m, w):
        if LEI in m.governance_quarantine:
            m.resolve_governance_quarantine(
                lei=LEI, incident_id=m.governance_quarantine[LEI]["incident_id"],
                authorized_by="risk-owner", rationale="test")
        return False
    E.append(("release_quarantine", frelease))
    return E


# ----------------------------------------------------------------- state key
def key(m: Membrane, w: World):
    """Full concrete key: every Attempt/Permit field, clock, quarantine, sink, registry, world."""
    import dataclasses
    at = tuple(sorted((i, tuple(sorted((k, str(v)) for k, v in dataclasses.asdict(a).items())))
                      for i, a in m.attempts.items()))
    pm = tuple(sorted((i, tuple(sorted((k, str(v)) for k, v in dataclasses.asdict(p).items())))
                      for i, p in m.permits.items()))
    q = tuple(sorted((l, str(sorted(v.get("evidence_ids", [])))) for l, v in m.governance_quarantine.items()))
    ef = tuple(sorted(e["attempt_id"] for e in m.sink.effects))
    reg = tuple(sorted(m._evidence_registry))
    return (at, pm, q, ef, tuple(sorted(w.effects.items())), w.advances, m.clock.now_ms, reg,
            len(m.governance_quarantine_history))


# ----------------------------------------------------------------- invariants
def snapshot(m: Membrane, w: World):
    return {
        "states": {i: a.state for i, a in m.attempts.items()},
        "effect_obs": {i: a.effect_observed for i, a in m.attempts.items()},
        "consumed": {i: p.consumed for i, p in m.permits.items()},
        "n_attempts": len(m.attempts),
        "sink": len(m.sink.effects),
        "quarantine": set(m.governance_quarantine),
        "consumed_events": sum(1 for e in m.events if e["event"] == "PERMIT_CONSUMED"),
    }


def check(label, dispatch, m, w, before):
    """Return list of (invariant_id, description) violations."""
    after = snapshot(m, w)
    v = []
    # I1 effect-at-most-once per logical operation (ground truth)
    if w.total() > 1:
        v.append(("I1", f"world effects for LEI = {w.total()} (>1)"))
    # I2 permit single-use: consumption is monotone, once per attempt
    for i, c in before["consumed"].items():
        if c and not after["consumed"].get(i, False):
            v.append(("I2", f"permit {i} un-consumed"))
    ids_consumed = [e["attempt_id"] for e in m.events if e["event"] == "PERMIT_CONSUMED"]
    if len(ids_consumed) != len(set(ids_consumed)):
        v.append(("I2", "permit consumed twice for one attempt (within step)"))
    for i in ids_consumed:
        if before["consumed"].get(i, False):
            v.append(("I2", f"permit {i} consumed again after prior consumption"))
    # I3 terminal immutability: RESOLVED / FAILED never change
    for i, s in before["states"].items():
        if s in (AttemptState.RESOLVED, AttemptState.FAILED) and after["states"][i] != s:
            v.append(("I3", f"terminal {s.value} of {i} became {after['states'][i].value}"))
    # I4 only dispatch-class events may grow the sink
    if after["sink"] > before["sink"] and not dispatch:
        v.append(("I4", "non-dispatch event appended an effect"))
    if after["sink"] < before["sink"]:
        v.append(("I4", "effect removed from sink"))
    # I5 FAILED implies no observed effect
    for i, a in m.attempts.items():
        if a.state == AttemptState.FAILED and a.effect_observed:
            v.append(("I5", f"{i} FAILED with effect_observed"))
    # I6 no new attempt admitted under quarantine
    if after["n_attempts"] > before["n_attempts"] and (before["quarantine"] & {LEI}):
        v.append(("I6", "attempt admitted under quarantine"))
    # I7 admission only when every earlier attempt is FAILED without effect
    if after["n_attempts"] > before["n_attempts"]:
        for i, s in before["states"].items():
            if not (s == AttemptState.FAILED and not before["effect_obs"][i]):
                v.append(("I7", f"new attempt admitted while {i} was {s.value}"))
    # I8 attempt ids are never reused / never dropped
    if after["n_attempts"] < before["n_attempts"]:
        v.append(("I8", "attempt record dropped"))
    return v


def explore(depth, world_mode, max_states=2_000_000):
    events = build_events(world_mode)
    bridge = KernelBridge()
    def fresh():
        m = Membrane(bridge, clock=FakeClock(now_ms=T0), tau_k_ms=TAU,
                     conflict_sensitive_properties={"exposure"},
                     quarantine_release_authorizer=lambda p, l: True)
        return m, World()

    m0, w0 = fresh()
    root_key = key(m0, w0)
    seen = {hash(root_key): 0}
    # Depth-1 inventory is diagnostic evidence: preserve the first transition
    # reaching each distinct state and the complete concrete state key.
    state_inventory = [{"depth": 0, "state_hash": hash(root_key),
                        "via": "ROOT", "state_key": root_key}] if depth == 1 else None
    q = deque([(m0, w0, ())])
    viol = {}
    first_trace = {}
    transitions = 0
    t0 = time.time()
    frontier_by_depth = {0: 1}
    while q:
        m, w, trace = q.popleft()
        if len(trace) >= depth:
            continue
        for label, fn in events:
            if label.startswith("advance") and w.advances >= MAX_ADVANCES:
                continue
            m2 = copy.deepcopy(m, memo={id(bridge): bridge})
            m2.events = []
            w2 = copy.deepcopy(w)
            before = snapshot(m2, w2)
            try:
                dispatch = fn(m2, w2)
            except ValueError as exc:
                message = str(exc)
                if "NONCE_REQUIRED" in message or "TRANSITION_OBJECT_REQUIRED" in message:
                    raise
                # Other ValueErrors represent expected business guards/rejections.
                dispatch = label.startswith(("process", "admit", "retry"))  # state may mutate before raising
            except StaleReceiptError:
                # Expired receipt is an explicit domain-level rejection. The
                # membrane may have moved the attempt to UNKNOWN before raising;
                # keep that concrete state and continue checking invariants.
                dispatch = False
            except KeyError:
                # Evidence events before their attempt exists are expected rejected
                # moves in this exhaustive event alphabet. Keep the allowlist narrow.
                if not (label.startswith(("receipt(", "declare_failed(", "reconcile(", "evidence_batch("))):
                    raise
                dispatch = False
            except Exception:
                # Unexpected implementation errors must not be treated as rejected moves.
                raise
            transitions += 1
            for inv, msg in check(label, dispatch, m2, w2, before):
                viol.setdefault(inv, 0)
                viol[inv] += 1
                tr = trace + (label,)
                if inv not in first_trace or len(tr) < len(first_trace[inv][0]):
                    first_trace[inv] = (tr, msg)
            k = hash(key(m2, w2))
            if transitions % 50000 == 0:
                print(f"[{time.time()-t0:.0f}s] states={len(seen)} transitions={transitions} queue={len(q)}", file=sys.stderr, flush=True)
            if k not in seen:
                seen[k] = len(trace) + 1
                frontier_by_depth[len(trace) + 1] = frontier_by_depth.get(len(trace) + 1, 0) + 1
                q.append((m2, w2, trace + (label,)))
                if state_inventory is not None and len(trace) == 0:
                    state_inventory.append({"depth": 1, "state_hash": k,
                                            "via": label, "state_key": key(m2, w2)})
                if len(seen) >= max_states:
                    print("state cap hit", file=sys.stderr)
                    q.clear()
                    break
    result = {
        "world": world_mode, "depth": depth, "distinct_states": len(seen),
        "transitions_checked": transitions, "new_states_by_depth": frontier_by_depth,
        "violations": viol,
        "shortest_counterexamples": {k: {"trace": list(v[0]), "msg": v[1]} for k, v in first_trace.items()},
        "n_event_types": len(events), "seconds": round(time.time() - t0, 1),
        "invariants": ["I1 effect-at-most-once (ground truth)", "I2 permit single-use",
                       "I3 terminal immutability", "I4 only dispatch appends effects",
                       "I5 FAILED => no observed effect", "I6 no admission under quarantine",
                       "I7 admission only after FAILED-without-effect", "I8 attempt record permanence"],
    }
    if state_inventory is not None:
        result["state_inventory_depth1"] = state_inventory
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--world", choices=["honest", "false_attest", "hidden_honest", "adversarial"], default="honest")
    ap.add_argument("--out")
    a = ap.parse_args()
    r = explore(a.depth, a.world)
    s = json.dumps(r, indent=2)
    print(s)
    if a.out:
        open(a.out, "w").write(s)
