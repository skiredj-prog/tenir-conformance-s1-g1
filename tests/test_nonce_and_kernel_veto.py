"""Regression tests for nonce binding and deterministic kernel HARD_VETO."""

from __future__ import annotations

import pytest

from tenir_conformance.membrane import (
    AttemptState,
    BindingError,
    Disposition,
    Evidence,
    Membrane,
)
from tenir_conformance.membrane.kernel_bridge import KernelBridge, KernelDecision


PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}
DENIED = KernelDecision(
    admissible=False, score=0.25, decision="block", rationale="standing denied"
)
ALLOWED = KernelDecision(
    admissible=True, score=2.0, decision="allow", rationale="admissible"
)


class SequenceBridge:
    def __init__(self, *decisions: KernelDecision):
        self.decisions = list(decisions)
        self.calls = 0

    def evaluate(self, payload):
        self.calls += 1
        return self.decisions.pop(0)


def _committed_evidence(*, evidence_id: str, nonce: str) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        attempt_id="A1",
        lei="L",
        nonce=nonce,
        status="COMMITTED",
        properties={},
        reference_scope="operation:LEI-L",
        reference_snapshot="snapshot:nonce-v1",
        normalization_profile="reconciliation-v1",
        integrity_verified=True,
        source_authoritative=True,
    )


def test_process_transaction_persists_nonce_and_reconcile_accepts_matching_receipt():
    membrane = Membrane(KernelBridge())
    first = membrane.process_transaction(
        lei="L", attempt_id="A1", payload=PAYLOAD, nonce="n-s1-01", receipt_lost=True
    )
    assert first.client_state == "UNKNOWN"
    assert membrane.attempts["A1"].nonce == "n-s1-01"

    result = membrane.reconcile(
        attempt_id="A1",
        evidence=_committed_evidence(evidence_id="E-MATCH", nonce="n-s1-01"),
    )
    assert result.client_state == "RESOLVED"
    assert membrane.attempts["A1"].state == AttemptState.RESOLVED


def test_process_transaction_rejects_receipt_with_different_nonce():
    membrane = Membrane(KernelBridge())
    membrane.process_transaction(
        lei="L", attempt_id="A1", payload=PAYLOAD, nonce="n-s1-01", receipt_lost=True
    )
    with pytest.raises(BindingError, match="nonce mismatch"):
        membrane.reconcile(
            attempt_id="A1",
            evidence=_committed_evidence(evidence_id="E-WRONG", nonce="n-autre"),
        )
    assert membrane.attempts["A1"].state == AttemptState.UNKNOWN
    assert len(membrane.sink.effects) == 1


@pytest.mark.parametrize("kwargs", [{}, {"nonce": ""}, {"nonce": None}])
def test_process_transaction_requires_nonce_before_registration(kwargs):
    membrane = Membrane(KernelBridge())
    with pytest.raises(ValueError, match="NONCE_REQUIRED"):
        membrane.process_transaction(
            lei="L", attempt_id="A1", payload=PAYLOAD, **kwargs
        )
    assert membrane.attempts == {}
    assert membrane.permits == {}
    assert membrane.events == []


def test_hard_veto_sets_failed_confirms_non_execution_and_unlocks_in_order():
    bridge = SequenceBridge(DENIED)
    membrane = Membrane(bridge)
    result = membrane.process_transaction(
        lei="L", attempt_id="A1", payload=PAYLOAD, nonce="n-veto-01"
    )

    attempt = membrane.attempts["A1"]
    assert result.disposition == Disposition.HARD_VETO
    assert result.client_state == "FAILED"
    assert attempt.state == AttemptState.FAILED
    assert attempt.non_execution_confirmed is True
    assert attempt.retry_eligible is False
    assert "A1" not in membrane.permits
    assert len(membrane.sink.effects) == 0
    names = [event["event"] for event in membrane.events]
    trio = [names.index("KernelVeto"), names.index("AttemptFailed"), names.index("LEIUnlocked")]
    assert trio == sorted(trio)
    assert bridge.calls == 1


def test_second_submit_after_hard_veto_gets_a_fresh_attempt_and_permit():
    bridge = SequenceBridge(DENIED, ALLOWED)
    membrane = Membrane(bridge)

    first = membrane.process_transaction(
        lei="L", attempt_id="A1", payload=PAYLOAD, nonce="n-veto-01"
    )
    second = membrane.process_transaction(
        lei="L", attempt_id="A2", payload=PAYLOAD, nonce="n-submit-02"
    )

    assert first.disposition == Disposition.HARD_VETO
    assert membrane.attempts["A1"].state == AttemptState.FAILED
    assert membrane.attempts["A1"].non_execution_confirmed is True
    assert second.disposition == Disposition.PASS
    assert second.client_state == "RESOLVED"
    assert "A1" not in membrane.permits
    assert "A2" in membrane.permits
    assert membrane.permits["A2"].attempt_id == "A2"
    assert membrane.permits["A2"] is not None
    assert bridge.calls == 2


def test_admit_and_await_qualification_applies_same_hard_veto_semantics():
    bridge = SequenceBridge(DENIED)
    membrane = Membrane(bridge)
    result = membrane.admit_and_await_qualification(
        lei="L", attempt_id="A1", payload=PAYLOAD, nonce="n-veto-await"
    )
    assert result.disposition == Disposition.HARD_VETO
    assert result.client_state == "FAILED"
    assert membrane.attempts["A1"].state == AttemptState.FAILED
    assert membrane.attempts["A1"].non_execution_confirmed is True
    assert "A1" not in membrane.permits
    assert membrane.retry_eligible_for("L") is True
