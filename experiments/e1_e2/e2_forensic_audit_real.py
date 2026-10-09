#!/usr/bin/env python3
"""Compare historical and strict E2 state keys on the real Membrane model."""
from __future__ import annotations
import argparse, copy, json, sys, time
from collections import defaultdict, deque
from pathlib import Path
from e2_explore import (
    FakeClock, KernelBridge, Membrane, T0, TAU, MAX_ADVANCES, World, build_events,
    check, is_expected_rejection, key as strict_key, snapshot,
)

def legacy_projection_key(m, w):
    """Exact legacy projection from the historical e2_explore.py."""
    import dataclasses
    at = tuple(sorted((aid, tuple(sorted((k, str(v)) for k, v in dataclasses.asdict(a).items())))
                      for aid, a in m.attempts.items()))
    pm = tuple(sorted((aid, tuple(sorted((k, str(v)) for k, v in dataclasses.asdict(p).items())))
                      for aid, p in m.permits.items()))
    q = tuple(sorted((lei, str(sorted(v.get("evidence_ids", []))))
                     for lei, v in m.governance_quarantine.items()))
    ef = tuple(sorted(e["attempt_id"] for e in m.sink.effects))
    reg = tuple(sorted(m._evidence_registry))
    return (at, pm, q, ef, tuple(sorted(w.effects.items())), w.advances,
            m.clock.now_ms, reg, len(m.governance_quarantine_history))

def fresh():
    bridge = KernelBridge()
    membrane = Membrane(bridge, clock=FakeClock(now_ms=T0), tau_k_ms=TAU,
        conflict_sensitive_properties={"exposure"},
        quarantine_release_authorizer=lambda principal, lei: True)
    return membrane, World(), bridge

