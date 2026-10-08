"""G0 S3 — Duplicate Request against the RFC-4 membrane."""

import json
import hashlib
from pathlib import Path

import pytest

from tenir_conformance.membrane.membrane import (
    FakeClock,
    Membrane,
    AttemptState,
    DuplicateAttemptID,
    UnresolvedSameLEI,
)
from tenir_conformance.membrane.kernel_bridge import KernelBridge

PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}


def _m(clock=None):
    return Membrane(KernelBridge(), clock=clock or FakeClock(now_ms=1_000_000))


def _assert_a2_absent(m: Membrane, a2_id: str, baseline_effects: int):
    assert a2_id not in m.attempts
    assert a2_id not in m.permits
    assert len(m.sink.effects) == baseline_effects


def test_s3a_second_admit_while_awaiting_qualification():
    """S3a: A1 AWAITING_QUALIFICATION; A2 same LEI rejected."""
    m = _m()
    m.admit_and_await_qualification(
        lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True
    )
    assert m.attempts["A1"].state == AttemptState.AWAITING_QUALIFICATION
    baseline = len(m.sink.effects)

    with pytest.raises(UnresolvedSameLEI):
        m._register_attempt(lei="L", attempt_id="A2")

    second = m.admit_and_await_qualification(
        lei="L", attempt_id="A2", payload=PAYLOAD, apply_effect=True
    )
    assert second.kernel_decision == "NOT_EVALUATED"
    assert second.disposition.value == "HOLD"
    _assert_a2_absent(m, "A2", baseline)
    assert m.attempts["A1"].state == AttemptState.AWAITING_QUALIFICATION
    events = [e["event"] for e in m.events]
    assert "T1_guard_FALSE" in events


def test_s3b_second_while_executed_receipt_pending():
    """S3b: A1 effect applied, receipt lost -> UNKNOWN; A2 blocked; effect count stable."""
    m = _m()
    first = m.process_transaction(
        lei="L", attempt_id="A1", payload=PAYLOAD, receipt_lost=True
    )
    assert first.effect_count == 1
    assert m.attempts["A1"].state == AttemptState.UNKNOWN
    baseline = len(m.sink.effects)

    with pytest.raises(UnresolvedSameLEI):
        m._register_attempt(lei="L", attempt_id="A2")

    second = m.process_transaction(lei="L", attempt_id="A2", payload=PAYLOAD)
    assert second.kernel_decision == "NOT_EVALUATED"
    _assert_a2_absent(m, "A2", baseline)
    assert m.attempts["A1"].state == AttemptState.UNKNOWN


def test_s3c_second_while_unknown_after_timeout():
    """S3c: A1 UNKNOWN after tau_K; A2 blocked."""
    clock = FakeClock(now_ms=1_000_000)
    m = Membrane(KernelBridge(), clock=clock, tau_k_ms=5_000)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=False
    )
    clock.advance_to(1_000_000 + 5_000)
    m.check_qualification_timeouts()
    assert m.attempts["A1"].state == AttemptState.UNKNOWN
    baseline = len(m.sink.effects)

    with pytest.raises(UnresolvedSameLEI):
        m._register_attempt(lei="L", attempt_id="A2")

    second = m.retry(lei="L", attempt_id="A2", payload=PAYLOAD)
    assert second.kernel_decision == "NOT_EVALUATED"
    _assert_a2_absent(m, "A2", baseline)


def test_s3d_duplicate_attempt_id_rejected_before_lei():
    """S3d: reusing A1 attempt_id raises DuplicateAttemptID; A1 not mutated."""
    m = _m()
    m.admit_and_await_qualification(
        lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True
    )
    a1_state = m.attempts["A1"].state
    baseline = len(m.sink.effects)

    with pytest.raises(DuplicateAttemptID):
        m._register_attempt(lei="L", attempt_id="A1")

    r = m.process_transaction(lei="L", attempt_id="A1", payload=PAYLOAD)
    assert r.kernel_decision == "NOT_EVALUATED"
    assert m.attempts["A1"].state == a1_state
    assert len(m.sink.effects) == baseline
    events = [e["event"] for e in m.events]
    assert "S3_DUPLICATE_ATTEMPT_ID" in events


def test_s3_after_t8_eligible_new_id_allowed():
    """Control: after T7 FAILED + retry_eligible, new attempt_id on same LEI is allowed."""
    m = _m()
    m.process_transaction(
        lei="L", attempt_id="A1", payload=PAYLOAD, request_lost=True
    )
    m.declare_failed(
        attempt_id="A1", evidence_qualified=True, retry_eligible=True
    )
    m._register_attempt(lei="L", attempt_id="A2")
    assert "A2" in m.attempts
    assert m.attempts["A1"].state == AttemptState.FAILED


def test_s3_scenario_definition_present():
    scenario = Path(__file__).parents[1] / "scenarios" / "S3.json"
    assert scenario.exists()
    payload = json.loads(scenario.read_text(encoding="utf-8"))
    assert payload["id"] == "S3"
    assert "S3d" in payload["subcases"]
    assert len(hashlib.sha256(scenario.read_bytes()).hexdigest()) == 64
