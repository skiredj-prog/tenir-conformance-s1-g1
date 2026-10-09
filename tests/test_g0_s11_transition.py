"""G0 S11 — governed Transition object conformance."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tenir_conformance.membrane import Disposition, Membrane, Transition, canonical_hash, payload_sha256
from tenir_conformance.membrane.kernel_bridge import KernelDecision

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "scenarios" / "G0_S11_TRANSITION_OBJECT.md"
ARTIFACTS = ROOT / "artifacts" / "s11"
PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}


class CountingBridge:
    def __init__(self, admissible=True):
        self.calls = 0
        self.admissible = admissible

    def evaluate(self, payload):
        self.calls += 1
        return KernelDecision(self.admissible, 2.0,
                              "allow" if self.admissible else "block", "S11 test bridge")


def make_transition(*, source="A", target="B", payload=PAYLOAD, scope=None,
                    postconditions=("effect-applied",), evidence_refs=("ev-1",),
                    tau_id="TAU-DEFAULT-TEST"):
    return Transition(
        tau_id=tau_id, source_realm=source, target_realm=target,
        action_class="default", principal="default",
        scope={"lei": "LEI-1", **(scope or {})},
        payload_digest=payload_sha256(payload), evidence_refs=evidence_refs,
        source_preconditions=("source-valid",), target_postconditions=postconditions,
        declared_at="2026-10-09T10:00:00Z",
    )


def record(case, expected, actual, *, kernel_calls, transition=None, details=None):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    body = {
        "scenario_id": "G0_S11", "subcase": case,
        "spec_sha256": hashlib.sha256(SPEC.read_bytes()).hexdigest(),
        "expected": expected, "actual": actual, "kernel_calls": kernel_calls,
        "transition_hash": canonical_hash(transition) if transition is not None else None,
        "claim_scope": "deterministic unit conformance; in-process membrane harness",
        "details": details or {},
    }
    (ARTIFACTS / f"evidence_{case}.json").write_text(
        json.dumps(body, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def invoke(transition, *, bridge=None, payload=PAYLOAD, **kwargs):
    bridge = bridge or CountingBridge()
    membrane = Membrane(bridge)
    result = membrane.process_transaction(
        lei="LEI-1", attempt_id="S11-A1", transition=transition,
        payload=payload, nonce="n1", **kwargs
    )
    return result, bridge, membrane


def test_s11a_valid_transition_calls_kernel_once_and_passes():
    transition = make_transition()
    result, bridge, _ = invoke(transition)
    assert result.disposition == Disposition.PASS
    assert bridge.calls == 1 and result.effect_count == 1
    record("S11a", "PASS; kernel_calls=1; effects=1", result.disposition.value,
           kernel_calls=bridge.calls, transition=transition,
           details={"effect_count": result.effect_count})


def test_s11b_same_payload_source_scope_changes_verdict():
    allowed = make_transition(source="A", scope={"source_realms": ["A"]})
    excluded = make_transition(source="B", scope={"source_realms": ["A"]})
    assert canonical_hash(allowed) != canonical_hash(excluded)
    allow_result, allow_bridge, _ = invoke(allowed)
    deny_result, deny_bridge, _ = invoke(excluded)
    assert allow_result.disposition == Disposition.PASS
    assert deny_result.disposition == Disposition.HOLD
    assert allow_bridge.calls == 1 and deny_bridge.calls == 0
    record("S11b", "PASS for allowed source; HOLD for excluded source",
           f"{allow_result.disposition.value}/{deny_result.disposition.value}",
           kernel_calls=allow_bridge.calls + deny_bridge.calls, transition=excluded,
           details={"allowed_transition_hash": canonical_hash(allowed),
                    "excluded_transition_hash": canonical_hash(excluded)})


def test_s11c_transition_change_after_admission_hash_is_hard_veto():
    transition = make_transition(scope={"source_realms": ["A"]})
    original_hash = canonical_hash(transition)
    transition.scope["source_realms"] = ["B"]
    result, bridge, _ = invoke(transition, expected_transition_hash=original_hash)
    assert result.disposition == Disposition.HARD_VETO
    assert result.kernel_decision == "TRANSITION_HASH_CHANGED" and bridge.calls == 0
    record("S11c", "HARD_VETO; kernel_calls=0", result.kernel_decision,
           kernel_calls=bridge.calls, transition=transition, details={"expected_hash": original_hash})


def test_s11d_payload_digest_mismatch_is_binding_violation():
    transition = make_transition()
    changed_payload = {**PAYLOAD, "amount": 999}
    result, bridge, _ = invoke(transition, payload=changed_payload)
    assert result.disposition == Disposition.HOLD
    assert result.kernel_decision == "BINDING_VIOLATION" and bridge.calls == 0
    record("S11d", "BINDING_VIOLATION; kernel_calls=0", result.kernel_decision,
           kernel_calls=bridge.calls, transition=transition,
           details={"transition_digest": transition.payload_digest,
                    "actual_payload_digest": payload_sha256(changed_payload)})


def test_s11e_missing_target_postconditions_holds_before_kernel():
    transition = make_transition(postconditions=())
    result, bridge, _ = invoke(transition)
    assert result.disposition == Disposition.HOLD
    assert result.kernel_decision == "TARGET_POSTCONDITIONS_UNDECLARED" and bridge.calls == 0
    record("S11e", "HOLD; target postconditions required", result.kernel_decision,
           kernel_calls=bridge.calls, transition=transition)


def test_s11f_all_declared_transition_fields_contribute_to_hash():
    base = make_transition()
    changed = make_transition(evidence_refs=("ev-2",))
    assert canonical_hash(base) != canonical_hash(changed)
    result, bridge, _ = invoke(base)
    assert result.disposition == Disposition.PASS and bridge.calls == 1
    record("S11f", "hash changes when evidence_refs changes; valid transition passes",
           result.disposition.value, kernel_calls=bridge.calls, transition=base,
           details={"changed_field": "evidence_refs", "base_hash": canonical_hash(base),
                    "changed_hash": canonical_hash(changed)})


def test_s11g_canonical_hash_is_stable_across_processes():
    transition = make_transition()
    expected = canonical_hash(transition)
    script = (
        "from tenir_conformance.membrane import Transition, canonical_hash, payload_sha256; "
        "p={'P':0.5,'V':0.5,'K':1.0,'option_space':1.0}; "
        "t=Transition(tau_id='TAU-DEFAULT-TEST',source_realm='A',target_realm='B',"
        "action_class='default',principal='default',scope={'lei':'LEI-1'},"
        "payload_digest=payload_sha256(p),evidence_refs=('ev-1',),"
        "source_preconditions=('source-valid',),target_postconditions=('effect-applied',),"
        "declared_at='2026-10-09T10:00:00Z'); print(canonical_hash(t))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    actual = subprocess.check_output([sys.executable, "-c", script], cwd=ROOT, env=env, text=True).strip()
    assert actual == expected
    record("S11g", "identical SHA-256 in child process", actual,
           kernel_calls=0, transition=transition, details={"parent_hash": expected, "child_hash": actual})


def test_tau_001_admission_without_transition_is_refused():
    bridge = CountingBridge()
    membrane = Membrane(bridge)
    with pytest.raises(ValueError, match="TRANSITION_REQUIRED"):
        membrane.process_transaction(lei="LEI-1", attempt_id="TAU-001", nonce="n1")
    assert bridge.calls == 0
    record("TAU-001", "TRANSITION_REQUIRED; kernel_calls=0", "TRANSITION_REQUIRED",
           kernel_calls=bridge.calls)


def test_tau_002_mutated_transition_against_frozen_hash_is_rejected():
    transition = make_transition()
    frozen_hash = canonical_hash(transition)
    transition.scope["lei"] = "LEI-2"
    result, bridge, _ = invoke(transition, expected_transition_hash=frozen_hash)
    assert result.disposition == Disposition.HARD_VETO
    assert result.kernel_decision == "TRANSITION_HASH_CHANGED" and bridge.calls == 0
    record("TAU-002", "TRANSITION_HASH_CHANGED; kernel_calls=0", result.kernel_decision,
           kernel_calls=bridge.calls, transition=transition, details={"frozen_hash": frozen_hash})
