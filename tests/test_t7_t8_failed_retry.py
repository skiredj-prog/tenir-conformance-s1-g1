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
        lei="L", attempt_id="A", payload=PAYLOAD, receipt_lost=True
    )
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
        lei="L", attempt_id="A", payload=PAYLOAD, request_lost=True
    )
    m.declare_failed(
        attempt_id="A", evidence_qualified=True, retry_eligible=True
    )
    assert m.retry_eligible_for("L") is True

    second = m.process_transaction(
        lei="L", attempt_id="A2", payload=PAYLOAD, receipt_lost=False
    )
    assert "A2" in m.attempts
    assert second.kernel_decision != "NOT_EVALUATED"
    assert m.attempts["A"].state == AttemptState.FAILED


def test_t8_failed_not_retry_eligible_still_blocks():
    """FAILED + retry_eligible=False keeps LEI locked."""
    clock = FakeClock(now_ms=1_000_000)
    m = _m(clock)
    m.process_transaction(
        lei="L", attempt_id="A", payload=PAYLOAD, receipt_lost=True
    )
    m.declare_failed(
        attempt_id="A", evidence_qualified=True, retry_eligible=False
    )
    assert m.retry_eligible_for("L") is False
    blocked = m.retry(lei="L", attempt_id="A-retry", payload=PAYLOAD)
    assert blocked.kernel_decision == "NOT_EVALUATED"
    assert blocked.disposition.value == "HOLD"
    assert "A-retry" not in m.attempts or m.attempts.get("A-retry") is None
    assert blocked.client_state == "UNKNOWN"


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
        lei="L", attempt_id="A", payload=PAYLOAD, receipt_lost=True
    )
    assert m.retry_eligible_for("L") is False
    r = m.retry(lei="L", attempt_id="A2", payload=PAYLOAD)
    assert r.kernel_decision == "NOT_EVALUATED"
