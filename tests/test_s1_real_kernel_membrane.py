"""S1 against the RFC-4 membrane backed by the real TENIR PolicyEngine."""

from tenir_conformance.membrane import KernelBridge, Membrane

PAYLOAD = {"P": 0.5, "V": 0.5, "K": 1.0, "option_space": 1.0}


def run_subcase(*, request_lost: bool, receipt_lost: bool, target_rejected: bool):
    membrane = Membrane(KernelBridge())
    first = membrane.process_transaction(
        nonce="n-s1real-process_transaction-01",
        lei="L", attempt_id="A", payload=PAYLOAD,
        request_lost=request_lost, receipt_lost=receipt_lost,
        target_rejected=target_rejected,
    )
    retry = membrane.retry(nonce="n-s1real-retry-01", lei="L", attempt_id="A-retry", payload=PAYLOAD)
    return first, retry, membrane


def test_s1a_request_loss_is_unknown_hold_and_retry_is_not_executed():
    first, retry, membrane = run_subcase(request_lost=True, receipt_lost=False, target_rejected=False)
    assert first.client_state == "UNKNOWN"
    assert first.disposition.value == "HOLD"
    assert retry.disposition.value == "HOLD"
    assert retry.client_state == "UNKNOWN"
    assert len(membrane.sink.effects) == 0


def test_s1b_commit_then_receipt_loss_is_unknown_hold_and_retry_is_not_executed():
    first, retry, membrane = run_subcase(request_lost=False, receipt_lost=True, target_rejected=False)
    assert first.client_state == "UNKNOWN"
    assert first.disposition.value == "HOLD"
    assert first.effect_count == 1
    assert retry.disposition.value == "HOLD"
    assert retry.client_state == "UNKNOWN"
    assert len(membrane.sink.effects) == 1


def test_s1c_rejection_receipt_loss_is_unknown_hold_and_retry_is_not_executed():
    first, retry, membrane = run_subcase(request_lost=False, receipt_lost=True, target_rejected=True)
    assert first.client_state == "UNKNOWN"
    assert first.disposition.value == "HOLD"
    assert retry.disposition.value == "HOLD"
    assert retry.client_state == "UNKNOWN"
    assert len(membrane.sink.effects) == 0


def test_all_s1_subcases_have_identical_client_projection_and_real_kernel_score():
    cases = [
        run_subcase(request_lost=True, receipt_lost=False, target_rejected=False),
        run_subcase(request_lost=False, receipt_lost=True, target_rejected=False),
        run_subcase(request_lost=False, receipt_lost=True, target_rejected=True),
    ]
    projections = [(first.client_state, first.disposition.value, retry.client_state, retry.disposition.value)
                   for first, retry, _ in cases]
    assert projections == [("UNKNOWN", "HOLD", "UNKNOWN", "HOLD")] * 3
    assert all(abs(first.kernel_score - 3.999984000064) < 1e-9 for first, _, _ in cases)
    assert all(first.kernel_decision == "allow" for first, _, _ in cases)


def test_retry_does_not_call_kernel_when_same_lei_is_unresolved():
    class CountingBridge(KernelBridge):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def evaluate(self, payload):
            self.calls += 1
            return super().evaluate(payload)

    bridge = CountingBridge()
    membrane = Membrane(bridge)
    membrane.process_transaction(nonce="n-s1real-process_transaction-02", lei="L", attempt_id="A", payload=PAYLOAD, receipt_lost=True)
    assert bridge.calls == 1
    membrane.retry(nonce="n-s1real-retry-02", lei="L", attempt_id="A-retry", payload=PAYLOAD)
    assert bridge.calls == 1
