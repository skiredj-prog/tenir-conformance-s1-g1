"""G0 S5 — contradictory evidence and epistemic escalation conformance tests."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tenir_conformance.membrane import (
    AttemptState,
    BindingError,
    ContradictoryEvidenceError,
    Evidence,
    FakeClock,
    IncompleteEvidence,
    Membrane,
    Receipt,
)
from tenir_conformance.membrane.kernel_bridge import KernelBridge

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "scenarios" / "G0_S5_CONTRADICTORY_EVIDENCE.md"
SCENARIO_PATH = ROOT / "scenarios" / "S5.json"
ARTIFACTS = ROOT / "artifacts" / "s5"
PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}
NOW = 1_000_000
TAU = 5_000


def _membrane(clock: FakeClock | None = None) -> Membrane:
    return Membrane(
        KernelBridge(),
        clock=clock or FakeClock(now_ms=NOW),
        tau_k_ms=TAU,
        conflict_sensitive_properties={"exposure"},
        quarantine_release_authorizer=lambda principal, lei: (
            principal == "risk-owner-test" and bool(lei)
        ),
    )


def _evidence(
    evidence_id: str,
    status: str,
    *,
    attempt_id: str = "A1",
    lei: str = "L",
    nonce: str = "n-s5",
    properties: dict | None = None,
    scope: str = "portfolio:LEI-L",
    snapshot: str = "snapshot:2026-10-09T00:00Z",
    normalization_profile: str = "exposure-normalization-v1",
    integrity_verified: bool = True,
    source_authoritative: bool = True,
    expires_at_ms: int = NOW + 60_000,
    required_properties: tuple[str, ...] = (),
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        attempt_id=attempt_id,
        lei=lei,
        nonce=nonce,
        status=status,
        properties=properties or {},
        reference_scope=scope,
        reference_snapshot=snapshot,
        normalization_profile=normalization_profile,
        integrity_verified=integrity_verified,
        source_authoritative=source_authoritative,
        expires_at_ms=expires_at_ms,
        required_properties=required_properties,
    )


def _spec_sha() -> str:
    return hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()


def _scenario_sha() -> str:
    return hashlib.sha256(SCENARIO_PATH.read_bytes()).hexdigest()


def _dump(m: Membrane, subcase: str, *, baseline_effects: int, permits_before: int) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    after_effects = len(m.sink.effects)
    body = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scenario_id": "G0_S5",
        "subcase": subcase,
        "spec_sha256": _spec_sha(),
        "scenario_sha256": _scenario_sha(),
        "effect_sink_count_before": baseline_effects,
        "effect_sink_count_after": after_effects,
        "effect_sink_delta": after_effects - baseline_effects,
        "issued_permit_count_before": permits_before,
        "issued_permit_count_after": len(m.permits),
        "issued_permit_delta": len(m.permits) - permits_before,
        "attempts": {
            key: {
                "lei": attempt.lei,
                "state": attempt.state.value,
                "nonce_registered": bool(attempt.nonce),
                "qualified": attempt.qualified,
                "timeout_fired": attempt.timeout_fired,
            }
            for key, attempt in m.attempts.items()
        },
        "permits": {
            key: {
                "lei": permit.lei,
                "consumed": permit.consumed,
                "revoked": permit.revoked,
                "usable": m.is_execution_permit_usable(key),
            }
            for key, permit in m.permits.items()
        },
        "governance_quarantine": m.governance_quarantine,
        "governance_quarantine_history": m.governance_quarantine_history,
        "transition_log": m.events,
        "claim_scope": "tested sequential interleavings only",
    }
    (ARTIFACTS / f"{subcase}.json").write_text(
        json.dumps(body, sort_keys=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (ARTIFACTS / f"{subcase}.jsonl").write_text(
        json.dumps(body, sort_keys=True, separators=(",", ":"), default=str) + "\n",
        encoding="utf-8",
    )


def _outcome_conflict() -> list[Evidence]:
    return [
        _evidence("E-FAIL-1", "FAILED"),
        _evidence("E-COMMIT-1", "COMMITTED"),
    ]


def _property_conflict() -> list[Evidence]:
    return [
        _evidence("E-OK-X", "COMMITTED", properties={"exposure": 1000},
                  required_properties=("exposure",)),
        _evidence("E-OK-Y", "COMMITTED", properties={"exposure": 2500},
                  required_properties=("exposure",)),
    ]


def _make_resolved_attempt(m: Membrane, *, lei: str = "L", attempt_id: str = "A1", nonce: str = "n-s5") -> int:
    m.admit_and_await_qualification(
        lei=lei, attempt_id=attempt_id, payload=PAYLOAD, apply_effect=True, nonce=nonce
    )
    r = m.deliver_qualifying_receipt(
        Receipt(attempt_id=attempt_id, lei=lei, nonce=nonce, expires_at_ms=NOW + 30_000)
    )
    assert r.disposition.value == "PASS"
    assert m.attempts[attempt_id].state == AttemptState.RESOLVED
    return len(m.sink.effects)


def test_s5_spec_hash_and_scenario_are_versioned():
    assert len(_spec_sha()) == 64
    assert len(_scenario_sha()) == 64
    scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    assert scenario["id"] == "G0_S5"
    assert scenario["assertions"] == ["A1", "A2", "A3", "A4", "A5", "A6", "A7"]


def test_s5a_outcome_conflict_escalates_atomically():
    clock = FakeClock(now_ms=NOW)
    m = _membrane(clock)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True, nonce="n-s5"
    )
    baseline_effects = len(m.sink.effects)
    assert baseline_effects == 1
    clock.advance_to(NOW + TAU)
    m.check_qualification_timeouts()
    assert m.attempts["A1"].state == AttemptState.UNKNOWN
    permits_before = len(m.permits)

    result = m.evaluate_evidence_batch(attempt_id="A1", evidence_batch=_outcome_conflict())

    assert result.disposition.value == "HOLD"
    assert m.attempts["A1"].state == AttemptState.ESCALATED
    assert m._has_unresolved("L")
    assert len(m.sink.effects) - baseline_effects == 0
    assert len(m.permits) - permits_before == 0
    assert m.permits["A1"].revoked is True
    assert m.is_execution_permit_usable("A1") is False
    conflict = next(e for e in m.events if e["event"] == "EVIDENCE_CONTRADICTION")
    assert conflict["attempt_id"] == "A1"
    assert set(conflict["evidence_ids"]) == {"E-FAIL-1", "E-COMMIT-1"}
    _dump(m, "S5a_outcome_conflict", baseline_effects=baseline_effects, permits_before=permits_before)


def test_s5b_property_conflict_preserves_terminal_state_and_quarantines_lei():
    m = _membrane()
    baseline_effects = _make_resolved_attempt(m)
    assert baseline_effects == 1
    permits_before = len(m.permits)
    state_before = m.attempts["A1"].state

    result = m.evaluate_evidence_batch(attempt_id="A1", evidence_batch=_property_conflict())

    assert result.disposition.value == "HOLD"
    assert m.attempts["A1"].state == state_before == AttemptState.RESOLVED
    assert m.governance_quarantine["L"]["state"] == "QUARANTINED"
    assert m._has_unresolved("L")
    assert len(m.sink.effects) - baseline_effects == 0
    assert len(m.permits) - permits_before == 0
    assert m.permits["A1"].revoked is True
    incident = next(e for e in m.events if e["event"] == "EVIDENCE_ESCALATION_INCIDENT")
    assert incident["preserved_state"] == AttemptState.RESOLVED.value
    conflict = next(e for e in m.events if e["event"] == "EVIDENCE_CONTRADICTION")
    assert set(conflict["evidence_ids"]) == {"E-OK-X", "E-OK-Y"}
    _dump(m, "S5b_property_conflict", baseline_effects=baseline_effects, permits_before=permits_before)


def test_s5_existing_unconsumed_permit_is_revoked_by_conflict():
    m = _membrane()
    attempt = m._register_attempt(lei="L", attempt_id="A1", nonce="n-s5")
    assert attempt.state == AttemptState.PENDING
    assert m.is_execution_permit_usable("A1") is True
    permits_before = len(m.permits)
    effects_before = len(m.sink.effects)

    m.evaluate_evidence_batch(attempt_id="A1", evidence_batch=_outcome_conflict())

    assert len(m.permits) == permits_before
    assert len(m.sink.effects) == effects_before
    assert m.permits["A1"].revoked is True
    assert m.is_execution_permit_usable("A1") is False
    assert m.attempts["A1"].state == AttemptState.ESCALATED


def test_s5_binding_failure_is_not_misclassified_as_contradiction():
    m = _membrane()
    m.admit_and_await_qualification(
        lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True, nonce="n-s5"
    )
    state_before = m.attempts["A1"].state
    effects_before = len(m.sink.effects)
    permits_before = len(m.permits)
    batch = [
        _evidence("E-1", "FAILED"),
        _evidence("E-2", "COMMITTED", nonce="wrong-nonce"),
    ]

    with pytest.raises(BindingError):
        m.evaluate_evidence_batch(attempt_id="A1", evidence_batch=batch)

    assert m.attempts["A1"].state == state_before
    assert len(m.sink.effects) == effects_before
    assert len(m.permits) == permits_before
    assert not any(e["event"] == "EVIDENCE_CONTRADICTION" for e in m.events)


def test_s5_incomplete_evidence_is_rejected_before_state_mutation():
    m = _membrane()
    m._register_attempt(lei="L", attempt_id="A1", nonce="n-s5")
    before = m.attempts["A1"].state
    incomplete = [
        _evidence("E-1", "COMMITTED", properties={}, required_properties=("exposure",)),
        _evidence("E-2", "COMMITTED", properties={"exposure": 1000},
                  required_properties=("exposure",)),
    ]

    with pytest.raises(IncompleteEvidence):
        m.evaluate_evidence_batch(attempt_id="A1", evidence_batch=incomplete)

    assert m.attempts["A1"].state == before
    assert not m.governance_quarantine
    assert not any(e["event"] == "EVIDENCE_CONTRADICTION" for e in m.events)


def test_s5_consistent_batch_can_follow_normal_resolution_path():
    m = _membrane()
    m.admit_and_await_qualification(
        lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=False, nonce="n-s5"
    )
    before_effects = len(m.sink.effects)
    batch = [
        _evidence("E-1", "COMMITTED", properties={"exposure": 1000},
                  required_properties=("exposure",)),
        _evidence("E-2", "COMMITTED", properties={"exposure": 1000},
                  required_properties=("exposure",)),
    ]

    result = m.evaluate_evidence_batch(attempt_id="A1", evidence_batch=batch)

    assert result.disposition.value == "PASS"
    assert m.attempts["A1"].state == AttemptState.RESOLVED
    assert m.attempts["A1"].effect_observed is True
    assert len(m.sink.effects) == before_effects
    assert not m.governance_quarantine
    assert not any(e["event"] == "EVIDENCE_CONTRADICTION" for e in m.events)


def test_s5_quarantine_release_does_not_override_resolved_effect_lock():
    m = _membrane()
    _make_resolved_attempt(m)
    m.evaluate_evidence_batch(attempt_id="A1", evidence_batch=_property_conflict())
    quarantine = m.governance_quarantine["L"]
    permits_before = len(m.permits)
    effects_before = len(m.sink.effects)

    result = m.process_transaction(lei="L", attempt_id="A2", payload=PAYLOAD)

    assert result.disposition.value == "HOLD"
    assert len(m.permits) == permits_before
    assert len(m.sink.effects) == effects_before
    assert "L" in m.governance_quarantine

    with pytest.raises(PermissionError):
        m.resolve_governance_quarantine(
            lei="L",
            incident_id=quarantine["incident_id"],
            authorized_by="untrusted-test",
            rationale="An untrusted principal must not lift quarantine.",
        )
    assert "L" in m.governance_quarantine
    assert any(e["event"] == "GOVERNANCE_QUARANTINE_RELEASE_REJECTED" for e in m.events)

    m.resolve_governance_quarantine(
        lei="L",
        incident_id=quarantine["incident_id"],
        authorized_by="risk-owner-test",
        rationale="Audited resolution recorded by the conformance test.",
    )
    assert "L" not in m.governance_quarantine
    assert m.governance_quarantine_history[-1]["state"] == "RELEASED"
    assert any(e["event"] == "GOVERNANCE_QUARANTINE_RELEASED" for e in m.events)

    # Releasing incident quarantine does not erase proof of an already resolved effect.
    resumed = m.process_transaction(lei="L", attempt_id="A2", payload=PAYLOAD)
    assert resumed.disposition.value == "HOLD"
    assert resumed.kernel_decision == "NOT_EVALUATED"
    assert "A2" not in m.attempts
    assert len(m.permits) == permits_before
    assert len(m.sink.effects) == effects_before


def test_s5_evidence_id_is_stable_and_cannot_be_rewritten():
    m = _membrane()
    m._register_attempt(lei="L", attempt_id="A1", nonce="n-s5")
    first = _evidence("E-STABLE", "COMMITTED", properties={"exposure": 1000})
    m.evaluate_evidence_batch(attempt_id="A1", evidence_batch=[first])
    changed_payload = _evidence("E-STABLE", "COMMITTED", properties={"exposure": 2500})

    with pytest.raises(IncompleteEvidence):
        m.evaluate_evidence_batch(attempt_id="A1", evidence_batch=[changed_payload])


def test_s5_mixed_normalization_profiles_are_rejected_before_decision():
    m = _membrane()
    m._register_attempt(lei="L", attempt_id="A1", nonce="n-s5")
    batch = [
        _evidence("E-V1", "COMMITTED", properties={"exposure": 1000},
                  normalization_profile="exposure-v1"),
        _evidence("E-V2", "COMMITTED", properties={"exposure": 2500},
                  normalization_profile="exposure-v2"),
    ]

    with pytest.raises(IncompleteEvidence):
        m.evaluate_evidence_batch(attempt_id="A1", evidence_batch=batch)

    assert m.attempts["A1"].state == AttemptState.PENDING
    assert m.is_execution_permit_usable("A1") is True
    assert not any(e["event"] == "EVIDENCE_CONTRADICTION" for e in m.events)




def test_s5_negative_outcome_cannot_override_observed_effect():
    clock = FakeClock(now_ms=NOW)
    m = _membrane(clock)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A1", payload=PAYLOAD, apply_effect=True, nonce="n-s5"
    )
    clock.advance_to(NOW + TAU)
    m.check_qualification_timeouts()
    assert m.attempts["A1"].state == AttemptState.UNKNOWN
    assert m.attempts["A1"].effect_observed is True

    result = m.evaluate_evidence_batch(
        attempt_id="A1", evidence_batch=[_evidence("E-FAIL-AFTER-EFFECT", "FAILED")]
    )

    assert result.disposition.value == "HOLD"
    assert result.kernel_decision == "EVIDENCE_CONTRADICTS_OBSERVED_EFFECT"
    assert m.attempts["A1"].state == AttemptState.UNKNOWN
    assert m.retry_eligible_for("L") is False
    assert "EVIDENCE_NEGATIVE_CONTRADICTS_OBSERVED_EFFECT" in [e["event"] for e in m.events]
