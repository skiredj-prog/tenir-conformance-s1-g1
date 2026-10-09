#!/usr/bin/env python3
"""Compatibility runner for the historical E2 baseline semantics.

Uses the current real-Membrane event model, but restores the historical
lossy state projection and catch-all exception policy. This is for baseline
reproduction only; strict-key analysis remains in e2_explore.py.
"""
from __future__ import annotations
import argparse
import dataclasses
import json
from pathlib import Path
import e2_explore as explorer

def legacy_key(m, w):
    at = tuple(sorted((i, tuple(sorted((k, str(v)) for k, v in dataclasses.asdict(a).items())))
                      for i, a in m.attempts.items()))
    pm = tuple(sorted((i, tuple(sorted((k, str(v)) for k, v in dataclasses.asdict(p).items())))
                      for i, p in m.permits.items()))
    q = tuple(sorted((l, str(sorted(v.get("evidence_ids", []))))
                     for l, v in m.governance_quarantine.items()))
    ef = tuple(sorted(e["attempt_id"] for e in m.sink.effects))
    reg = tuple(sorted(m._evidence_registry))
    return (at, pm, q, ef, tuple(sorted(w.effects.items())), w.advances,
            m.clock.now_ms, reg, len(m.governance_quarantine_history))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--depth", type=int, default=6)
    p.add_argument("--world", choices=["honest", "false_attest", "hidden_honest", "adversarial"], default="honest")
    p.add_argument("--out")
    a = p.parse_args()
    explorer.key = legacy_key
    explorer.is_expected_rejection = lambda exc, label, m: True
    result = explorer.explore(a.depth, a.world)
    # The historical baseline did not include the strict runner's rejection histogram.
    result.pop("expected_rejections", None)
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if a.out:
        Path(a.out).write_text(rendered, encoding="utf-8")

if __name__ == "__main__":
    main()
