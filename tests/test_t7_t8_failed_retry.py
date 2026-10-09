"""T7/T8 — FAILED state, evidence guard, retry_eligible."""

from tenir_conformance.membrane.membrane import (
    FakeClock,
    Membrane,
    AttemptState,
    Receipt,
)
from tenir_conformance.membrane.kernel_bridge import KernelBridge

PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}
TAU_K_MS = 5_000


def _m(clock=None):
    return Membrane(
        KernelBridge(),
        clock=clock or FakeClock(now_ms=1_000_000),
        tau_k_ms=TAU_K_MS,
    )


def test_timeout_alone_does_not_become_failed():
    """Critical: tau_K expiry leaves UNKNOWN, not FAILED."""
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=True
    )
    clock.advance_to(1_000_000 + TAU_K_MS)
    m.check_qualification_timeouts()
    assert m.attempts["A"].state == AttemptState.UNKNOWN
    assert m.attempts["A"].timeout_fired is True
    assert m.attempts["A"].retry_eligible is False


def test_t7_requires_evidence_qualification():
    """Without evidence_qualified, UNKNOWN must not transition to FAILED."""
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.process_transaction(
        nonce="n-t7t8-process_transaction-01",
        lei="L", attempt_id="A", payload=PAYLOAD, receipt_lost=True
    )
    assert m.attempts["A"].state == AttemptState.UNKNOWN
    rejected = m.declare_failed(
        attempt_id="A", evidence_qualified=False, retry_eligible=True
    )
    assert m.attempts["A"].state == AttemptState.UNKNOWN
    assert rejected.retry_eligible is False
    events = [e["event"] for e in m.events]
    assert "T7_REJECTED_UNQUALIFIED_EVIDENCE" in events
    assert "T7_DECLARE_FAILED" not in events


def test_t7_unknown_to_failed_with_qualified_evidence():
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.process_transaction(
        nonce="n-t7t8-process_transaction-02",
        lei="L", attempt_id="A", payload=PAYLOAD, request_lost=True
    )
    assert m.attempts["A"].effect_observed is False
    result = m.declare_failed(
        attempt_id="A",
        evidence_qualified=True,
        retry_eligible=True,
        reason="PROOF_NON_EXECUTION",
    )
    assert result.client_state == "FAILED"
    assert result.retry_eligible is True
    assert m.attempts["A"].state == AttemptState.FAILED
    assert m.attempts["A"].retry_eligible is True
    assert m.attempts["A"].failure_reason == "PROOF_NON_EXECUTION"
    events = [e["event"] for e in m.events]
    assert "T7_DECLARE_FAILED" in events


def test_t8_failed_retry_eligible_allows_new_attempt_same_lei():
    """FAILED + retry_eligible=True -> new attempt on same LEI is allowed."""
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.process_transaction(
        nonce="n-t7t8-process_transaction-03",
        lei="L", attempt_id="A", payload=PAYLOAD, request_lost=True
    )
    m.declare_failed(
        attempt_id="A", evidence_qualified=True, retry_eligible=True
    )
    assert m.retry_eligible_for("L") is True

    second = m.process_transaction(
        nonce="n-t7t8-process_transaction-04",
        lei="L", attempt_id="A2", payload=PAYLOAD, receipt_lost=False
    )
    assert "A2" in m.attempts
    assert second.kernel_decision != "NOT_EVALUATED"
    assert m.attempts["A"].state == AttemptState.FAILED


def test_t8_retry_eligibility_is_annotation_not_effect_lock():
    """FAILED without observed effect releases the LEI regardless of retry_eligible."""
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.process_transaction(
        nonce="n-t7t8-process_transaction-05",
        lei="L", attempt_id="A", payload=PAYLOAD, request_lost=True
    )
    m.declare_failed(
        attempt_id="A", evidence_qualified=True, retry_eligible=False
    )
    assert m.attempts["A"].state == AttemptState.FAILED
    assert m.attempts["A"].effect_observed is False
    assert m.attempts["A"].retry_eligible is False
    assert m.retry_eligible_for("L") is True
    second = m.retry(nonce="n-t7t8-retry-01", lei="L", attempt_id="A-retry", payload=PAYLOAD)
    assert "A-retry" in m.attempts
    assert second.kernel_decision != "NOT_EVALUATED"