def explore(mode, world_mode, depth, max_states):
    started = time.time()
    m0, w0, bridge = fresh()
    events = build_events(world_mode)
    key_fn = (lambda m, w: hash(legacy_projection_key(m, w))) if mode == "LEGACY" else strict_key
    first_id = key_fn(m0, w0)
    seen = {first_id}
    queue = deque([(m0, w0, ())])
    metrics = {"mode": mode, "world": world_mode, "depth_limit": depth,
        "states_visited": 0, "transitions_attempted": 0, "transitions_accepted": 0,
        "transitions_rejected_expected": 0, "transitions_same_key_id": 0,
        "i1_violation_occurrences": 0, "minimal_i1_depth": None,
        "minimal_i1_trace_signatures": [], "state_cap_hit": False}
    hash_to_projections = defaultdict(set)
    collision_hashes, collision_encounters = set(), 0
    if mode == "LEGACY":
        hash_to_projections[first_id].add(legacy_projection_key(m0, w0))
    first_strict_key, fused_groups = {}, defaultdict(set)
    strict_projection_states = 0

    while queue:
        m, w, trace = queue.popleft()
        metrics["states_visited"] += 1
        if mode == "STRICT":
            strict_projection_states += 1
            old = legacy_projection_key(m, w)
            sk = strict_key(m, w)
            if old not in first_strict_key:
                first_strict_key[old] = sk
            elif first_strict_key[old] != sk:
                fused_groups[old].update((first_strict_key[old], sk))
        if len(trace) >= depth:
            continue

        for label, fn in events:
            if label.startswith("advance") and w.advances >= MAX_ADVANCES:
                continue
            metrics["transitions_attempted"] += 1
            m2 = copy.deepcopy(m, memo={id(bridge): bridge})
            m2.events = []
            w2 = copy.deepcopy(w)
            before = snapshot(m2, w2)
            before_id = key_fn(m2, w2)
            rejected = False
            try:
                dispatch = fn(m2, w2)
            except Exception as exc:
                dispatch = label.startswith(("process", "admit", "retry"))
                if is_expected_rejection(exc, label, m2):
                    rejected = True
                    metrics["transitions_rejected_expected"] += 1
                else:
                    print(f"Unexpected exception {mode} / {label}: {type(exc).__name__}: {exc}",
                          file=sys.stderr)
                    print("Trace: " + " -> ".join(trace + (label,)), file=sys.stderr)
                    raise
            if not rejected:
                metrics["transitions_accepted"] += 1
            for inv, _msg in check(label, dispatch, m2, w2, before):
                if inv != "I1":
                    continue
                metrics["i1_violation_occurrences"] += 1
                tr = trace + (label,)
                d, best = len(tr), metrics["minimal_i1_depth"]
                if best is None or d < best:
                    metrics["minimal_i1_depth"] = d
                    metrics["minimal_i1_trace_signatures"] = [tr]
                elif d == best:
                    metrics["minimal_i1_trace_signatures"].append(tr)

            if mode == "LEGACY":
                proj = legacy_projection_key(m2, w2)
                sid = hash(proj)
                prior = hash_to_projections[sid]
                if prior and proj not in prior:
                    collision_hashes.add(sid)
                    collision_encounters += 1
                prior.add(proj)
            else:
                sid = strict_key(m2, w2)
            if sid == before_id:
                metrics["transitions_same_key_id"] += 1
            if sid not in seen:
                seen.add(sid)
                queue.append((m2, w2, trace + (label,)))
                if len(seen) >= max_states:
                    metrics["state_cap_hit"] = True
                    queue.clear()
                    break

    metrics["minimal_i1_trace_signatures"] = sorted(set(
        tuple(t) for t in metrics["minimal_i1_trace_signatures"]))
    metrics["distinct_minimal_i1_traces"] = len(metrics["minimal_i1_trace_signatures"])
    metrics["native_collision_hash_values"] = len(collision_hashes)
    metrics["native_collision_encounters"] = collision_encounters
    metrics["seconds"] = round(time.time() - started, 2)
    if mode == "STRICT":
        metrics["strict_states_projection_audit_count"] = strict_projection_states
        metrics["semantic_fusion_groups"] = len(fused_groups)
        metrics["strict_states_in_fusion_groups"] = sum(len(v) for v in fused_groups.values())
        metrics["semantic_fusion_examples"] = [
            {"legacy_projection": repr(k)[:400], "distinct_strict_keys": len(v)}
            for k, v in list(fused_groups.items())[:10]]
    return metrics

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--depth", type=int, default=6)
    p.add_argument("--world", choices=["honest","false_attest","hidden_honest","adversarial"],
                   default="adversarial")
    p.add_argument("--max-states", type=int, default=2_000_000)
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    legacy = explore("LEGACY", a.world, a.depth, a.max_states)
    strict = explore("STRICT", a.world, a.depth, a.max_states)
    result = {
        "protocol": "E2 forensic key comparison",
        "transition_policy": "same expected-rejection classification in both modes; key strategy isolated",
        "legacy": legacy, "strict": strict,
        "delta_strict_minus_legacy": {k: strict[k]-legacy[k] for k in (
            "states_visited","transitions_attempted","transitions_accepted",
            "transitions_rejected_expected","transitions_same_key_id","i1_violation_occurrences")},
        "minimal_i1_trace_comparison": {
            "legacy_depth": legacy["minimal_i1_depth"], "strict_depth": strict["minimal_i1_depth"],
            "shared_signatures": len(set(map(tuple, legacy["minimal_i1_trace_signatures"])) &
                                      set(map(tuple, strict["minimal_i1_trace_signatures"]))),
            "legacy_signatures": legacy["distinct_minimal_i1_traces"],
            "strict_signatures": strict["distinct_minimal_i1_traces"]},
        "limitations": [
            "No observed native collision is bounded evidence, not proof that hash() never collides.",
            "Semantic fusion group count is not assumed to equal states pruned.",
            "This isolates key strategy under common rejection handling; it is not a byte-for-byte replay of the old catch-all exception loop.",
            "No JSON baseline or MANIFEST is changed."]}
    out = json.dumps(result, indent=2, default=repr)
    print(out)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(out + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
