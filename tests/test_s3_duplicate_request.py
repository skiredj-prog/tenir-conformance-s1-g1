"""G0 S3 — Duplicate Request: empirical validation against the real lab membrane.

Validates sequential interleavings on tenir_conformance.membrane.Membrane.
Does not claim mathematical proof of all concurrent schedules.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tenir_conformance.membrane.membrane import (
    AttemptState,
    DuplicateAttemptID,
    FakeClock,
    Membrane,
    UnresolvedSameLEI,
)
from tenir_conformance.membrane.kernel_bridge import KernelBridge
from s7_helpers import sign_attestation

PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}
ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "G0_S3_Duplicate_Request.md"
SCENARIO_PATH = ROOT / "scenarios" / "S3.json"
ARTIFACTS = ROOT / "artifacts" / "s3"


def _membrane(clock: FakeClock | None = None) -> Membrane:
    return Membrane(
        KernelBridge(),
        clock=clock or FakeClock(now_ms=1_000_000),
        tau_k_ms=5_000,
    )


def _spec_sha256() -> str:
    assert SPEC_PATH.is_file(), f"missing G0 spec: {SPEC_PATH}"
    return hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()


def _scenario_sha256() -> str:
    assert SCENARIO_PATH.is_file()
    return hashlib.sha256(SCENARIO_PATH.read_bytes()).hexdigest()


def _dump_evidence(
    membrane: Membrane,
    *,
    subcase: str,
    a1_id: str,
    a2_id: str,
    client_state: str,
    disposition: str,
) -> Path:
    """Emit the five physical artifact classes required by G0 S3."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    events = list(membrane.events)
    a2_events = [
        e
        for e in events
        if e.get("attempt_id") == a2_id
        or e.get("event") in ("T1_guard_FALSE", "S3_DUPLICATE_ATTEMPT_ID")
    ]
    evidence = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "subcase": subcase,
        "spec_sha256": _spec_sha256(),
        "scenario_sha256": _scenario_sha256(),
        "a1_id": a1_id,
        "a2_id": a2_id,
        "client_state": client_state,
        "disposition": disposition,
        "effect_sink_count": len(membrane.sink.effects),
        "attempts_registered": sorted(membrane.attempts.keys()),
        "permits_issued": sorted(membrane.permits.keys()),
        "transition_log": events,
        "a2_transition_slice": a2_events,
    }
    jsonl_path = ARTIFACTS / f"evidence_G0_{subcase}.jsonl"
    with jsonl_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(evidence, sort_keys=True) + "\n")
    (ARTIFACTS / f"{subcase}_transition.json").write_text(
        json.dumps(events, indent=2), encoding="utf-8"
    )
    permits = {
        k: {"lei": p.lei, "consumed": p.consumed, "issued_at_ms": p.issued_at_ms}
        for k, p in membrane.permits.items()
    }
    (ARTIFACTS / f"{subcase}_permit.json").write_text(
        json.dumps(permits, indent=2), encoding="utf-8"
    )
    (ARTIFACTS / f"{subcase}_effect_sink.json").write_text(
        json.dumps(membrane.sink.effects, indent=2), encoding="utf-8"
    )
    (ARTIFACTS / f"{subcase}_result.json").write_text(
        json.dumps(
            {
                "subcase": subcase,
                "client_state": client_state,
                "disposition": disposition,
                "spec_sha256": evidence["spec_sha256"],
                "scenario_sha256": evidence["scenario_sha256"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return jsonl_path


def _assert_g0_rejection(
    membrane: Membrane,
    *,
    a1_id: str,
    a2_id: str,
    lei: str,
    baseline_effects: int,
    a1_state_before: AttemptState,
    client_state: str,
    disposition: str,
    require_t1_guard: bool = True,
) -> None:
    """Seven G0 assertions for sequential A2 rejection."""
    assert client_state in ("UNKNOWN", "FAILED")
    assert disposition == "HOLD"
    assert a1_id in membrane.attempts
    assert membrane.attempts[a1_id].state == a1_state_before
    assert membrane.attempts[a1_id].lei == lei
    assert a2_id not in membrane.attempts
    assert a2_id not in membrane.permits
    assert len(membrane.sink.effects) == baseline_effects
    event_names = [e["event"] for e in membrane.events]
    if require_t1_guard:
        assert "T1_guard_FALSE" in event_names
    else:
        assert "S3_DUPLICATE_ATTEMPT_ID" in event_names


def test_s3a_a1_awaiting_qualification():
    """S3a: A1 AWAITING_QUALIFICATION; A2 same LEI rejected at barrier."""
    m = _membrane()
    m.admit_and_await_qualification(
        lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True
    )
    a1_state = m.attempts["A1"].state
    assert a1_state == AttemptState.AWAITING_QUALIFICATION
    baseline = len(m.sink.effects)

    with pytest.raises(UnresolvedSameLEI):
        m._register_attempt(lei="L", attempt_id="A2")

    r = m.admit_and_await_qualification(
        lei="L", attempt_id="A2", payload=PAYLOAD, apply_effect=True
    )
    _assert_g0_rejection(
        m,
        a1_id="A1",
        a2_id="A2",
        lei="L",
        baseline_effects=baseline,
        a1_state_before=a1_state,
        client_state=r.client_state,
        disposition=r.disposition.value,
    )
    _dump_evidence(
        m,
        subcase="S3a",
        a1_id="A1",
        a2_id="A2",
        client_state=r.client_state,
        disposition=r.disposition.value,
    )


def test_s3b_a1_executed_receipt_pending():
    """S3b: A1 effect applied, receipt lost → UNKNOWN; A2 blocked; sink stable."""
    m = _membrane()
    first = m.process_transaction(
        nonce="n-s3-process_transaction-01",
        lei="L", attempt_id="A1", payload=PAYLOAD, receipt_lost=True
    )
    assert first.effect_count == 1
    a1_state = m.attempts["A1"].state
    assert a1_state == AttemptState.UNKNOWN
    baseline = len(m.sink.effects)

    with pytest.raises(UnresolvedSameLEI):
        m._register_attempt(lei="L", attempt_id="A2")

    r = m.process_transaction(nonce="n-s3-process_transaction-02", lei="L", attempt_id="A2", payload=PAYLOAD)
    _assert_g0_rejection(
        m,
        a1_id="A1",
        a2_id="A2",
        lei="L",
        baseline_effects=baseline,
        a1_state_before=a1_state,
        client_state=r.client_state,
        disposition=r.disposition.value,
    )
    _dump_evidence(
        m,
        subcase="S3b",
        a1_id="A1",
        a2_id="A2",
        client_state=r.client_state,
        disposition=r.disposition.value,
    )


def test_s3c_a1_unknown_after_timeout():
    """S3c: A1 UNKNOWN after tau_K; A2 blocked."""
    clock = FakeClock(now_ms=1_000_000)
    m = Membrane(KernelBridge(), clock=clock, tau_k_ms=5_000)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=False
    )
    clock.advance_to(1_000_000 + 5_000)
    m.check_qualification_timeouts()
    a1_state = m.attempts["A1"].state
    assert a1_state == AttemptState.UNKNOWN
    baseline = len(m.sink.effects)

    with pytest.raises(UnresolvedSameLEI):
        m._register_attempt(lei="L", attempt_id="A2")

    r = m.retry(nonce="n-s3-retry-01", lei="L", attempt_id="A2", payload=PAYLOAD)
    _assert_g0_rejection(
        m,
        a1_id="A1",
        a2_id="A2",
        lei="L",
        baseline_effects=baseline,
        a1_state_before=a1_state,
        client_state=r.client_state,
        disposition=r.disposition.value,
    )
    _dump_evidence(
        m,
        subcase="S3c",
        a1_id="A1",
        a2_id="A2",
        client_state=r.client_state,
        disposition=r.disposition.value,
    )


def test_s3d_duplicate_attempt_id():
    """S3d: identity collision rejected before LEI evaluation; A1 not mutated."""
    m = _membrane()
    m.admit_and_await_qualification(
        lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True
    )
    a1_state = m.attempts["A1"].state
    baseline = len(m.sink.effects)

    with pytest.raises(DuplicateAttemptID):
        m._register_attempt(lei="L", attempt_id="A1")

    r = m.process_transaction(nonce="n-s3-process_transaction-03", lei="L", attempt_id="A1", payload=PAYLOAD)
    _assert_g0_rejection(
        m,
        a1_id="A1",
        a2_id="A1-dup-soft",
        lei="L",
        baseline_effects=baseline,
        a1_state_before=a1_state,
        client_state=r.client_state,
        disposition=r.disposition.value,
        require_t1_guard=False,
    )
    assert list(m.attempts.keys()) == ["A1"]
    events = [e["event"] for e in m.events]
    assert "S3_DUPLICATE_ATTEMPT_ID" in events
    _dump_evidence(
        m,
        subcase="S3d",
        a1_id="A1",
        a2_id="A1",
        client_state=r.client_state,
        disposition=r.disposition.value,
    )


def test_s3_after_t8_eligible_new_id_allowed():
    """Control: T7 FAILED + retry_eligible unlocks new attempt_id on same LEI."""
    m = _membrane()
    m.process_transaction(
        nonce="n-s3-process_transaction-04",
        lei="L", attempt_id="A1", payload=PAYLOAD, request_lost=True
    )
    m.declare_failed(
        attempt_id="A1", evidence_qualified=True,
        attestation=sign_attestation(
            attestation_id="AT-S3-T8",
            attempt_id="A1", lei="L", nonce="n-s3-process_transaction-04",
        ),
        retry_eligible=True,
    )
    m._register_attempt(lei="L", attempt_id="A2")
    assert "A2" in m.attempts
    assert m.attempts["A1"].state == AttemptState.FAILED


def test_s3_spec_and_scenario_hashes_stable():
    """Specification file is present and hashable (empirical binding)."""
    sha = _spec_sha256()
    assert len(sha) == 64
    sc = _scenario_sha256()
    assert len(sc) == 64
    payload = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    assert payload["id"] == "S3"
    assert "S3d" in payload["subcases"]