def test_t7_after_timeout_still_requires_qualification():
    """After tau_K, explicit T7 with evidence can FAILED; without, stays UNKNOWN."""
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=False
    )
    clock.advance_to(1_000_000 + TAU_K_MS)
    m.check_qualification_timeouts()
    assert m.attempts["A"].state == AttemptState.UNKNOWN

    m.declare_failed(attempt_id="A", evidence_qualified=False)
    assert m.attempts["A"].state == AttemptState.UNKNOWN

    m.declare_failed(
        attempt_id="A", evidence_qualified=True, retry_eligible=True
    )
    assert m.attempts["A"].state == AttemptState.FAILED
    assert m.retry_eligible_for("L") is True


def test_t7_rejected_on_resolved_attempt():
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.admit_and_await_qualification(
        lei="L", attempt_id="A", payload=PAYLOAD, apply_effect=True, nonce="n-t7"
    )
    clock.tick(100)
    m.deliver_qualifying_receipt(Receipt(attempt_id="A", lei="L", nonce="n-t7"))
    assert m.attempts["A"].state == AttemptState.RESOLVED
    m.declare_failed(attempt_id="A", evidence_qualified=True)
    assert m.attempts["A"].state == AttemptState.RESOLVED
    events = [e["event"] for e in m.events]
    assert "T7_REJECTED_ALREADY_RESOLVED" in events


def test_unknown_still_blocks_retry_before_t7():
    """Regression: UNKNOWN without T7 continues to block (S1/S2 invariant)."""
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.process_transaction(
        nonce="n-t7t8-process_transaction-06",
        lei="L", attempt_id="A", payload=PAYLOAD, receipt_lost=True
    )
    assert m.retry_eligible_for("L") is False
    r = m.retry(nonce="n-t7t8-retry-02", lei="L", attempt_id="A2", payload=PAYLOAD)
    assert r.kernel_decision == "NOT_EVALUATED"



def test_target_rejection_is_failed_without_effect_and_releases_lei():
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    rejected = m.process_transaction(
        nonce="n-t7t8-process_transaction-07",
        lei="L", attempt_id="A1", payload=PAYLOAD, target_rejected=True
    )
    assert rejected.client_state == "FAILED"
    assert rejected.disposition.value == "HOLD"
    assert m.attempts["A1"].state == AttemptState.FAILED
    assert m.attempts["A1"].effect_observed is False
    assert len(m.sink.effects) == 0
    # retry_eligible=False does not override the confirmed absence of an effect.
    assert m.retry_eligible_for("L") is True
    second = m.process_transaction(nonce="n-t7t8-process_transaction-08", lei="L", attempt_id="A2", payload=PAYLOAD)
    assert "A2" in m.attempts
    assert second.kernel_decision != "NOT_EVALUATED"


def test_resolved_effect_permanently_blocks_same_lei():
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    first = m.process_transaction(nonce="n-t7t8-process_transaction-09", lei="L", attempt_id="A1", payload=PAYLOAD)
    assert first.client_state == "RESOLVED"
    assert m.attempts["A1"].effect_observed is True
    effects_before = len(m.sink.effects)
    second = m.process_transaction(nonce="n-t7t8-process_transaction-10", lei="L", attempt_id="A2", payload=PAYLOAD)
    assert second.disposition.value == "HOLD"
    assert second.kernel_decision == "NOT_EVALUATED"
    assert "A2" not in m.attempts
    assert len(m.sink.effects) == effects_before


def test_t7_cannot_declare_failed_after_observed_effect():
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.process_transaction(
        nonce="n-t7t8-process_transaction-11",
        lei="L", attempt_id="A1", payload=PAYLOAD, receipt_lost=True
    )
    assert m.attempts["A1"].state == AttemptState.UNKNOWN
    assert m.attempts["A1"].effect_observed is True
    result = m.declare_failed(
        attempt_id="A1", evidence_qualified=True, retry_eligible=True,
        reason="CLAIMED_NON_EXECUTION",
    )
    assert m.attempts["A1"].state == AttemptState.UNKNOWN
    assert result.retry_eligible is False
    assert m.retry_eligible_for("L") is False
    assert "T7_REJECTED_EFFECT_ALREADY_OBSERVED" in [e["event"] for e in m.events]
