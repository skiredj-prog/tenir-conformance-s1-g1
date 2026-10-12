"""Conformance tests for manuscript v7.0 §4.4 — non_execution_attested.

Pins the normative obligations declared for pass2 / issue #25:

* reconcile never dispatches, never issues a permit, never reopens a receipt window
* non_execution_attested requires bound fresh evidence, e=0, and a qualifying
  signed attestation (lab field: non_execution_confirmed)
* the mark authorizes terminal FAILED without dispatch
* the mark does not claim external-world truth or key legitimacy
* retry_eligible is an audit annotation only — not a G_adm guard

These tests target the lab membrane in tenir-conformance-s1-g1.
They do not certify a production gateway.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from tenir_conformance.membrane import (
    AttemptState,
    BindingError,
    Evidence,
    FakeClock,
    Membrane,
)
from tenir_conformance.membrane.kernel_bridge import KernelBridge
from s7_helpers import sign_attestation

PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}
NOW = 1_000_000
TAU = 5_000
LEI = "L"
ATTEMPT = "A1"
NONCE = "n-nea-01"


def _membrane(clock: FakeClock | None = None) -> Membrane:
    return Membrane(KernelBridge(), clock=clock or FakeClock(now_ms=NOW), tau_k_ms=TAU)


def _failed_evidence(
    *,
    evidence_id: str = "E-NEA-FAILED",
    non_execution_confirmed: bool = True,
    integrity_verified: bool = True,
    nonce: str = NONCE,
    attempt_id: str = ATTEMPT,
    lei: str = LEI,
) -> Evidence:
    attestation = None
    if non_execution_confirmed:
        attestation = sign_attestation(
            attestation_id=f"AT-{evidence_id}",
            attempt_id=attempt_id,
            lei=lei,
            nonce=nonce,
            non_execution_confirmed=True,
        )
    return Evidence(
        evidence_id=evidence_id,
        attempt_id=attempt_id,
        lei=lei,
        nonce=nonce,
        status="FAILED",
        properties={},
        reference_scope=f"operation:LEI-{lei}",
        reference_snapshot="snapshot:nea-v1",
        normalization_profile="reconciliation-v1",
        integrity_verified=integrity_verified,
        source_authoritative=True,
        expires_at_ms=NOW + 60_000,
        non_execution_confirmed=non_execution_confirmed,
        attestation=attestation,
    )


def _unknown_no_effect() -> tuple[Membrane, FakeClock]:
    clock = FakeClock(now_ms=NOW)
    m = _membrane(clock)
    m.admit_and_await_qualification(
        lei=LEI,
        attempt_id=ATTEMPT,
        payload=PAYLOAD,
        apply_effect=False,
        nonce=NONCE,
    )
    clock.advance_to(NOW + TAU)
    timed_out = m.check_qualification_timeouts()
    assert ATTEMPT in timed_out
    assert m.attempts[ATTEMPT].state == AttemptState.UNKNOWN
    assert m.attempts[ATTEMPT].effect_observed is False
    return m, clock


def test_nea_reconcile_failed_does_not_dispatch_or_issue_permit():
    m, _ = _unknown_no_effect()
    effects_before = list(m.sink.effects)
    permit_ids_before = set(m.permits)
    consumed_before = {k: (p.consumed, p.revoked) for k, p in m.permits.items()}

    result = m.reconcile(
        attempt_id=ATTEMPT,
        evidence=_failed_evidence(non_execution_confirmed=True),
        retry_eligible=False,
    )

    assert result.client_state == "FAILED"
    assert m.attempts[ATTEMPT].state == AttemptState.FAILED
    assert list(m.sink.effects) == effects_before
    assert set(m.permits) == permit_ids_before
    assert {k: (p.consumed, p.revoked) for k, p in m.permits.items()} == consumed_before


def test_nea_reconcile_does_not_reopen_receipt_window_via_late_path():
    m, clock = _unknown_no_effect()
    effects_before = list(m.sink.effects)
    far = NOW + TAU + 100_000
    clock.advance_to(far)
    evidence = replace(
        _failed_evidence(non_execution_confirmed=True),
        expires_at_ms=far + 60_000,
    )
    result = m.reconcile(attempt_id=ATTEMPT, evidence=evidence)
    assert m.attempts[ATTEMPT].state == AttemptState.FAILED
    assert result.client_state == "FAILED"
    assert list(m.sink.effects) == effects_before


def test_nea_requires_non_execution_confirmation_to_reach_failed():
    m, _ = _unknown_no_effect()
    result = m.reconcile(
        attempt_id=ATTEMPT,
        evidence=_failed_evidence(non_execution_confirmed=False),
    )
    assert m.attempts[ATTEMPT].state == AttemptState.UNKNOWN
    assert result.client_state != "FAILED"
    assert result.kernel_decision == "RECONCILIATION_NO_NON_EXECUTION_PROOF"


def test_nea_failed_path_sets_terminal_failed_with_e_obs_zero():
    m, _ = _unknown_no_effect()
    effects_before = len(m.sink.effects)
    m.reconcile(
        attempt_id=ATTEMPT,
        evidence=_failed_evidence(non_execution_confirmed=True),
    )
    attempt = m.attempts[ATTEMPT]
    assert attempt.state == AttemptState.FAILED
    assert attempt.effect_observed is False
    assert len(m.sink.effects) == effects_before


def test_nea_binding_mismatch_rejects_attestation_path():
    m, _ = _unknown_no_effect()
    bad = _failed_evidence(non_execution_confirmed=True, nonce="n-wrong-binding")
    with pytest.raises(BindingError):
        m.reconcile(attempt_id=ATTEMPT, evidence=bad)
    assert m.attempts[ATTEMPT].state == AttemptState.UNKNOWN


def test_nea_retry_eligible_false_does_not_block_lei_after_failed_non_execution():
    m, _ = _unknown_no_effect()
    m.reconcile(
        attempt_id=ATTEMPT,
        evidence=_failed_evidence(non_execution_confirmed=True),
        retry_eligible=False,
    )
    assert m.attempts[ATTEMPT].state == AttemptState.FAILED
    assert m.attempts[ATTEMPT].retry_eligible is False
    assert m.retry_eligible_for(LEI) is True
    second = m.admit_and_await_qualification(
        lei=LEI,
        attempt_id="A2",
        payload=PAYLOAD,
        apply_effect=False,
        nonce="n-nea-a2",
    )
    assert "A2" in m.attempts
    assert second.kernel_decision != "NOT_EVALUATED"


def test_nea_declare_failed_t7_with_attestation_matches_reconcile_semantics():
    clock = FakeClock(now_ms=NOW)
    m = _membrane(clock)
    m.process_transaction(
        lei=LEI,
        attempt_id=ATTEMPT,
        payload=PAYLOAD,
        nonce=NONCE,
        request_lost=True,
    )
    assert m.attempts[ATTEMPT].state == AttemptState.UNKNOWN
    effects_before = len(m.sink.effects)

    m.declare_failed(
        attempt_id=ATTEMPT,
        evidence_qualified=True,
        attestation=sign_attestation(
            attestation_id="AT-NEA-T7",
            attempt_id=ATTEMPT,
            lei=LEI,
            nonce=NONCE,
            non_execution_confirmed=True,
        ),
        retry_eligible=False,
    )
    assert m.attempts[ATTEMPT].state == AttemptState.FAILED
    assert m.attempts[ATTEMPT].effect_observed is False
    assert len(m.sink.effects) == effects_before
    assert m.retry_eligible_for(LEI) is True


def test_nea_does_not_claim_external_world_truth_via_sink_oracle():
    m, _ = _unknown_no_effect()
    assert len(m.sink.effects) == 0
    m.reconcile(
        attempt_id=ATTEMPT,
        evidence=_failed_evidence(non_execution_confirmed=True),
    )
    assert len(m.sink.effects) == 0
    assert m.attempts[ATTEMPT].state == AttemptState.FAILED
